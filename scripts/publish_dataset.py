#!/usr/bin/env python3
"""Prepare one dataset for Phase 2: raw labelled .h5ad -> the .h5ad to publish on Hugging Face.

Every dataset is preprocessed once, the same way, and published (as sc-brrr published Hao),
so the plan's input modules can treat all datasets alike (docs/datasets.md):

  X           log1p(counts per 10,000) of the 2,000 most variable genes of the whole
              dataset (scanpy `seurat` flavour); skipped with --already_normalized
  obs.label   the reference labels, renamed from --label_key; unlabelled cells dropped

Then upload the file and pin its revision and sha256 in benchmark-phase2.yaml.

    python scripts/publish_dataset.py raw.h5ad pancreas.h5ad --label_key celltype
"""

import argparse
import hashlib
import sys
from pathlib import Path

import anndata as ad
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "modules"))
from dataset_input import prepare  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("raw", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--label_key", required=True)
    p.add_argument("--n_hvg", type=int, default=2000)
    p.add_argument("--already_normalized", action="store_true",
                   help="X is already log-normalised (skip normalisation)")
    args = p.parse_args()

    raw = ad.read_h5ad(args.raw)
    X, genes, cells, labels = prepare(raw, args.label_key, 0,
                                      "none" if args.already_normalized else "log1p_cp10k",
                                      args.n_hvg)
    out = ad.AnnData(X=X, obs=pd.DataFrame({"label": pd.Categorical(labels)}, index=cells),
                     var=pd.DataFrame(index=genes))
    out.write_h5ad(args.out, compression="gzip")
    sha = hashlib.sha256(args.out.read_bytes()).hexdigest()
    print(f"{args.out}: {out.n_obs} cells x {out.n_vars} genes, {out.obs['label'].nunique()} labels")
    print(f"sha256: {sha}")


if __name__ == "__main__":
    main()
