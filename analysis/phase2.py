#!/usr/bin/env python3
"""Phase 2 tables, per stage and per named pipeline, per dataset and subsample size.

Reads one or several ob output trees of benchmark-phase2.yaml (several = same-seed replicates,
as in report.py) and writes TSVs only; report/phase2.qmd reads them. Definitions are
docs/phase2-plan.md's; in short:

  stage tabs        PCA, kNN, Clustering, each read from its slice: the other stages at the
                    exact baselines, so every difference belongs to that stage
  stability         agreement between runs whose seeds differ, within one output folder
  reproducibility   agreement between runs with identical parameters in different folders
  PCA agreement     variance-weighted: the share of one run's top-50 variance the other's
                    subspace holds (concordance.pca_fidelity); fidelity = against the exact
                    solver (pc-baseline); between seeds, averaged over both directions
  kNN agreement     shared neighbours per cell; fidelity = recall of the exact (nn-baseline)
                    neighbours
  accuracy          ARI of the final clusters against the reference labels, also as a share of
                    the range between chance (0) and the oracle bound (the better of logistic
                    regression and 15-NN, cross-validated on the exact embedding)
  resolution        every summary is given at every resolution of the sweep (res_key "0.5",
                    ...) and at the oracle resolution (res_key "oracle"): the resolution with
                    the best median accuracy over seeds (never per seed). At "oracle", stage
                    tabs read downstream results at the *baseline pipeline's* oracle
                    resolution, so a worse PCA or kNN cannot be rescued by another resolution;
                    the Clustering tab and the named pipelines use their own.
  cost              wall time: of a stage's own job in the stage tabs; per answer for the named
                    pipelines: at a fixed resolution PCA + kNN + one Leiden run, at "oracle" PCA
                    + kNN + Leiden at every resolution of the sweep (choosing the best needs them
                    all). The first rapids job of a module in a folder is a cold start: flagged,
                    and left out of medians where there are others.
  concordance       between two implementations: the median agreement between their runs
                    against each one's own seed floor (median agreement between its own runs);
                    gap = floor - between. No significance tests.
  named pipelines   baseline, scanpy-defaults, tuned-cpu, all-gpu, hybrid (PIPELINES), with
                    matched seeds: seed i at every seeded stage

    python analysis/phase2.py --from_out out-phase2 [out-phase2-rep1 ...] --output_dir results/phase2

Outputs (phase2_<name>.tsv):
  bounds                    dataset x size: cells, labels, chance and oracle bounds
  runs                      every clustering: pipeline, resolution, seeds, folder, ARI, clusters
  jobs                      every job: wall time, memory, cores, GPU, start (resources.runtimes)
  pca, knn                  every PCA / kNN run of its slice: fidelity, wall time, cold start
  pca_pairs, knn_pairs      seed pairs (stability) and replicate pairs (reproducibility)
  stage_concordance         every pair of modules of a stage, per dataset and size, on the
                            stage's own measure (Leiden: ARI, per resolution), against each
                            one's own seed floor
  stability, reproducibility  final clusters: per pipeline and resolution (pairs, quartiles)
  stages                    stage x module x dataset x size x res_key: fidelity, stage
                            stability and reproducibility, downstream accuracy and stability,
                            cost: the stage tabs' summary
  answers                   every answer: wall time per stage and in total, cold start; per
                            resolution (scope "single") and for the whole sweep (scope "sweep")
  pipelines                 named pipeline x dataset x size x res_key: accuracy, stability,
                            reproducibility, cost, log10 cost against the fastest
  pipelines_runs            the named pipelines' runs per res_key (accuracy distributions)
  obs                       every individual observation behind the medians, for box plots:
                            tab, metric, group (module, pipeline or "A vs B"), dataset,
                            subsample, cells, res_key ("*" where the resolution does not
                            matter), value, cold_start
memory: a job's peak RAM (denet's peak RSS of the process tree) plus its peak GPU memory, in GB;
an answer's peak is the largest of its jobs' (the stages run one after another).
"""

import argparse
import itertools
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import concordance as cc  # noqa: E402
import resources as rs  # noqa: E402
from load import REPLICATE_KEYS, index_runs  # noqa: E402

STAGES = ("pca", "knn", "cluster")
BASELINE = {"pca": "pc-baseline", "knn": "nn-baseline", "cluster": "cl-baseline"}
BASELINE_PIPELINE = " > ".join(BASELINE.values())
ORACLE = "oracle"  # res_key of the oracle-resolution rows; the others are f"{resolution:g}"
PIPELINES = {  # keep in step with scripts/make_filters.py
    "baseline":        ("pc-baseline", "nn-baseline", "cl-baseline"),
    "scanpy-defaults": ("pc-scanpy", "nn-scanpy", "cl-scanpy"),
    "tuned-cpu":       ("pc-randomized", "nn-scanpy-mt", "cl-baseline"),
    "all-gpu":         ("pc-rapids", "nn-rapids", "cl-rapids"),
    "hybrid":          ("pc-rapids", "nn-rapids", "cl-baseline"),
}


# ---- identity ------------------------------------------------------------------------

def _seed(node):
    """A node's seed (random_seed/seed), ignoring replicate tags; '' if it has none."""
    return ",".join(f"{v}" for k, v in node.seeds if k not in REPLICATE_KEYS)


def _run_tag(nodes):
    """The output folder a lineage came from (load.index_runs' "run" seed), '' for one folder."""
    return next((str(v) for k, v in nodes[1].params if k == "run"), "") if len(nodes) > 1 else ""


def _node_dir(path, depth_from_file=0):
    """The node directory of an output file, or of its ancestor depth_from_file stages up."""
    d = Path(path).parent
    for _ in range(depth_from_file):
        d = d.parents[2]
    return str(d)


def stage_rows(df, output, stage_index):
    """One row per output of a stage (pca: 2, knn: 3), with its lineage identity."""
    rows = []
    for _, r in df[df["output"] == output].iterrows():
        nodes = r["nodes"]
        if len(nodes) != stage_index + 1:
            continue
        mods = [n.module for n in nodes[2:]]
        rows.append({"dataset": nodes[0].module, "subsample": nodes[1].module, "run": _run_tag(nodes),
                     "module": nodes[-1].module, "seed": _seed(nodes[-1]),
                     "upstream": " > ".join(mods[:-1]), "upstream_seeds": ",".join(_seed(n) for n in nodes[2:-1]),
                     "path": r["path"], "dir": _node_dir(r["path"]), "nodes": nodes})
    return pd.DataFrame(rows)


def clustering_table(df):
    """One row per clustering with its pipeline, resolution, seeds, folder and job directories."""
    rows = []
    for _, r in df[df["output"] == "clusters_tsv"].iterrows():
        nodes = r["nodes"]
        if len(nodes) < 5:
            continue
        data, inp, pca, knn, clu = nodes[:5]
        mods = (pca.module, knn.module, clu.module)
        rows.append({
            "dataset": data.module, "subsample": inp.module, "pca": pca.module, "knn": knn.module,
            "cluster": clu.module, "pipeline": " > ".join(mods),
            "resolution": float(dict(clu.settings).get("resolution", np.nan)),
            "pca_seed": _seed(pca), "knn_seed": _seed(knn), "cluster_seed": _seed(clu),
            "run": _run_tag(nodes), "label": r["label"], "path": r["path"],
            "pca_dir": _node_dir(r["path"], 2), "knn_dir": _node_dir(r["path"], 1), "cluster_dir": _node_dir(r["path"]),
            "varies": ",".join(s for s, m in zip(STAGES, mods) if m != BASELINE[s]) or "none",
        })
    return pd.DataFrame(rows)


# ---- accuracy and bounds ------------------------------------------------------------------

def oracle_bounds(embedding, labels, folds=5, seed=0):
    """(ARI of cross-validated logistic regression, of 15-NN) predicting labels from an embedding."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    y = np.asarray(labels)
    k = int(min(folds, pd.Series(y).value_counts().min()))  # rare classes: fewer folds
    if k < 2:
        return np.nan, np.nan
    cv = StratifiedKFold(n_splits=k, shuffle=True, random_state=seed)
    out = []
    for clf in (make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)),
                KNeighborsClassifier(n_neighbors=15)):
        pred = cross_val_predict(clf, embedding, y, cv=cv)
        out.append(cc.ari(cc.codes(pd.Series(y)), cc.codes(pd.Series(pred))))
    return tuple(out)


def accuracy(df, runs):
    """Adds ari_truth and clusters to runs; returns (runs, bounds)."""
    runs = runs.copy()
    runs["ari_truth"], runs["clusters"] = np.nan, np.nan
    bounds = []
    truth_rows = df[df["output"] == "rawdata_clusters_truth"]
    emb_rows = df[df["output"] == "embedding_tsv"]
    for (dataset, subsample, run), idx in runs.groupby(["dataset", "subsample", "run"]).groups.items():
        # each folder's own truth file (replicate folders hold identical ones)
        t = truth_rows[[n[0].module == dataset and len(n) > 1 and n[1].module == subsample and _run_tag(n) == run
                        for n in truth_rows["nodes"]]]
        if not len(t):
            continue
        truth = cc.read_truth(t["path"].iloc[0])["truths"]
        order, tc = truth.index, cc.codes(truth)
        for i in idx:
            lab = cc.read_clusters(runs.at[i, "path"]).reindex(order)
            if lab.isna().any():
                raise ValueError(f"cells missing from {runs.at[i, 'path']} relative to the truth file")
            codes = cc.codes(lab)
            runs.at[i, "ari_truth"] = cc.ari(tc, codes)
            runs.at[i, "clusters"] = codes.max() + 1
        if any(b["dataset"] == dataset and b["subsample"] == subsample for b in bounds):
            continue  # one bound per dataset and size, from the first folder
        e = emb_rows[[n[0].module == dataset and n[1].module == subsample and n[-1].module == BASELINE["pca"]
                      for n in emb_rows["nodes"]]]
        e = e if len(e) else emb_rows[[n[0].module == dataset and n[1].module == subsample for n in emb_rows["nodes"]]]
        lr, knn = (oracle_bounds(cc.read_embedding(e["path"].iloc[0]).reindex(order).to_numpy(), truth.to_numpy())
                   if len(e) else (np.nan, np.nan))
        bounds.append({"dataset": dataset, "subsample": subsample, "cells": len(truth),
                       "labels": truth.nunique(), "chance": 0.0, "oracle_logreg": lr, "oracle_knn": knn,
                       "oracle": float(np.nanmax([lr, knn])) if np.isfinite([lr, knn]).any() else np.nan})
    return runs, pd.DataFrame(bounds)


def oracle_resolution(g):
    """The resolution with the best median ARI over seeds (ties: the first, lowest)."""
    med = g.groupby("resolution")["ari_truth"].median().dropna()
    return float(med.sort_values(ascending=False, kind="stable").index[0]) if len(med) else np.nan


# ---- stability and reproducibility of the final clusters ------------------------------------

PAIR_COLS = ["pairs", "q25", "median", "q75", "min"]


def _summarise(values):
    q = np.quantile(values, [0.25, 0.5, 0.75])
    return dict(zip(PAIR_COLS, (len(values), q[0], q[1], q[2], float(np.min(values)))))


def pair_obs(runs, key, same_folder):
    """Every pairwise ARI within groups sharing `key`: seeds differ within one folder
    (stability), or identical seeds across folders (reproducibility). One row per pair."""
    seeds = ["pca_seed", "knn_seed", "cluster_seed"]
    out = []
    for k, g in runs.groupby(key, dropna=False):
        if len(g) < 2:
            continue
        order = cc.read_clusters(g["path"].iloc[0]).index
        lab = {p: cc.codes(cc.read_clusters(p).reindex(order)) for p in g["path"]}
        for (_, a), (_, b) in itertools.combinations(g.iterrows(), 2):
            same_seeds = all(a[s] == b[s] for s in seeds)
            if same_folder and (a["run"] != b["run"] or same_seeds):
                continue
            if not same_folder and (a["run"] == b["run"] or not same_seeds):
                continue
            out.append({**dict(zip(key, k)), "value": cc.ari(lab[a["path"]], lab[b["path"]])})
    return pd.DataFrame(out, columns=[*key, "value"])


def summarise_pairs(obs, key):
    rows = [{**dict(zip(key, k)), **_summarise(g["value"].to_numpy())} for k, g in obs.groupby(key, dropna=False)]
    return pd.DataFrame(rows, columns=[*key, *PAIR_COLS])


def _pairs(runs, key, same_folder):
    return summarise_pairs(pair_obs(runs, key, same_folder), key)


KEY = ["dataset", "subsample", "pipeline", "resolution"]


def stability(runs):
    return _pairs(runs, KEY, same_folder=True)


def reproducibility(runs):
    return _pairs(runs, KEY, same_folder=False)


# ---- PCA and kNN stages ---------------------------------------------------------------

def pca_stage(df):
    """Per PCA run of the PCA slice: fidelity to the exact solver in its folder; seed and
    replicate pairs of the variance-weighted agreement."""
    t = stage_rows(df, "embedding_tsv", 2)
    load = stage_rows(df, "loadings_tsv", 2)
    if not len(t) or not len(load):
        return t.drop(columns=["nodes"], errors="ignore"), pd.DataFrame()
    t = t.merge(load[["dir", "path"]].rename(columns={"path": "loadings"}), on="dir", how="left")
    cache = {}

    def get(r):
        if r["dir"] not in cache:
            emb = cc.read_embedding(r["path"])
            cache[r["dir"]] = (cc.read_loadings(r["loadings"]), emb.var(axis=0, ddof=1).to_numpy())
        return cache[r["dir"]]

    t["fidelity"] = np.nan
    for (d, s, run), g in t.groupby(["dataset", "subsample", "run"]):
        ex = g[g["module"] == BASELINE["pca"]]
        if not len(ex):
            continue
        v_ex, var_ex = get(ex.iloc[0])
        for i, r in g.iterrows():
            v, _ = get(r)
            t.at[i, "fidelity"] = cc.pca_fidelity(v_ex.to_numpy(), var_ex, v.reindex(v_ex.index).to_numpy())
    pairs = []
    for (d, s, m), g in t.groupby(["dataset", "subsample", "module"]):
        for (_, a), (_, b) in itertools.combinations(g.iterrows(), 2):
            kind = ("stability" if a["run"] == b["run"] and a["seed"] != b["seed"] else
                    "reproducibility" if a["run"] != b["run"] and a["seed"] == b["seed"] else None)
            if kind:
                (va, la), (vb, lb) = get(a), get(b)
                pairs.append({"dataset": d, "subsample": s, "module": m, "kind": kind,
                              "value": cc.pca_agreement(va.to_numpy(), la, vb.reindex(va.index).to_numpy(), lb)})
    return t.drop(columns=["nodes"]), pd.DataFrame(pairs, columns=["dataset", "subsample", "module", "kind", "value"])


def knn_stage(df):
    """Per kNN run on the exact embedding (the kNN slice): recall of the exact neighbours in its
    folder; seed and replicate pairs of the shared-neighbour fraction."""
    t = stage_rows(df, "neighbors_h5", 3)
    if not len(t):
        return t, pd.DataFrame()
    t = t[t["upstream"] == BASELINE["pca"]].copy()
    near, order = {}, {}

    def get(r):
        key = (r["dataset"], r["subsample"], r["run"])
        if r["dir"] not in near:
            g, cells = cc.read_neighbors(r["path"])
            order.setdefault(key, cells)
            g = cc.align_graph(g, cells, order[key])
            near[r["dir"]] = (g, cc.neighbours_per_cell(g))
        return near[r["dir"]]

    t["fidelity"] = np.nan
    for (d, s, run), g in t.groupby(["dataset", "subsample", "run"]):
        ex = g[g["module"] == BASELINE["knn"]]
        if not len(ex):
            continue
        g_ex, _ = get(ex.iloc[0])
        for i, r in g.iterrows():
            t.at[i, "fidelity"] = float(cc.knn_shared_fraction(g_ex, get(r)[0]).mean())
    pairs = []
    for (d, s, m), g in t.groupby(["dataset", "subsample", "module"]):
        for (_, a), (_, b) in itertools.combinations(g.iterrows(), 2):
            kind = ("stability" if a["run"] == b["run"] and a["seed"] != b["seed"] else
                    "reproducibility" if a["run"] != b["run"] and a["seed"] == b["seed"] else None)
            if kind:
                ga, gb = get(a)[0], get(b)[0]
                if a["run"] != b["run"]:  # other folder: align to one cell order
                    gb = cc.align_graph(gb, order[(d, s, b["run"])], order[(d, s, a["run"])])
                pairs.append({"dataset": d, "subsample": s, "module": m, "kind": kind,
                              "value": float(cc.knn_shared_fraction(ga, gb).mean())})
    return t.drop(columns=["nodes"]), pd.DataFrame(pairs, columns=["dataset", "subsample", "module", "kind", "value"])


def res_key(r):
    return ORACLE if isinstance(r, str) else f"{float(r):g}"


def stage_concordance(stage, t, items, sim, by=("dataset", "subsample")):
    """Every pair of modules of one stage, per group (dataset and size; Leiden also resolution):
    the median agreement between their runs against each one's own seed floor, the median
    agreement between its own runs (undefined, not 1, for a module that ran once). Runs are
    compared within one output folder and upstream only."""
    rows = []
    for k, g in t.groupby(list(by)):
        mods = {m: gm for m, gm in g.groupby("module")}
        for a, b in itertools.combinations(sorted(mods), 2):
            strata = []
            for key in sorted(set(zip(mods[a]["run"], mods[a]["upstream"])) & set(zip(mods[b]["run"], mods[b]["upstream"]))):
                ra = [items(r) for _, r in mods[a][(mods[a]["run"] == key[0]) & (mods[a]["upstream"] == key[1])].iterrows()]
                rb = [items(r) for _, r in mods[b][(mods[b]["run"] == key[0]) & (mods[b]["upstream"] == key[1])].iterrows()]
                strata.append((ra, rb))
            if not strata:
                continue
            between = [sim(x, y) for ra, rb in strata for x in ra for y in rb]
            within = {side: [sim(x, y) for st in strata for x, y in itertools.combinations(st[i], 2)]
                      for side, i in (("A", 0), ("B", 1))}
            med = {side: float(np.median(w)) if w else np.nan for side, w in within.items()}
            bmed = float(np.median(between))
            rows.append({"stage": stage, **dict(zip(by, k)), "A": a, "B": b,
                         "runs A": sum(len(x[0]) for x in strata), "runs B": sum(len(x[1]) for x in strata),
                         "within A median": med["A"], "within B median": med["B"], "between median": bmed,
                         "gap A": med["A"] - bmed, "gap B": med["B"] - bmed,
                         "_between": between, "_within A": within["A"], "_within B": within["B"]})
    return pd.DataFrame(rows)


def pca_concordance(pca):
    cache = {}

    def items(r):
        if r["dir"] not in cache:
            emb = cc.read_embedding(r["path"])
            cache[r["dir"]] = (cc.read_loadings(r["loadings"]), emb.var(axis=0, ddof=1).to_numpy())
        return cache[r["dir"]]

    def sim(x, y):
        return cc.pca_agreement(x[0].to_numpy(), x[1], y[0].reindex(x[0].index).to_numpy(), y[1])

    return stage_concordance("pca", pca, items, sim) if len(pca) else pd.DataFrame()


def knn_concordance(knn):
    cache, order = {}, {}

    def items(r):
        if r["dir"] not in cache:
            g, cells = cc.read_neighbors(r["path"])
            key = (r["dataset"], r["subsample"], r["run"])
            order.setdefault(key, cells)
            cache[r["dir"]] = cc.align_graph(g, cells, order[key])
        return cache[r["dir"]]

    def sim(x, y):
        return float(cc.knn_shared_fraction(x, y).mean())

    return stage_concordance("knn", knn, items, sim) if len(knn) else pd.DataFrame()


def cluster_slice(runs):
    """The Clustering slice: exact PCA and kNN (the baselines) at seed 0, every Leiden."""
    sl = runs[runs["varies"].isin(["none", "cluster"])]
    return sl[sl["pca_seed"].isin(["0", ""]) & sl["knn_seed"].isin(["0", ""])]


def cluster_concordance(runs):
    """Leiden implementations on the Clustering slice: ARI between them at equal resolutions,
    against each one's seed floor; per resolution, and at res_key "oracle" the rows at the
    baseline Leiden's oracle resolution."""
    sl = cluster_slice(runs)
    if not len(sl):
        return pd.DataFrame()
    t = sl.assign(module=sl["cluster"], upstream=sl["pca"] + " > " + sl["knn"], dir=sl["cluster_dir"])
    cache = {}

    def items(r):
        if r["path"] not in cache:
            cache[r["path"]] = cc.read_clusters(r["path"])
        return cache[r["path"]]

    def sim(x, y):
        return cc.ari(cc.codes(x), cc.codes(y.reindex(x.index)))

    c = stage_concordance("cluster", t, items, sim, by=("dataset", "subsample", "resolution"))
    if not len(c):
        return c
    c["res_key"] = c["resolution"].map(res_key)
    orc = []
    for (d, s), g in t.groupby(["dataset", "subsample"]):
        base = g[g["cluster"] == BASELINE["cluster"]]
        r = oracle_resolution(base) if len(base) else np.nan
        orc.append(c[(c["dataset"] == d) & (c["subsample"] == s) & (c["resolution"] == r)].assign(res_key=ORACLE))
    return pd.concat([c, *orc], ignore_index=True)


# ---- cost ------------------------------------------------------------------------------

def output_folder(node_dir):
    """The ob output tree a node dir belongs to: everything above its top-level data/ stage dir."""
    parts = Path(node_dir).parts
    return str(Path(*parts[: parts.index("data")])) if "data" in parts else ""


def cold_starts(rt):
    """Job dirs of cold starts: per output folder, the first-started job of each rapids module."""
    if not len(rt) or rt["t0_ms"].isna().all():
        return set()
    gpu = rt.dropna(subset=["t0_ms"])
    gpu = gpu[gpu["module"].str.contains("rapids")].copy()
    if not len(gpu):
        return set()
    gpu["folder"] = gpu["dir"].map(output_folder)
    return set(gpu.loc[gpu.groupby(["folder", "module"])["t0_ms"].idxmin(), "dir"])


def job_memory_gb(rt):
    """Per job dir: peak RAM + peak GPU memory (GB)."""
    if not len(rt):
        return {}
    gpu = rt["gpu_mem_peak_mb"] if "gpu_mem_peak_mb" in rt.columns else 0.0
    mem = (pd.to_numeric(rt["max_rss"], errors="coerce") + pd.to_numeric(gpu, errors="coerce").fillna(0)) / 1024
    return dict(zip(rt["dir"], mem))


def add_cost(t, rt, cold):
    wall = dict(zip(rt["dir"], rt["s"])) if len(rt) else {}
    mem = job_memory_gb(rt)
    t = t.copy()
    t["wall_s"] = [wall.get(d, np.nan) for d in t["dir"]]
    t["mem_gb"] = [mem.get(d, np.nan) for d in t["dir"]]
    t["cold_start"] = [d in cold for d in t["dir"]]
    return t


def warm(x):
    """Leave cold starts out where there are others."""
    return x[~x["cold_start"]] if (~x["cold_start"]).any() else x


def warm_median(x, col="wall_s"):
    w = warm(x)
    return float(w[col].median()) if len(w) else np.nan


def answers(runs, rt, cold):
    """One row per answer and resolution (scope "single": PCA + kNN + one Leiden run) and per
    answer for the whole sweep (scope "sweep": PCA + kNN + Leiden at every resolution)."""
    wall = dict(zip(rt["dir"], rt["s"])) if len(rt) else {}
    mem = job_memory_gb(rt)
    key = ["dataset", "subsample", "pipeline", "pca_seed", "knn_seed", "cluster_seed", "run"]
    out = []

    def row(k, scope, res, cdirs, g):
        dirs = [g["pca_dir"].iloc[0], g["knn_dir"].iloc[0], *cdirs]
        w = [wall.get(d, np.nan) for d in dirs]
        return {**dict(zip(key, k)), "scope": scope, "resolution": res, "resolutions": len(cdirs),
                "pca_s": w[0], "knn_s": w[1], "cluster_s": float(np.sum(w[2:])),
                "wall_s": float(np.sum(w)) if np.isfinite(w).all() else np.nan,
                "mem_gb": float(np.nanmax(m)) if np.isfinite(m := [mem.get(d, np.nan) for d in dirs]).any() else np.nan,
                "cold_start": any(d in cold for d in dirs)}

    for k, g in runs.groupby(key, dropna=False):
        out.append(row(k, "sweep", np.nan, list(g["cluster_dir"]), g))
        for res, gr in g.groupby("resolution"):
            out.append(row(k, "single", res, list(gr["cluster_dir"]), g))
    return pd.DataFrame(out)


# ---- summaries -------------------------------------------------------------------------

def _pick(t, **where):
    if not len(t):
        return np.nan
    m = t
    for k, v in where.items():
        m = m[m[k] == v]
    return float(m["median"].iloc[0]) if len(m) else np.nan


def _share(ari, oracle):
    return (ari - 0.0) / oracle if np.isfinite(oracle) and oracle > 0 else np.nan


def stages_summary(runs, bounds, pca, pca_pairs, knn, knn_pairs, rt, cold, obs=None):
    """Stage x module x dataset x size x res_key: the stage tabs' numbers. `obs`, a list, gets
    the individual observations behind them."""
    obs = [] if obs is None else obs

    def ob(tab, metric, group, d, s, cells, key, values, cold_flags=None):
        cold_flags = [False] * len(values) if cold_flags is None else list(cold_flags)
        obs.extend({"tab": tab, "metric": metric, "group": group, "dataset": d, "subsample": s,
                    "cells": cells, "res_key": key, "value": float(v), "cold_start": bool(c)}
                   for v, c in zip(values, cold_flags) if np.isfinite(v))
    b = bounds.set_index(["dataset", "subsample"]) if len(bounds) else pd.DataFrame()
    # A stage tab lets only that stage's seed vary: the other stages at the baseline modules
    # and at seed 0, so downstream accuracy and stability measure that stage alone, for the
    # exact baseline row as for the variants.
    other_seeds = {"pca": ("knn_seed", "cluster_seed"), "knn": ("pca_seed", "cluster_seed"),
                   "cluster": ("pca_seed", "knn_seed")}
    sliced = {}
    for stage in STAGES:
        sl = runs[runs["varies"].isin(["none", stage])]
        for c in other_seeds[stage]:
            sl = sl[sl[c].isin(["0", ""])]
        so, ro = pair_obs(sl, KEY, True), pair_obs(sl, KEY, False)
        sliced[stage] = (sl, summarise_pairs(so, KEY), summarise_pairs(ro, KEY), so, ro)
    grid = sorted(runs["resolution"].dropna().unique())
    rows = []
    for (d, s), g in runs.groupby(["dataset", "subsample"]):
        oracle = b.at[(d, s), "oracle"] if (d, s) in b.index else np.nan
        base = g[g["pipeline"] == BASELINE_PIPELINE]
        res_base = oracle_resolution(base) if len(base) else np.nan
        for stage in STAGES:
            sl_all, stab, repro, so, ro = sliced[stage]
            cells = b.at[(d, s), "cells"] if (d, s) in b.index else np.nan
            sl = sl_all[(sl_all["dataset"] == d) & (sl_all["subsample"] == s)]
            for module, gm in sl.groupby(stage):
                pipeline = gm["pipeline"].iloc[0]
                own = {"fidelity": np.nan, "stage_stability": np.nan, "stage_reproducibility": np.nan,
                       "cost_s": np.nan, "mem_gb": np.nan}
                if stage in ("pca", "knn"):
                    st, pairs = (pca, pca_pairs) if stage == "pca" else (knn, knn_pairs)
                    r = st[(st["dataset"] == d) & (st["subsample"] == s) & (st["module"] == module)] if len(st) else st
                    p = pairs[(pairs["dataset"] == d) & (pairs["subsample"] == s) & (pairs["module"] == module)] if len(pairs) else pairs
                    own = {"fidelity": float(r["fidelity"].median()) if len(r) else np.nan,
                           "stage_stability": float(p[p["kind"] == "stability"]["value"].median()) if len(p) else np.nan,
                           "stage_reproducibility": float(p[p["kind"] == "reproducibility"]["value"].median()) if len(p) else np.nan,
                           "cost_s": warm_median(r) if len(r) else np.nan,
                           "mem_gb": warm_median(r, "mem_gb") if len(r) else np.nan}
                    if len(r):
                        ob(stage, "fidelity", module, d, s, cells, "*", r["fidelity"])
                        w = warm(r)
                        ob(stage, "cost_s", module, d, s, cells, "*", w["wall_s"], w["cold_start"])
                        ob(stage, "mem_gb", module, d, s, cells, "*", w["mem_gb"], w["cold_start"])
                    if len(p):
                        ob(stage, "stage_stability", module, d, s, cells, "*", p.loc[p["kind"] == "stability", "value"])
                        ob(stage, "stage_reproducibility", module, d, s, cells, "*", p.loc[p["kind"] == "reproducibility", "value"])
                choices = [(ORACLE, res_base if stage != "cluster" else oracle_resolution(gm),
                            "baseline oracle" if stage != "cluster" else "own oracle")]
                choices += [(res_key(x), x, "fixed") for x in grid]
                for key, res, rule in choices:
                    at = gm[gm["resolution"] == res]
                    row = {"stage": stage, "module": module, "dataset": d, "subsample": s,
                           "cells": b.at[(d, s), "cells"] if (d, s) in b.index else np.nan,
                           "res_key": key, "resolution": res, "resolution_rule": rule,
                           "accuracy_ari": float(at["ari_truth"].median()) if len(at) else np.nan,
                           "accuracy_share": _share(float(at["ari_truth"].median()), oracle) if len(at) else np.nan,
                           "downstream_stability": _pick(stab, dataset=d, subsample=s, pipeline=pipeline, resolution=res),
                           "downstream_reproducibility": _pick(repro, dataset=d, subsample=s, pipeline=pipeline, resolution=res),
                           **own}
                    ds = so[(so["dataset"] == d) & (so["subsample"] == s) & (so["pipeline"] == pipeline) & (so["resolution"] == res)]
                    dr = ro[(ro["dataset"] == d) & (ro["subsample"] == s) & (ro["pipeline"] == pipeline) & (ro["resolution"] == res)]
                    ob(stage, "accuracy_share", module, d, s, cells, key, [_share(x, oracle) for x in at["ari_truth"]])
                    ob(stage, "downstream_stability", module, d, s, cells, key, ds["value"])
                    ob(stage, "downstream_reproducibility", module, d, s, cells, key, dr["value"])
                    if stage == "cluster":
                        jobs = add_cost(at.rename(columns={"cluster_dir": "dir"})[["dir"]], rt, cold)
                        row.update({"stage_stability": row["downstream_stability"],
                                    "stage_reproducibility": row["downstream_reproducibility"],
                                    "cost_s": warm_median(jobs) if len(jobs) else np.nan,  # one Leiden run
                                    "mem_gb": warm_median(jobs, "mem_gb") if len(jobs) else np.nan})
                        if len(jobs):
                            w = warm(jobs)
                            ob(stage, "cost_s", module, d, s, cells, key, w["wall_s"], w["cold_start"])
                            ob(stage, "mem_gb", module, d, s, cells, key, w["mem_gb"], w["cold_start"])
                    rows.append(row)
    return pd.DataFrame(rows)


def named_pipeline_runs(runs):
    """The named pipelines' runs with matched seeds (seed i at every seeded stage), tagged."""
    seeded = {m for col, scol in (("pca", "pca_seed"), ("knn", "knn_seed"), ("cluster", "cluster_seed"))
              for m, g in runs.groupby(col) if g[scol].nunique() > 1}
    out = []
    for name, mods in PIPELINES.items():
        g = runs[(runs["pca"] == mods[0]) & (runs["knn"] == mods[1]) & (runs["cluster"] == mods[2])]
        for i, r in g.iterrows():
            s = {r[sc] for m, sc in zip(mods, ("pca_seed", "knn_seed", "cluster_seed")) if m in seeded}
            if len(s) <= 1:
                out.append((i, name))
    t = runs.loc[[i for i, _ in out]].copy()
    t["named"] = [n for _, n in out]
    return t


def pipelines_summary(named, bounds, stab, repro, ans, stab_obs=None, repro_obs=None, obs=None):
    """Named pipeline x dataset x size x res_key. At a fixed resolution the cost of an answer is
    PCA + kNN + one Leiden run; at "oracle" the whole sweep, since choosing needs every run."""
    b = bounds.set_index(["dataset", "subsample"]) if len(bounds) else pd.DataFrame()
    grid = sorted(named["resolution"].dropna().unique()) if len(named) else []
    rows, at_res = [], []
    for (d, s, name), g in named.groupby(["dataset", "subsample", "named"]):
        oracle = b.at[(d, s), "oracle"] if (d, s) in b.index else np.nan
        pipeline = g["pipeline"].iloc[0]
        keys = set(zip(g["pca_seed"], g["knn_seed"], g["cluster_seed"], g["run"]))
        a = ans[(ans["dataset"] == d) & (ans["subsample"] == s) & (ans["pipeline"] == pipeline)]
        a = a[[k in keys for k in zip(a["pca_seed"], a["knn_seed"], a["cluster_seed"], a["run"])]]
        choices = [(ORACLE, oracle_resolution(g))] + [(res_key(x), x) for x in grid]
        for key, res in choices:
            at = g[g["resolution"] == res]
            if not len(at):
                continue
            c = a[a["scope"] == "sweep"] if key == ORACLE else a[(a["scope"] == "single") & (a["resolution"] == res)]
            if obs is not None:
                cells = b.at[(d, s), "cells"] if (d, s) in b.index else np.nan
                base = {"tab": "pipeline", "group": name, "dataset": d, "subsample": s, "cells": cells, "res_key": key}
                obs.extend({**base, "metric": "accuracy_share", "value": _share(x, oracle), "cold_start": False}
                           for x in at["ari_truth"])
                for metric, po in (("stability", stab_obs), ("reproducibility", repro_obs)):
                    if po is not None and len(po):
                        v = po[(po["dataset"] == d) & (po["subsample"] == s) & (po["pipeline"] == pipeline)
                               & (po["resolution"] == res)]["value"]
                        obs.extend({**base, "metric": metric, "value": float(x), "cold_start": False} for x in v)
                w = warm(c) if len(c) else c
                for metric, col in (("cost_s", "wall_s"), ("mem_gb", "mem_gb")):
                    obs.extend({**base, "metric": metric, "value": float(x), "cold_start": bool(cs)}
                               for x, cs in zip(w[col], w["cold_start"]) if np.isfinite(x))
            rows.append({"dataset": d, "subsample": s,
                         "cells": b.at[(d, s), "cells"] if (d, s) in b.index else np.nan,
                         "pipeline": name, "modules": pipeline, "res_key": key, "resolution": res,
                         "runs": len(at), "accuracy_ari": float(at["ari_truth"].median()),
                         "accuracy_q10": float(at["ari_truth"].quantile(0.1)),
                         "accuracy_q90": float(at["ari_truth"].quantile(0.9)),
                         "accuracy_share": _share(float(at["ari_truth"].median()), oracle),
                         "stability": _pick(stab, dataset=d, subsample=s, pipeline=pipeline, resolution=res),
                         "reproducibility": _pick(repro, dataset=d, subsample=s, pipeline=pipeline, resolution=res),
                         "cost_s": warm_median(c) if len(c) else np.nan,
                         "mem_gb": warm_median(c, "mem_gb") if len(c) else np.nan,
                         "cost_cold_answers": int(c["cold_start"].sum()) if len(c) else 0})
            at_res.append(at.assign(res_key=key, accuracy_share=[_share(x, oracle) for x in at["ari_truth"]]))
    p = pd.DataFrame(rows)
    if len(p):
        p["log10_cost_vs_fastest"] = np.log10(
            p["cost_s"] / p.groupby(["dataset", "subsample", "res_key"])["cost_s"].transform("min"))
    pr = pd.concat(at_res) if at_res else pd.DataFrame()
    return p, pr


def concordance_obs(conc, bounds):
    """The individual agreements behind the concordance medians: "between" per pair of
    implementations, "within" (each one's own seed floor) per implementation."""
    if not len(conc):
        return pd.DataFrame()
    cells = {(r["dataset"], r["subsample"]): r["cells"] for _, r in bounds.iterrows()}
    out = []
    for _, r in conc.iterrows():
        key = r["res_key"] if "res_key" in r and isinstance(r["res_key"], str) else "*"
        base = {"tab": r["stage"], "dataset": r["dataset"], "subsample": r["subsample"],
                "cells": cells.get((r["dataset"], r["subsample"]), np.nan), "res_key": key, "cold_start": False}
        out += [{**base, "metric": "between", "group": f'{r["A"]} vs {r["B"]}', "value": v} for v in r["_between"]]
        out += [{**base, "metric": "within", "group": f'{r["A"]} vs {r["B"]}|{r[side]}', "value": v}
                for side, col in (("A", "_within A"), ("B", "_within B")) for v in r[col]]
    return pd.DataFrame(out)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--from_out", type=Path, nargs="+", required=True)
    p.add_argument("--output_dir", type=Path, default=Path("results/phase2"))
    p.add_argument("--no_report", action="store_true",
                   help="write the TSVs only; skip rendering report/phase2.qmd to HTML")
    args = p.parse_args()

    df = index_runs(args.from_out)
    runs = clustering_table(df)
    if not len(runs):
        raise SystemExit("no Phase 2 clusterings found (data > input > pca > knn > cluster)")
    runs, bounds = accuracy(df, runs)
    stab_obs, repro_obs = pair_obs(runs, KEY, True), pair_obs(runs, KEY, False)
    stab, repro = summarise_pairs(stab_obs, KEY), summarise_pairs(repro_obs, KEY)
    rt = rs.runtimes(df)[0]
    cold = cold_starts(rt)
    pca, pca_pairs = pca_stage(df)
    knn, knn_pairs = knn_stage(df)
    pca = add_cost(pca, rt, cold) if len(pca) else pca
    knn = add_cost(knn, rt, cold) if len(knn) else knn
    stage_conc = pd.concat([pca_concordance(pca), knn_concordance(knn), cluster_concordance(runs)],
                           ignore_index=True)
    ans = answers(runs, rt, cold)
    obs = []
    stages = stages_summary(runs, bounds, pca, pca_pairs, knn, knn_pairs, rt, cold, obs)
    named = named_pipeline_runs(runs)
    pipes, pipe_runs = pipelines_summary(named, bounds, stab, repro, ans, stab_obs, repro_obs, obs)
    obs = pd.concat([pd.DataFrame(obs), concordance_obs(stage_conc, bounds)], ignore_index=True)
    stage_conc = stage_conc.drop(columns=[c for c in stage_conc.columns if c.startswith("_")])

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    drop = ["path", "pca_dir", "knn_dir", "cluster_dir", "loadings", "dir"]
    tables = {"bounds": bounds, "runs": runs, "jobs": rt, "pca": pca, "pca_pairs": pca_pairs, "knn": knn,
              "knn_pairs": knn_pairs, "stability": stab, "reproducibility": repro, "stages": stages,
              "answers": ans, "pipelines": pipes, "pipelines_runs": pipe_runs,
              "stage_concordance": stage_conc, "obs": obs}
    for name, t in tables.items():
        t.drop(columns=[c for c in drop if c in t.columns and name != "jobs"]).to_csv(
            out / f"phase2_{name}.tsv", sep="\t", index=False)
    print(f"wrote {out}/phase2_*.tsv: {len(runs)} clusterings, {len(stages)} stage rows, "
          f"{len(pipes)} named-pipeline rows")
    if not args.no_report:
        render_report(out)


def render_report(out):
    """Render report/phase2.qmd from the TSVs in `out` to out/phase2.html (needs quarto)."""
    out = out.resolve()
    qmd = Path(__file__).resolve().parent.parent / "report" / "phase2.qmd"
    subprocess.run(["quarto", "render", str(qmd), "--output-dir", str(out)], check=True,
                   env={**os.environ, "PHASE2_RESULTS": str(out)})
    print(f"wrote {out / 'phase2.html'}")


if __name__ == "__main__":
    main()
