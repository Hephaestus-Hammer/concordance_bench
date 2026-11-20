"""The file formats the input stage can write, and the reader the PCA modules use to detect them.

Every format is HDF5 and goes to the same path ({name}_normalized_selected.h5), so the plan's
stage outputs do not change; the readers tell them apart by what is inside:

  omni     /matrix/{data,indices,indptr,shape,genes,barcodes}: CSC genes x cells, the omni-scrna
           intermediate layout (what every module read so far). Always sparse.
  10x      /matrix/{data,indices,indptr,shape,barcodes} + /matrix/features/{id,name,
           feature_type,genome}: Cell Ranger's v3 HDF5, read with scanpy.read_10x_h5 where scanpy
           is installed. Always sparse.
  h5ad     AnnData (cells x genes), read with anndata.read_h5ad. --layout sparse (CSR) or dense.

detect() and read_matrix() here are the reference; the PCA modules in the scanpy fork and the
rapids-singlecell module carry the same logic (they cannot import this file).
"""

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import scipy.sparse as sp

FORMATS = ("omni", "10x", "h5ad")
LAYOUTS = ("sparse", "dense")


def write_matrix(X, genes, cells, path, fmt="omni", layout="sparse"):
    """X: cells x genes (sparse or dense). omni and 10x are sparse by definition."""
    if fmt not in FORMATS or layout not in LAYOUTS:
        raise ValueError(f"format {fmt!r} / layout {layout!r}: expected one of {FORMATS} / {LAYOUTS}")
    if fmt != "h5ad" and layout != "sparse":
        raise ValueError(f"{fmt} is a sparse format: --layout dense needs --format h5ad")
    genes, cells = [str(g) for g in genes], [str(c) for c in cells]
    if fmt == "h5ad":
        X = (X.toarray() if sp.issparse(X) else np.asarray(X)) if layout == "dense" else sp.csr_matrix(X)
        a = ad.AnnData(X=X, obs=pd.DataFrame(index=pd.Index(cells, name="cell_id")),
                       var=pd.DataFrame(index=pd.Index(genes, name="gene_id")))
        a.write_h5ad(path)
        return
    X = sp.csr_matrix(X)  # cells x genes CSR = genes x cells CSC
    with h5py.File(path, "w") as h5:
        g = h5.create_group("matrix")
        for k in ("data", "indices", "indptr"):
            g.create_dataset(k, data=getattr(X, k))
        g.create_dataset("shape", data=np.array([X.shape[1], X.shape[0]]))
        g.create_dataset("barcodes", data=np.array(cells, dtype="S"))
        if fmt == "omni":
            g.create_dataset("genes", data=np.array(genes, dtype="S"))
        else:
            f = g.create_group("features")
            f.create_dataset("id", data=np.array(genes, dtype="S"))
            f.create_dataset("name", data=np.array(genes, dtype="S"))
            f.create_dataset("feature_type", data=np.array(["Gene Expression"] * len(genes), dtype="S"))
            f.create_dataset("genome", data=np.array(["unknown"] * len(genes), dtype="S"))
            f.create_dataset("_all_tag_keys", data=np.array(["genome"], dtype="S"))


def detect(path):
    """'omni', '10x' or 'h5ad', from the file's HDF5 layout."""
    with h5py.File(path, "r") as h5:
        if "matrix" in h5:
            return "10x" if "features" in h5["matrix"] else "omni"
        if "X" in h5 and "obs" in h5 and "var" in h5:
            return "h5ad"
    raise ValueError(f"{path}: neither omni, 10x nor h5ad")


def read_matrix(path, dense=False):
    """AnnData (cells x genes) from any of the formats; X as stored (sparse or dense) unless
    dense=True forces dense."""
    fmt = detect(path)
    if fmt == "h5ad":
        a = ad.read_h5ad(path)
    elif fmt == "10x":
        try:
            import scanpy as sc
            a = sc.read_10x_h5(path)
            a.var_names = a.var["gene_ids"].astype(str) if "gene_ids" in a.var else a.var_names
        except ImportError:
            a = _read_csc(path, "features/id")
    else:
        a = _read_csc(path, "genes")
    if dense and sp.issparse(a.X):
        a.X = a.X.toarray()
    return a


def _read_csc(path, gene_key):
    with h5py.File(path, "r") as h5:
        g = h5["matrix"]
        shape = tuple(g["shape"][:])
        X = sp.csc_matrix((g["data"][:], g["indices"][:], g["indptr"][:]), shape=shape).T.tocsr()
        genes, cells = g[gene_key][:].astype(str), g["barcodes"][:].astype(str)
    a = ad.AnnData(X=X)
    a.obs_names, a.var_names = cells, genes
    return a
