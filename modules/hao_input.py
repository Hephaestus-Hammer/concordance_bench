#!/usr/bin/env python3
"""Hao .h5ad -> the omni-scrna FEAT stage output + truth labels.

Reads one rung of the published sc-brrr input (huggingface.co/datasets/btraven/sc-brrr-hao2021,
built by sc-brrr's prep/export.py): X = log-normalised HVG matrix, cells x genes, with
obs["label"] and obs["label_cl"]. Writes what the omni-scrna PCA stage reads, so the
scanpy and rapids modules run on it unchanged:

  {output_dir}/{name}_normalized_selected.h5   /matrix: CSC genes x cells (10x layout)
  {output_dir}/{name}.clusters_truth.tsv        cell_id<TAB>truths<TAB>truths_cl

Genes with no counts in this rung are dropped: subsamples of the HVG set have some, and
rapids' sparse PCA refuses them. With zero variance they don't change centred PCs.

--replicate is accepted and ignored. Giving it several values makes several identical
lineages, so every downstream stage runs once per replicate.
"""

import argparse
from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import scipy.sparse as sp


def write_omni_h5(X, genes, cells, path):
    """Cells x genes CSR is the CSC of genes x cells, which is the omni-scrna layout."""
    with h5py.File(path, "w") as h5:
        g = h5.create_group("matrix")
        for k in ("data", "indices", "indptr"):
            g.create_dataset(k, data=getattr(X, k))
        g.create_dataset("shape", data=np.array([X.shape[1], X.shape[0]]))
        g.create_dataset("genes", data=np.array(genes, dtype="S"))
        g.create_dataset("barcodes", data=np.array(cells, dtype="S"))


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--output_dir", type=Path, required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--data_h5ad", type=Path, required=True)
    p.add_argument("--replicate", type=int, default=0)
    args = p.parse_args()

    a = ad.read_h5ad(args.data_h5ad)
    X = sp.csr_matrix(a.X, dtype=np.float32)
    keep = np.bincount(X.indices, minlength=X.shape[1]) > 0
    X, genes = X[:, keep], a.var_names[keep]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_omni_h5(X, genes, a.obs_names, args.output_dir / f"{args.name}_normalized_selected.h5")
    truth = pd.DataFrame({"cell_id": a.obs_names, "truths": a.obs["label"].astype(str).to_numpy(),
                          "truths_cl": a.obs["label_cl"].astype(str).to_numpy()})
    truth.to_csv(args.output_dir / f"{args.name}.clusters_truth.tsv", sep="\t", index=False)
    print(f"{args.name}: {X.shape[0]} cells x {X.shape[1]} genes ({(~keep).sum()} empty genes dropped)")


if __name__ == "__main__":
    main()
