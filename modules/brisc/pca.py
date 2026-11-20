#!/usr/bin/env python3
"""PCA with brisc's defaults (SingleCell.pca): genes scaled to unit variance inside the solver
(implicitly: the sparse matrix is never densified), 50 PCs, block Krylov (IRLBA-like) with a
subspace of 100, on every core the job has.

The input is already normalised and HVG-selected, so pca() runs with hvg_column=None and
QC_column=None. brisc computes in float32 always (pca() accepts normalised values only as
float32, the type its normalize() produces), so it has no dtype parameter. brisc does not return the loadings; for the {name}_loadings.tsv the plan
declares, they are recovered in `write` (not timed as work) by projecting the scaled genes onto
the PCs: V = Z^T U / ||Z^T U||, Z the scaled matrix, U the PCs (zero mean, so the centring drops
out: Z^T U = (X^T U) / sd).

Phases (obkit-events.jsonl): load (HDF5 -> SingleCell), pca, write.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sp

sys.path.insert(0, str(Path(__file__).parent))
import brisc_io as io  # noqa: E402
from phases import init_logger, phase  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--output_dir", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--normalized_selected_h5", required=True)
    p.add_argument("--n_components", type=int, default=50)
    p.add_argument("--random_seed", type=int, default=0)
    p.add_argument("--num_threads", type=int, default=0, help="0: every core the job has")
    return p.parse_args()


def loadings(X, pcs):
    """Unit-norm gene loadings of the scaled matrix for these PCs (see the module docstring)."""
    Xd = sp.csc_matrix(X, dtype=np.float64)
    mean = np.asarray(Xd.mean(axis=0)).ravel()
    var = np.asarray(Xd.multiply(Xd).mean(axis=0)).ravel() - mean ** 2
    sd = np.sqrt(np.maximum(var * X.shape[0] / max(X.shape[0] - 1, 1), 0))
    sd = np.maximum(sd, 1e-8)  # as brisc clips tiny standard deviations
    u = pcs - pcs.mean(axis=0)
    v = (Xd.T @ u) / sd[:, None]
    return v / np.linalg.norm(v, axis=0, keepdims=True)


def main():
    args = parse_args()
    print(f"Full command: {' '.join(sys.argv)}")
    out = io.stage_dir(args.output_dir)
    init_logger(str(out))
    nt = io.threads(args.num_threads)

    with phase("load") as attrs:
        X, genes, cells = io.read_matrix(args.normalized_selected_h5)
        a = io.single_cell(X, cells, genes, num_threads=nt)
        attrs["n_cells"], attrs["n_genes"] = X.shape

    with phase("pca") as attrs:
        a = a.pca(QC_column=None, hvg_column=None, num_PCs=args.n_components, seed=args.random_seed,
                  num_threads=nt)
        attrs["n_components"], attrs["num_threads"] = args.n_components, nt

    with phase("write"):
        pcs = np.asarray(a.obsm["pca"], dtype=np.float64)
        io.write_table(out / f"{args.name}_embedding.tsv", cells, "cell_id", pcs, "PC")
        io.write_table(out / f"{args.name}_loadings.tsv", genes, "gene_id", loadings(X, pcs), "PC")
    print(f"  wrote: {out / (args.name + '_embedding.tsv')}")


if __name__ == "__main__":
    main()
