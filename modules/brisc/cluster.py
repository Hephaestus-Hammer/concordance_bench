#!/usr/bin/env python3
"""Leiden with brisc's defaults: SingleCell.cluster on the connectivities of a *_neighbors.h5
file (the SNN graph from modules/brisc/knn.py), one resolution per job as the plan runs every
Leiden; clusters smaller than 5 cells merged into a neighbouring cluster (brisc's
min_cluster_size, which needs each cell's neighbours: read from the distances graph).

Phases (obkit-events.jsonl): load (HDF5 -> SingleCell), leiden, write.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import brisc_io as io  # noqa: E402
from phases import init_logger, phase  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--output_dir", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--neighbors_h5", required=True)
    p.add_argument("--resolution", type=float, required=True)
    p.add_argument("--min_cluster_size", type=int, default=5)
    p.add_argument("--random_seed", type=int, default=0)
    p.add_argument("--num_threads", type=int, default=1, help="brisc's Leiden is serial; 0: every core")
    return p.parse_args()


def main():
    args = parse_args()
    print(f"Full command: {' '.join(sys.argv)}")
    out = io.stage_dir(args.output_dir)
    init_logger(str(out))
    nt = io.threads(args.num_threads)

    with phase("load") as attrs:
        cells, d, conn = io.read_neighbors(args.neighbors_h5)
        conn = conn.tocsr()
        conn.sort_indices()
        a = io.single_cell(cells=cells, n=len(cells), obsm={"neighbors": np.ascontiguousarray(io.neighbors_from_distances(d))},
                           obsp={"shared_neighbors": conn}, num_threads=nt)
        attrs["n_cells"], attrs["connectivities_nnz"] = len(cells), conn.nnz

    with phase("leiden") as attrs:
        a = a.cluster(QC_column=None, resolution=args.resolution, min_cluster_size=args.min_cluster_size,
                      seed=args.random_seed, num_threads=nt)
        labels = a.obs["cluster"].to_numpy()
        attrs["resolution"], attrs["n_clusters"] = args.resolution, int(len(set(labels)))

    with phase("write"):
        path = out / f"{args.name}_clusters.tsv"
        pd.DataFrame({"cell_id": cells, "cluster": labels}).to_csv(path, sep="\t", index=False)
    print(f"  wrote: {path}")


if __name__ == "__main__":
    main()
