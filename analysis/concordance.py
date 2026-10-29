"""Concordance between runs and seeds: PCA |cos| and subspace, kNN overlap, ARI.

Every metric here is defined in docs/metrics.md. Once proven, this becomes the
modules/concordance.py stage.

The metric functions take outputs already aligned to one cell order.
"""

import h5py
import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.metrics import normalized_mutual_info_score


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


def pca_basis(a, k):
    """Orthonormal basis of the span of the first k components (cells x k)."""
    q, _ = np.linalg.qr(np.asarray(a, dtype=np.float64)[:, :k])
    return q


def pca_max_angle(a, b, k=None, qa=None, qb=None):
    """Largest principal angle (degrees) between the spans of the first k components.

    Pass precomputed bases (pca_basis) as qa, qb to reuse them across pairs. Uses the
    sine form, which stays accurate for the tiny angles between near-identical runs
    (the cosine form, arccos of ~1, does not).
    """
    qa = pca_basis(a, k) if qa is None else qa
    qb = pca_basis(b, k) if qb is None else qb
    resid = qb - qa @ (qa.T @ qb)  # part of b's span outside a's span
    s = np.sqrt(max(np.linalg.eigvalsh(resid.T @ resid)[-1], 0.0))  # its largest singular value
    return float(np.degrees(np.arcsin(min(s, 1.0))))


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


def nearest(d, k):
    """Each cell's k nearest neighbours as sorted keys plus their rows, for reuse across pairs."""
    keys, rows = _nearest_keys(d, k)
    order = np.argsort(keys)
    return keys[order], rows[order], d.shape[0]


def knn_shared_fraction(d1, d2, k=None, n1=None, n2=None):
    """Per cell: share of its k nearest neighbours that the two graphs have in common.

    k defaults to the smaller of the two graphs' neighbours per cell. Pass
    precomputed nearest(d, k) as n1, n2 to reuse them across pairs.
    """
    if k is None:
        k = min(neighbours_per_cell(d1), neighbours_per_cell(d2))
    k1, r1, n = nearest(d1, k) if n1 is None else n1
    k2, r2, _ = nearest(d2, k) if n2 is None else n2
    pos = np.searchsorted(k2, k1).clip(max=len(k2) - 1)
    shared = np.bincount(r1[k2[pos] == k1], minlength=n)
    size = np.maximum(np.bincount(r1, minlength=n), np.bincount(r2, minlength=n))
    return np.divide(shared, size, out=np.ones(n), where=size > 0)


# ---- clustering ----------------------------------------------------------------

def codes(labels):
    """Labels as integer codes 0..m-1: compute once per clustering, reuse for every pair."""
    return pd.factorize(np.asarray(labels))[0]


def _comb2(x):
    x = x.astype(np.float64)
    return (x * (x - 1) / 2).sum()


def ari(a, b):
    """Adjusted Rand index (same value as sklearn's), fast on integer codes from codes()."""
    a = a if np.issubdtype(np.asarray(a).dtype, np.integer) else codes(a)
    b = b if np.issubdtype(np.asarray(b).dtype, np.integer) else codes(b)
    a, b = np.asarray(a, dtype=np.int64), np.asarray(b, dtype=np.int64)
    nb = int(b.max()) + 1
    table = np.bincount(a * nb + b, minlength=(int(a.max()) + 1) * nb)
    sum_ij = _comb2(table)
    sum_a, sum_b = _comb2(np.bincount(a)), _comb2(np.bincount(b))
    total = len(a) * (len(a) - 1) / 2
    expected = sum_a * sum_b / total
    top = (sum_a + sum_b) / 2
    if top == expected:  # both partitions trivial (one cluster each, or all singletons)
        return 1.0
    return float((sum_ij - expected) / (top - expected))


def nmi(a, b):
    return float(normalized_mutual_info_score(a, b))
