#!/usr/bin/env python3
"""Any labelled .h5ad -> one nested, label-stratified subsample in the omni-scrna FEAT layout.

In the plan, datasets arrive already preprocessed by scripts/publish_dataset.py (labels in
obs.label, X log-normalised on 2,000 HVGs), so the defaults (--normalize none, --n_hvg 0)
apply; the options exist for running on a raw file directly.

The Phase 2 counterpart of hao_input.py, for every dataset (docs/phase2-plan.md). Reads a
whole dataset and writes what the omni-scrna PCA stage reads, so the scanpy and rapids
modules run on it unchanged:

  {output_dir}/{name}_normalized_selected.h5   /matrix: CSC genes x cells (10x layout)
  {output_dir}/{name}.clusters_truth.tsv        cell_id<TAB>truths

Steps, all on the whole dataset first so every subsample of it shares them:

1. Cells without a label (NA, empty) are dropped: accuracy needs a reference for every cell.
2. --normalize log1p_cp10k: counts to 10,000 per cell, then log1p (scanpy's
   normalize_total + log1p). none: X is used as given (already normalised, like sc-brrr).
   Normalisation is per cell, so it does not depend on which cells are kept.
3. --n_hvg N > 0: the N most variable genes of the whole dataset (scanpy
   highly_variable_genes, --hvg_flavor, on the log data), the same genes at every size.
   0: keep the genes as given.
4. Subsample: the first --n_cells cells of one fixed ordering of the whole dataset. The
   ordering interleaves the labels in proportion (each cell's random rank within its
   label, divided by the label's size), so every prefix keeps the label proportions
   (each label within one cell of its share) and every smaller subsample is contained
   in every larger one: nested by construction. --order_seed fixes the ordering; it is a
   design constant, not a seed axis. --n_cells 0 = every labelled cell.
5. Genes with no counts in the subsample are dropped (rapids' sparse PCA refuses them;
   with zero variance they do not change centred PCs).

--replicate is accepted and ignored, as in hao_input.py: several values give identical
lineages (same-seed replicates).
"""

import argparse
import sys
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import scipy.sparse as sp

sys.path.insert(0, str(Path(__file__).parent))
from hao_input import write_omni_h5  # noqa: E402


def stratified_order(labels, seed=0):
    """A permutation of the cells whose every prefix keeps the label proportions.

    Within each label the cells get a random rank r = 0..m-1; a cell's key is
    (r + u) / m with u uniform in [0, 1), and cells are sorted by key. A prefix of
    length n then holds n * m / N +- 1 cells of a label of size m, for every n.
    """
    labels = np.asarray(labels)
    rng = np.random.default_rng(seed)
    key = np.empty(len(labels))
    for lab in np.unique(labels):
        idx = np.flatnonzero(labels == lab)
        rank = rng.permutation(len(idx))
        key[idx] = (rank + rng.random(len(idx))) / len(idx)
    return np.argsort(key, kind="stable")


def _labelled(obs, label_key):
    lab = obs[label_key]
    s = lab.astype(str).str.strip()
    return (lab.notna() & (s != "") & (s.str.lower() != "nan")).to_numpy()


def prepare(a, label_key, n_cells=0, normalize="none", n_hvg=0, hvg_flavor="seurat", order_seed=0):
    """The subsample as (X cells x genes CSR float32, genes, cells, labels)."""
    a = a[_labelled(a.obs, label_key)].copy()
    a.X = sp.csr_matrix(a.X, dtype=np.float64)
    if normalize == "log1p_cp10k":
        import scanpy as sc
        sc.pp.normalize_total(a, target_sum=1e4)
        sc.pp.log1p(a)
    elif normalize != "none":
        raise SystemExit(f"unknown --normalize {normalize!r}")
    if n_hvg > 0 and n_hvg < a.n_vars:
        import scanpy as sc
        sc.pp.highly_variable_genes(a, n_top_genes=n_hvg, flavor=hvg_flavor)
        a = a[:, a.var["highly_variable"].to_numpy()].copy()
    order = stratified_order(a.obs[label_key].astype(str).to_numpy(), order_seed)
    if n_cells > 0:
        if n_cells > a.n_obs:
            raise SystemExit(f"--n_cells {n_cells} > {a.n_obs} labelled cells: exclude this "
                             "dataset from this subsample size in the plan")
        order = order[:n_cells]
    a = a[np.sort(order)]  # keep the dataset's own cell order within the subsample
    X = sp.csr_matrix(a.X, dtype=np.float32)
    keep = np.bincount(X.indices, minlength=X.shape[1]) > 0
    return X[:, keep], a.var_names[keep], a.obs_names, a.obs[label_key].astype(str).to_numpy()


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--output_dir", type=Path, required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--data_h5ad", type=Path, required=True)
    p.add_argument("--label_key", default="label",
                   help="obs column with the reference labels (published datasets use obs.label)")
    p.add_argument("--n_cells", type=int, default=0, help="subsample size; 0 = every labelled cell")
    p.add_argument("--normalize", default="none", choices=["none", "log1p_cp10k"])
    p.add_argument("--n_hvg", type=int, default=0, help="highly variable genes of the whole dataset; 0 = keep all")
    p.add_argument("--hvg_flavor", default="seurat", choices=["seurat", "cell_ranger", "seurat_v3"])
    p.add_argument("--order_seed", type=int, default=0, help="fixes the nested ordering (a design constant)")
    p.add_argument("--replicate", type=int, default=0)
    args = p.parse_args()

    a = ad.read_h5ad(args.data_h5ad)
    if args.label_key not in a.obs:
        raise SystemExit(f"--label_key {args.label_key!r} not in obs: {list(a.obs.columns)}")
    X, genes, cells, labels = prepare(a, args.label_key, args.n_cells, args.normalize,
                                      args.n_hvg, args.hvg_flavor, args.order_seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_omni_h5(X, genes, cells, args.output_dir / f"{args.name}_normalized_selected.h5")
    pd.DataFrame({"cell_id": cells, "truths": labels}).to_csv(
        args.output_dir / f"{args.name}.clusters_truth.tsv", sep="\t", index=False)
    print(f"{args.name}: {X.shape[0]} cells x {X.shape[1]} genes, {len(set(labels))} labels")


if __name__ == "__main__":
    main()
