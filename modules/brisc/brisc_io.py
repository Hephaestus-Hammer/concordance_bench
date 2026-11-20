"""Input and output for the brisc stage scripts (modules/brisc/), in the layouts the omni-scrna
modules use, so every other stage and the analysis read them unchanged:

  input       {name}_normalized_selected.h5: omni (/matrix CSC genes x cells, genes, barcodes)
              or 10x v3 (/matrix/features/id) HDF5. Already normalised and HVG-selected.
  embedding   {name}_embedding.tsv: cell_id, PC1..PCn
  loadings    {name}_loadings.tsv: gene_id, PC1..PCn
  neighbors   {name}_neighbors.h5: /cell_ids (fixed-length strings), the distances CSR flat at the
              root (data, indices, indptr) and the connectivities CSR under /connectivities
  clusters    {name}_clusters.tsv: cell_id, cluster

brisc keeps its own state in a SingleCell; these functions convert to and from it.
"""

import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import polars as pl
import scipy.sparse as sp


def threads(n):
    """n > 0, else the cores this job may use (Slurm's allocation through the affinity mask)."""
    return int(n) if int(n) > 0 else len(os.sched_getaffinity(0))


def read_matrix(path):
    """(cells x genes CSR float32, genes, cells) from an omni or 10x HDF5 file. float32: brisc's
    pca() takes normalised values only in float32, the type its own normalize() produces."""
    with h5py.File(path, "r") as h5:
        if "matrix" not in h5:
            raise ValueError(f"{path}: no /matrix group (brisc reads omni or 10x HDF5; h5ad is not supported)")
        g = h5["matrix"]
        shape = tuple(int(x) for x in g["shape"][:])
        X = sp.csc_matrix((g["data"][:], g["indices"][:], g["indptr"][:]), shape=shape).T.tocsr()
        genes = (g["genes"] if "genes" in g else g["features/id"])[:].astype(str)
        cells = g["barcodes"][:].astype(str)
    X = sp.csr_array(X.astype(np.float32))
    X.sort_indices()
    return X, genes, cells


def write_table(path, ids, id_name, values, prefix):
    cols = {f"{prefix}{i + 1}": values[:, i] for i in range(values.shape[1])}
    pd.DataFrame({id_name: ids, **cols}).to_csv(path, sep="\t", index=False)


def read_embedding(path):
    """(cells, n x d float64) from an embedding TSV with the cell ids in the first column."""
    t = pl.read_csv(path, separator="\t")
    return t[:, 0].cast(pl.Utf8).to_numpy(), t[:, 1:].to_numpy().astype(np.float64)


def _write_csr(group, m):
    m = sp.csr_matrix(m)
    m.sort_indices()
    for k in ("data", "indices", "indptr"):
        group.create_dataset(k, data=getattr(m, k))


def write_neighbors(path, cells, distances, connectivities):
    with h5py.File(path, "w") as h5:
        h5.create_dataset("cell_ids", data=np.array(list(cells), dtype="S"))
        _write_csr(h5, distances)
        _write_csr(h5.create_group("connectivities"), connectivities)


def read_neighbors(path):
    """(cells, distances CSR, connectivities CSR)."""
    with h5py.File(path, "r") as h5:
        cells = h5["cell_ids"][:].astype(str)
        n = len(cells)
        d = sp.csr_matrix((h5["data"][:], h5["indices"][:], h5["indptr"][:]), shape=(n, n))
        c = h5["connectivities"]
        conn = sp.csr_matrix((c["data"][:], c["indices"][:], c["indptr"][:]), shape=(n, n))
    return cells, d, conn


def neighbors_from_distances(d):
    """Each cell's neighbours as an (n x k) uint32 array, nearest first (brisc's obsm['neighbors'],
    which min_cluster_size merges by). k is the most any row holds: a sparse kNN graph drops a
    neighbour at distance 0 (a duplicate cell), so such a row is padded with its nearest neighbour
    (itself if it has none), which only repeats a vote when small clusters are merged."""
    d = sp.csr_matrix(d)
    counts = np.diff(d.indptr)
    n, k = d.shape[0], int(counts.max()) if len(counts) else 0
    out = np.empty((n, k), dtype=np.uint32)
    for i in range(n):
        lo, hi = d.indptr[i], d.indptr[i + 1]
        row = d.indices[lo:hi][np.argsort(d.data[lo:hi], kind="stable")]
        if len(row) < k:
            row = np.concatenate([row, np.full(k - len(row), row[0] if len(row) else i)])
        out[i] = row
    return np.ascontiguousarray(out)


def single_cell(X=None, cells=None, genes=None, n=None, obsm=None, obsp=None, num_threads=1):
    """A brisc SingleCell holding already normalised data (uns['normalized'] set: brisc's pca()
    refuses counts it has not normalised itself) and no QC or HVG columns (the input stage
    selected the genes). Without X, a placeholder cells x 1 all-zero matrix carries obsm/obsp
    (brisc wants at least one gene)."""
    from brisc import SingleCell
    if X is None:
        X, genes = sp.csr_array((n, 1), dtype=np.float32), ["_placeholder"]
    obs = pl.DataFrame({"cell": list(cells)})
    var = pl.DataFrame({"gene": list(genes) if genes is not None else []}, schema={"gene": pl.Utf8})
    return SingleCell(X=X, obs=obs, var=var, obsm=obsm or {}, obsp=obsp or {},
                      uns={"normalized": True, "QCed": True}, num_threads=num_threads)


def stage_dir(output_dir):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    return out
