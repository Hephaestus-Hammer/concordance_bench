"""Concordance between runs and seeds: PCA |cos| and subspace, kNN overlap, ARI.

Every metric here is defined in docs/metrics.md. Once proven, this becomes the
modules/concordance.py stage.

The metric functions take outputs already aligned to one cell order.
"""

import h5py
import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy.linalg import subspace_angles
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score


# ---- readers (the omni-scrna stage formats) ------------------------------------

def read_embedding(path):
    """embedding_tsv: header cell_id + one column per component; cells as rows."""
    return pd.read_csv(path, sep="\t", index_col=0)


def read_neighbors(path):
    """neighbors_h5: kNN distances as CSR at the file root, cell_ids alongside."""
    with h5py.File(path, "r") as h5:
        cells = pd.Index(h5["cell_ids"][:].astype(str))
        n = len(cells)
        d = sp.csr_matrix((h5["data"][:], h5["indices"][:], h5["indptr"][:]), shape=(n, n))
    return d, cells


def read_clusters(path):
    """clusters_tsv: cell_id, cluster."""
    return pd.read_csv(path, sep="\t", index_col=0).iloc[:, 0].astype(str)


def read_truth(path):
    """rawdata_clusters_truth: cell_id plus label columns (truths, truths_cl)."""
    return pd.read_csv(path, sep="\t", index_col=0).astype(str)


def align_graph(d, cells, order):
    """Reorder a square cell x cell matrix to `order` (a pandas Index of cell ids)."""
    if cells.equals(order):
        return d
    perm = cells.get_indexer(order)
    if (perm < 0).any():
        raise ValueError("kNN graph is missing cells present in the reference order")
    return d[perm][:, perm].tocsr()


# ---- PCA -----------------------------------------------------------------------

def pca_one_minus_abs_cos(a, b):
    """Per component: 1 - |cos| between the two score vectors (sign-invariant)."""
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    k = min(a.shape[1], b.shape[1])
    a, b = a[:, :k], b[:, :k]
    cos = np.abs((a * b).sum(0)) / (np.linalg.norm(a, axis=0) * np.linalg.norm(b, axis=0))
    return 1 - np.clip(cos, 0, 1)


def pca_max_angle(a, b, k):
    """Largest principal angle (degrees) between the spans of the first k components."""
    a = np.asarray(a, dtype=np.float64)[:, :k]
    b = np.asarray(b, dtype=np.float64)[:, :k]
    return float(np.degrees(subspace_angles(a, b).max()))


# ---- kNN -----------------------------------------------------------------------

def neighbours_per_cell(d):
    """Stored neighbours per cell, not counting the cell itself (median over cells)."""
    c = d.tocoo()
    return int(np.median(np.bincount(c.row[c.row != c.col], minlength=d.shape[0])))


def _nearest_keys(d, k):
    """Each cell's k nearest stored neighbours (by distance, self excluded), as row * n + col.

    Modules do not store the same number of neighbours: scanpy keeps n_neighbors - 1
    on its exact path but pynndescent's raw n_neighbors (+ self) on its approximate
    path. Comparing the k nearest on both sides compares like with like. Stored zero
    distances to other cells (duplicates) are kept: they are real neighbours.
    """
    c = d.tocoo()
    keep = c.row != c.col
    rows, cols, dist = c.row[keep].astype(np.int64), c.col[keep], c.data[keep]
    order = np.lexsort((cols, dist, rows))  # by row, then distance, then index for ties
    rows, cols = rows[order], cols[order]
    start = np.searchsorted(rows, rows)  # first position of each row
    take = (np.arange(len(rows)) - start) < k
    return rows[take] * d.shape[0] + cols[take], rows[take]


def knn_shared_fraction(d1, d2, k=None):
    """Per cell: share of its k nearest neighbours that the two graphs have in common.

    k defaults to the smaller of the two graphs' neighbours per cell.
    """
    n = d1.shape[0]
    if k is None:
        k = min(neighbours_per_cell(d1), neighbours_per_cell(d2))
    k1, r1 = _nearest_keys(d1, k)
    k2, r2 = _nearest_keys(d2, k)
    shared = np.bincount(r1[np.isin(k1, k2)], minlength=n)
    size = np.maximum(np.bincount(r1, minlength=n), np.bincount(r2, minlength=n))
    return np.divide(shared, size, out=np.ones(n), where=size > 0)


# ---- clustering ----------------------------------------------------------------

def ari(a, b):
    return float(adjusted_rand_score(a, b))


def nmi(a, b):
    return float(normalized_mutual_info_score(a, b))
