"""Fake Phase 2 ob output tree with known effects, for tests/test_phase2.py.

Datasets dsA, dsB with 8 well-separated groups in 20 "genes"; sizes in-small and in-all. Every
lineage of the three stage slices and of the named pipelines (seeds 0-3), laid out as ob does,
each job with a Snakemake benchmark file of known wall time. Effects built in:

  PCA      pc-baseline is the exact PCA (10 components); pc-randomized replaces its last
           component (0.? % of the variance) by a seed-dependent direction, so its fidelity is
           1 - that component's share; pc-rapids is exact up to 1e-9 noise.
  kNN      nn-baseline and nn-rapids exact; nn-scanpy and nn-scanpy-mt replace 3% of neighbours,
           seed-dependent (nn-scanpy-mt also differs across folders: not reproducible).
  Leiden   resolution sets granularity (0.5 merges pairs, 1 matches the groups, 2 splits them);
           a seed moves 5% of cells; cl-rapids also merges two groups and is not reproducible
           across folders. Upstream noise from an approximate kNN moves 2% more cells.
"""

import hashlib
import json
import zlib
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.neighbors import NearestNeighbors

SEEDS = range(4)
RES = (0.5, 1.0, 2.0)
SECS = {"input": 2, "pc-baseline": 10, "pc-randomized": 3, "pc-rapids": 1, "nn-baseline": 8,
        "nn-scanpy": 4, "nn-scanpy-mt": 1.5, "nn-rapids": 0.5, "cl-baseline": 2, "cl-rapids": 0.5}
BENCH = ("s\th:m:s\tmax_rss\tmax_vms\tmax_uss\tmax_pss\tio_in\tio_out\tmean_load\tcpu_time\n"
         "{s:.2f}\t0:00:01\t{m:.1f}\t1\t1\t1\t0\t0\t0\t{s:.2f}\n")


def _node(parent, stage, module, params):
    h = hashlib.md5(json.dumps(params, sort_keys=True).encode()).hexdigest()[:8]
    d = parent / stage / module / f".{h}"
    if not d.exists():
        d.mkdir(parents=True)
        (d / "parameters.json").write_text(json.dumps(params))
        s = SECS[module if module in SECS else stage]
        (d / "performance.txt").write_text(BENCH.format(s=s, m=100 + s))
        _denet(d, s, 100 + s, 512 if "rapids" in module else None)
    return d


_CLOCK = [1_000_000.0]


def _denet(d, s, rss_mb, gpu_mb):
    """A minimal denet trace: start, two samples (RAM rises to its peak), exit after s seconds."""
    t0 = _CLOCK[0]
    _CLOCK[0] += 1000 * s + 10
    gpu = (lambda mb: {"process_data": [{"gpu_utilization": 50, "memory_usage": int(mb * 1024 ** 2)}]}) if gpu_mb else None
    lines = [{"kind": "metadata", "t0_ms": t0, "pid": 1, "cmd": "python3 x.py"}]
    for frac, mem in ((0.0, rss_mb / 2), (0.5, rss_mb), (1.0, rss_mb / 2)):
        smp = {"kind": "sample", "ts_ms": t0 + 1000 * s * frac, "cpu_usage": 100.0, "mem_rss_kb": int(mem * 1024),
               "thread_count": 1}
        if gpu_mb:
            smp["gpu"] = gpu(gpu_mb * (0.5 + frac / 2))
        lines.append(smp)
    lines.append({"kind": "exit", "ts_ms": t0 + 1000 * s})
    (d / "denet.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))


def _tsv(path, index, col_values, index_name):
    pd.DataFrame(col_values, index=pd.Index(index, name=index_name)).to_csv(path, sep="\t")


def _knn_h5(path, cells, emb, noise_seed=None):
    n = len(cells)
    dist, idx = NearestNeighbors(n_neighbors=15).fit(emb).kneighbors(emb)
    if noise_seed is not None:
        r = np.random.default_rng(noise_seed)
        m = r.random(idx.shape) < 0.03
        m[:, 0] = False
        idx[m] = r.integers(0, n, m.sum())
    rows = np.repeat(np.arange(n), 15)
    D = sp.csr_matrix((dist.ravel() + 1e-6, (rows, idx.ravel())), shape=(n, n))
    D.setdiag(0)
    D.eliminate_zeros()
    C = sp.csr_matrix((np.ones(rows.size), (rows, idx.ravel())), shape=(n, n))
    C.setdiag(0)
    C.eliminate_zeros()
    C = ((C + C.T) > 0).astype(float).tocsr()
    with h5py.File(path, "w") as h5:
        h5.create_dataset("cell_ids", data=np.array(cells, dtype="S"))
        for g, m in ((h5, D), (h5.create_group("connectivities"), C)):
            for k in ("data", "indices", "indptr"):
                g.create_dataset(k, data=getattr(m, k))


def _clusters(lab, res, seed, merged, extra_noise):
    r = np.random.default_rng(seed)
    c = lab.copy()
    if res < 1:
        c = c // 2
    if res > 1:
        c = c * 2 + (r.random(len(c)) < 0.5)
    if merged:
        c[c == 1] = 0
    k = r.random(len(c)) < 0.05 + extra_noise
    c[k] = r.choice(np.unique(c), k.sum())
    return c


def exact_pca(X, k=10):
    xc = X - X.mean(0)
    u, s, vt = np.linalg.svd(xc, full_matrices=False)
    signs = np.sign(vt[np.arange(k), np.argmax(np.abs(vt[:k]), axis=1)])
    v = (vt[:k] * signs[:, None]).T
    return xc @ v, v


def build(root, rep=0, n_a=600, n_b=400, small=300):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "Snakefile").write_text("")
    genes = [f"g{i}" for i in range(20)]
    for ds, n in (("dsA", n_a), ("dsB", n_b)):
        rng = np.random.default_rng(zlib.crc32(ds.encode()))
        lab_all = rng.integers(0, 8, n)
        centres = rng.normal(0, 2.5, (8, 20))
        X_all = centres[lab_all] + rng.normal(0, 1, (n, 20))
        d0 = root / "data" / ds / ".d0"
        d0.mkdir(parents=True, exist_ok=True)
        (d0 / "parameters.json").write_text("{}")
        for sub, m in (("in-small", small), ("in-all", n)):
            cells = [f"c{i}" for i in range(m)]
            lab, X = lab_all[:m], X_all[:m]
            inp = _node(d0, "input", sub, {"n_cells": m if sub != "in-all" else 0, "replicate": 0})
            _tsv(inp / f"{sub}.clusters_truth.tsv", cells, {"truths": lab}, "cell_id")
            emb_exact, v_exact = exact_pca(X)

            def pca(module, seed):
                d = _node(inp, "pca", module, {"random_seed": seed})
                if module == "pc-randomized":   # last component replaced, seed-dependent
                    r = np.random.default_rng(300 + seed)
                    v = v_exact.copy()
                    q, _ = np.linalg.qr(np.c_[v_exact, r.normal(size=20)])
                    v[:, -1] = q[:, -1]
                elif module == "pc-rapids":
                    v = v_exact + np.random.default_rng(5).normal(0, 1e-9, v_exact.shape)
                else:
                    v = v_exact
                emb = (X - X.mean(0)) @ v
                _tsv(d / f"{module}_embedding.tsv", cells, emb, "cell_id")
                _tsv(d / f"{module}_loadings.tsv", genes, v, "gene_id")
                return d, emb

            def knn(pdir, emb, module, seed):
                d = _node(pdir, "knn", module, {"random_seed": seed})
                noise = None if module in ("nn-baseline", "nn-rapids") else (
                    100 + seed + (1000 * rep if module == "nn-scanpy-mt" else 0))
                if not (d / f"{module}_neighbors.h5").exists():
                    _knn_h5(d / f"{module}_neighbors.h5", cells, emb, noise)
                return d, module in ("nn-scanpy", "nn-scanpy-mt")

            def leiden(kdir, approx_knn, module, seed, salt):
                for res in RES:
                    d = _node(kdir, "cluster", module, {"random_seed": seed, "resolution": res})
                    s = seed + salt + (1000 * rep if module == "cl-rapids" else 0)
                    _tsv(d / f"{module}_clusters.tsv", cells,
                         {"cluster": _clusters(lab, res, s, module == "cl-rapids", 0.02 if approx_knn else 0)},
                         "cell_id")

            pb, eb = pca("pc-baseline", 0)
            kb, _ = knn(pb, eb, "nn-baseline", 0)
            for s in SEEDS:  # clustering slice (and the baseline pipeline)
                leiden(kb, False, "cl-baseline", s, 0)
                leiden(kb, False, "cl-rapids", s, 0)
            kr, _ = knn(pb, eb, "nn-rapids", 0)  # kNN slice
            leiden(kr, False, "cl-baseline", 0, 0)
            for s in SEEDS:
                ks, a = knn(pb, eb, "nn-scanpy", s)
                leiden(ks, a, "cl-baseline", 0, 11 * s)
            for s in SEEDS:  # PCA slice
                pr, er = pca("pc-randomized", s)
                k2, _ = knn(pr, er, "nn-baseline", 0)
                leiden(k2, False, "cl-baseline", 0, 7 * s)
            pg, eg = pca("pc-rapids", 0)
            k3, _ = knn(pg, eg, "nn-baseline", 0)
            leiden(k3, False, "cl-baseline", 0, 0)
            # named pipelines: tuned-cpu, all-gpu, hybrid (matched seeds)
            kg, _ = knn(pg, eg, "nn-rapids", 0)
            for s in SEEDS:
                pr, er = pca("pc-randomized", s)
                kt, a = knn(pr, er, "nn-scanpy-mt", s)
                leiden(kt, a, "cl-baseline", s, 13 * s)
                leiden(kg, False, "cl-rapids", s, 0)
                leiden(kg, False, "cl-baseline", s, 0)
    return root
