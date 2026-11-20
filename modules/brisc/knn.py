#!/usr/bin/env python3
"""kNN with brisc's defaults: SingleCell.neighbors (faiss-style IVF: k-means cells into
clusters, search the nearest clusters exhaustively; k = 20, a cell not its own neighbour), then
SingleCell.shared_neighbors (the Jaccard shared-nearest-neighbour graph, as Seurat's, pairs with
fewer than 3 shared neighbours dropped), on every core the job has.

Output {name}_neighbors.h5: distances = the kNN graph, Euclidean (brisc stores squared
distances; the square root is taken in `write`); connectivities = the SNN graph brisc clusters.

Phases (obkit-events.jsonl): load (TSV -> SingleCell), knn (neighbors + shared_neighbors), write.
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
    p.add_argument("--embedding_tsv", required=True)
    p.add_argument("--k", type=int, default=20, help="neighbours per cell, itself excluded (brisc's num_neighbors)")
    p.add_argument("--min_shared_neighbors", type=int, default=3)
    p.add_argument("--random_seed", type=int, default=0)
    p.add_argument("--num_threads", type=int, default=0, help="0: every core the job has")
    return p.parse_args()


def main():
    args = parse_args()
    print(f"Full command: {' '.join(sys.argv)}")
    out = io.stage_dir(args.output_dir)
    init_logger(str(out))
    nt = io.threads(args.num_threads)

    with phase("load") as attrs:
        cells, emb = io.read_embedding(args.embedding_tsv)
        a = io.single_cell(cells=cells, n=len(cells), obsm={"pca": np.ascontiguousarray(emb, dtype=np.float32)}, num_threads=nt)
        attrs["n_cells"], attrs["n_dims"] = emb.shape

    with phase("knn") as attrs:
        a = a.neighbors(QC_column=None, num_neighbors=args.k, seed=args.random_seed, num_threads=nt)
        a = a.shared_neighbors(QC_column=None, min_shared_neighbors=args.min_shared_neighbors, num_threads=nt)
        attrs["k"], attrs["num_threads"] = args.k, nt

    with phase("write"):
        idx = np.asarray(a.obsm["neighbors"])
        dist = np.sqrt(np.maximum(np.asarray(a.obsm["distances"], dtype=np.float64), 0))
        n, k = idx.shape
        dist[dist == 0] = np.finfo(np.float64).tiny  # a duplicate cell stays an edge
        d = sp.csr_matrix((dist.ravel(), (np.repeat(np.arange(n), k), idx.ravel())), shape=(n, n))
        io.write_neighbors(out / f"{args.name}_neighbors.h5", cells, d, a.obsp["shared_neighbors"])
    print(f"  wrote: {out / (args.name + '_neighbors.h5')}")


if __name__ == "__main__":
    main()
