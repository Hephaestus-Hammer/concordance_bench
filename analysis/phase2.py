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
  oracle resolution the resolution with the best median accuracy over seeds (never per seed).
                    Stage tabs read downstream accuracy at the *baseline pipeline's* oracle
                    resolution, so a worse PCA or kNN cannot be rescued by another resolution;
                    the Clustering tab and the named pipelines use their own.
  cost              wall time: of a stage's own job in the stage tabs; per answer for the named
                    pipelines (PCA and kNN once, Leiden at every resolution of the sweep). The
                    first rapids job of a module in a folder is a cold start: flagged, and left
                    out of medians where there are others.
  named pipelines   baseline, scanpy-defaults, tuned-cpu, all-gpu, hybrid (PIPELINES), with
                    matched seeds: seed i at every seeded stage

    python analysis/phase2.py --from_out out-phase2 [out-phase2-rep1 ...] --output_dir results/phase2

Outputs (phase2_<name>.tsv):
  bounds                    dataset x size: cells, labels, chance and oracle bounds
  runs                      every clustering: pipeline, resolution, seeds, folder, ARI, clusters
  jobs                      every job: wall time, memory, cores, GPU, start (resources.runtimes)
  pca, knn                  every PCA / kNN run of its slice: fidelity, wall time, cold start
  pca_pairs, knn_pairs      seed pairs (stability) and replicate pairs (reproducibility)
  stage_concordance         PCA and kNN: every pair of modules, per dataset and size, on the
                            stage's own measure, against each one's own seed floor (the
                            permutation test where both have several seeds)
  stability, reproducibility  final clusters: per pipeline and resolution (pairs, quartiles)
  stages                    stage x module x dataset x size: fidelity, stage stability and
                            reproducibility, downstream accuracy and stability, cost: the
                            stage tabs' summary
  answers                   every answer: wall time per stage and in total, cold start
  pipelines                 named pipeline x dataset x size at its oracle resolution: accuracy,
                            stability, reproducibility, cost, log10 cost against the fastest
  pipelines_runs            the named pipelines' runs at their oracle resolution (accuracy
                            distributions)
  concordance_*             report.py's concordance tables per dataset/size: PCA angles, kNN
                            overlap, ARI between runs, the Leiden tests against each module's
                            own seed noise, modularity (unless --no_concordance)
"""

import argparse
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import concordance as cc  # noqa: E402
import report  # noqa: E402
import resources as rs  # noqa: E402
import significance as sg  # noqa: E402
from load import REPLICATE_KEYS, index_runs  # noqa: E402

STAGES = ("pca", "knn", "cluster")
BASELINE = {"pca": "pc-baseline", "knn": "nn-baseline", "cluster": "cl-baseline"}
BASELINE_PIPELINE = " > ".join(BASELINE.values())
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


def _pairs(runs, key, same_folder):
    """Pairwise ARI within groups sharing `key`: seeds differ within one folder (stability),
    or identical seeds across folders (reproducibility)."""
    seeds = ["pca_seed", "knn_seed", "cluster_seed"]
    out = []
    for k, g in runs.groupby(key, dropna=False):
        if len(g) < 2:
            continue
        order = cc.read_clusters(g["path"].iloc[0]).index
        lab = {p: cc.codes(cc.read_clusters(p).reindex(order)) for p in g["path"]}
        aris = []
        for (_, a), (_, b) in itertools.combinations(g.iterrows(), 2):
            same_seeds = all(a[s] == b[s] for s in seeds)
            if same_folder and (a["run"] != b["run"] or same_seeds):
                continue
            if not same_folder and (a["run"] == b["run"] or not same_seeds):
                continue
            aris.append(cc.ari(lab[a["path"]], lab[b["path"]]))
        if aris:
            out.append({**dict(zip(key, k)), **_summarise(aris)})
    return pd.DataFrame(out, columns=[*key, *PAIR_COLS])


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


def stage_concordance(stage, t, items, sim, n_perm=9999):
    """Every pair of modules of one stage, per dataset and size: their agreement against each
    one's own seed floor, on the stage's own measure. The permutation test (significance.py)
    where both modules ran several seeds; the medians alone otherwise (an exact module has no
    seed noise: its floor is undefined, not 1)."""
    rows = []
    for (d, s), g in t.groupby(["dataset", "subsample"]):
        by = {m: gm for m, gm in g.groupby("module")}
        for a, b in itertools.combinations(sorted(by), 2):
            strata = []
            for run in sorted(set(by[a]["run"]) & set(by[b]["run"])):
                ra = [items(r) for _, r in by[a][by[a]["run"] == run].iterrows()]
                rb = [items(r) for _, r in by[b][by[b]["run"] == run].iterrows()]
                strata.append((ra, rb))
            if not strata:
                continue
            row = {"stage": stage, "dataset": d, "subsample": s, "A": a, "B": b,
                   "runs A": sum(len(x[0]) for x in strata), "runs B": sum(len(x[1]) for x in strata)}
            testable = [x for x in strata if len(x[0]) > 1 and len(x[1]) > 1]
            if testable:
                row.update(sg.own_floor_test(testable, n_perm=n_perm, sim=sim))
            else:
                # one side ran once (an exact module): no permutation test, but the seeded
                # side's own floor and its gap (floor - between, means) are still defined
                between = [sim(x, y) for ra, rb in strata for x in ra for y in rb]
                within = {}
                for side, idx in (("A", 0), ("B", 1)):
                    w = [sim(x, y) for st in strata for x, y in itertools.combinations(st[idx], 2)]
                    within[side] = w
                row.update({"upstreams": len(strata), "between median": float(np.median(between)),
                            "within A median": float(np.median(within["A"])) if within["A"] else np.nan,
                            "within B median": float(np.median(within["B"])) if within["B"] else np.nan,
                            "gap A": float(np.mean(within["A"]) - np.mean(between)) if within["A"] else np.nan,
                            "p A": np.nan,
                            "gap B": float(np.mean(within["B"]) - np.mean(between)) if within["B"] else np.nan,
                            "p B": np.nan})
            rows.append(row)
    return pd.DataFrame(rows)


def pca_concordance(pca, n_perm=9999):
    cache = {}

    def items(r):
        if r["dir"] not in cache:
            emb = cc.read_embedding(r["path"])
            cache[r["dir"]] = (cc.read_loadings(r["loadings"]), emb.var(axis=0, ddof=1).to_numpy())
        return cache[r["dir"]]

    def sim(x, y):
        return cc.pca_agreement(x[0].to_numpy(), x[1], y[0].reindex(x[0].index).to_numpy(), y[1])

    return stage_concordance("pca", pca, items, sim, n_perm) if len(pca) else pd.DataFrame()


def knn_concordance(knn, n_perm=9999):
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

    return stage_concordance("knn", knn, items, sim, n_perm) if len(knn) else pd.DataFrame()


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


def add_cost(t, rt, cold):
    wall = dict(zip(rt["dir"], rt["s"])) if len(rt) else {}
    t = t.copy()
    t["wall_s"] = [wall.get(d, np.nan) for d in t["dir"]]
    t["cold_start"] = [d in cold for d in t["dir"]]
    return t


def warm_median(x):
    w = x[~x["cold_start"]] if (~x["cold_start"]).any() else x
    return float(w["wall_s"].median()) if len(w) else np.nan


def answers(runs, rt, cold):
    """One row per answer: wall time of its PCA, kNN and every Leiden resolution, in total."""
    wall = dict(zip(rt["dir"], rt["s"])) if len(rt) else {}
    rss = dict(zip(rt["dir"], rt["max_rss"])) if len(rt) else {}
    key = ["dataset", "subsample", "pipeline", "pca_seed", "knn_seed", "cluster_seed", "run"]
    out = []
    for k, g in runs.groupby(key, dropna=False):
        dirs = [g["pca_dir"].iloc[0], g["knn_dir"].iloc[0], *g["cluster_dir"]]
        w = [wall.get(d, np.nan) for d in dirs]
        out.append({**dict(zip(key, k)), "resolutions": g["resolution"].nunique(),
                    "pca_s": w[0], "knn_s": w[1], "cluster_s": float(np.sum(w[2:])),
                    "wall_s": float(np.sum(w)) if np.isfinite(w).all() else np.nan,
                    "peak_rss_mb": np.nanmax([rss.get(d, np.nan) for d in dirs]) if rss else np.nan,
                    "cold_start": any(d in cold for d in dirs)})
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


def stages_summary(runs, bounds, pca, pca_pairs, knn, knn_pairs, rt, cold):
    """Stage x module x dataset x size: the stage tabs' numbers."""
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
        sliced[stage] = (sl, stability(sl), reproducibility(sl))
    rows = []
    for (d, s), g in runs.groupby(["dataset", "subsample"]):
        oracle = b.at[(d, s), "oracle"] if (d, s) in b.index else np.nan
        base = g[g["pipeline"] == BASELINE_PIPELINE]
        res_base = oracle_resolution(base) if len(base) else np.nan
        for stage in STAGES:
            sl_all, stab, repro = sliced[stage]
            sl = sl_all[(sl_all["dataset"] == d) & (sl_all["subsample"] == s)]
            col = stage
            for module, gm in sl.groupby(col):
                pipeline = gm["pipeline"].iloc[0]
                res = res_base if stage != "cluster" else oracle_resolution(gm)
                at = gm[gm["resolution"] == res]["ari_truth"]
                row = {"stage": stage, "module": module, "dataset": d, "subsample": s,
                       "cells": b.at[(d, s), "cells"] if (d, s) in b.index else np.nan,
                       "resolution": res, "resolution_rule": "baseline oracle" if stage != "cluster" else "own oracle",
                       "accuracy_ari": float(at.median()) if len(at) else np.nan,
                       "accuracy_share": _share(float(at.median()), oracle) if len(at) else np.nan,
                       "downstream_stability": _pick(stab, dataset=d, subsample=s, pipeline=pipeline, resolution=res),
                       "downstream_reproducibility": _pick(repro, dataset=d, subsample=s, pipeline=pipeline, resolution=res)}
                if stage in ("pca", "knn"):
                    st, pairs = (pca, pca_pairs) if stage == "pca" else (knn, knn_pairs)
                    r = st[(st["dataset"] == d) & (st["subsample"] == s) & (st["module"] == module)] if len(st) else st
                    p = pairs[(pairs["dataset"] == d) & (pairs["subsample"] == s) & (pairs["module"] == module)] if len(pairs) else pairs
                    row.update({"fidelity": float(r["fidelity"].median()) if len(r) else np.nan,
                                "stage_stability": float(p[p["kind"] == "stability"]["value"].median()) if len(p) else np.nan,
                                "stage_reproducibility": float(p[p["kind"] == "reproducibility"]["value"].median()) if len(p) else np.nan,
                                "cost_s": warm_median(r) if len(r) else np.nan})
                else:
                    jobs = add_cost(gm.rename(columns={"cluster_dir": "dir"})[["dir"]], rt, cold)
                    row.update({"fidelity": np.nan, "stage_stability": row["downstream_stability"],
                                "stage_reproducibility": row["downstream_reproducibility"],
                                "cost_s": warm_median(jobs)})  # one Leiden run
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


def pipelines_summary(named, bounds, stab, repro, ans):
    """Named pipeline x dataset x size, at its own oracle resolution."""
    b = bounds.set_index(["dataset", "subsample"]) if len(bounds) else pd.DataFrame()
    rows, at_oracle = [], []
    for (d, s, name), g in named.groupby(["dataset", "subsample", "named"]):
        res = oracle_resolution(g)
        at = g[g["resolution"] == res]
        oracle = b.at[(d, s), "oracle"] if (d, s) in b.index else np.nan
        pipeline = g["pipeline"].iloc[0]
        keys = set(zip(g["pca_seed"], g["knn_seed"], g["cluster_seed"], g["run"]))
        a = ans[(ans["dataset"] == d) & (ans["subsample"] == s) & (ans["pipeline"] == pipeline)]
        a = a[[k in keys for k in zip(a["pca_seed"], a["knn_seed"], a["cluster_seed"], a["run"])]]
        rows.append({"dataset": d, "subsample": s,
                     "cells": b.at[(d, s), "cells"] if (d, s) in b.index else np.nan,
                     "pipeline": name, "modules": pipeline, "oracle_resolution": res, "runs": len(at),
                     "accuracy_ari": float(at["ari_truth"].median()),
                     "accuracy_q10": float(at["ari_truth"].quantile(0.1)), "accuracy_q90": float(at["ari_truth"].quantile(0.9)),
                     "accuracy_share": _share(float(at["ari_truth"].median()), oracle),
                     "stability": _pick(stab, dataset=d, subsample=s, pipeline=pipeline, resolution=res),
                     "reproducibility": _pick(repro, dataset=d, subsample=s, pipeline=pipeline, resolution=res),
                     "cost_s": warm_median(a) if len(a) else np.nan,
                     "cost_cold_answers": int(a["cold_start"].sum()) if len(a) else 0})
        at_oracle.append(at.assign(accuracy_share=[_share(x, oracle) for x in at["ari_truth"]]))
    p = pd.DataFrame(rows)
    if len(p):
        p["log10_cost_vs_fastest"] = np.log10(p["cost_s"] / p.groupby(["dataset", "subsample"])["cost_s"].transform("min"))
    pr = pd.concat(at_oracle) if at_oracle else pd.DataFrame()
    return p, pr


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--from_out", type=Path, nargs="+", required=True)
    p.add_argument("--output_dir", type=Path, default=Path("results/phase2"))
    p.add_argument("--n_perm", type=int, default=9999, help="permutations per concordance test")
    p.add_argument("--no_concordance", action="store_true",
                   help="skip the concordance tables (report.compute per dataset and size), the slow part")
    args = p.parse_args()

    df = index_runs(args.from_out)
    df["size"] = [f"{n[0].module}/{n[1].module}" if len(n) > 1 else n[0].module for n in df["nodes"]]
    runs = clustering_table(df)
    if not len(runs):
        raise SystemExit("no Phase 2 clusterings found (data > input > pca > knn > cluster)")
    runs, bounds = accuracy(df, runs)
    stab, repro = stability(runs), reproducibility(runs)
    rt = rs.runtimes(df)[0]
    cold = cold_starts(rt)
    pca, pca_pairs = pca_stage(df)
    knn, knn_pairs = knn_stage(df)
    pca = add_cost(pca, rt, cold) if len(pca) else pca
    knn = add_cost(knn, rt, cold) if len(knn) else knn
    stage_conc = pd.concat([pca_concordance(pca, args.n_perm), knn_concordance(knn, args.n_perm)],
                           ignore_index=True)
    ans = answers(runs, rt, cold)
    stages = stages_summary(runs, bounds, pca, pca_pairs, knn, knn_pairs, rt, cold)
    named = named_pipeline_runs(runs)
    pipes, pipe_runs = pipelines_summary(named, bounds, stab, repro, ans)

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    drop = ["path", "pca_dir", "knn_dir", "cluster_dir", "loadings", "dir"]
    tables = {"bounds": bounds, "runs": runs, "jobs": rt, "pca": pca, "pca_pairs": pca_pairs, "knn": knn,
              "knn_pairs": knn_pairs, "stability": stab, "reproducibility": repro, "stages": stages,
              "answers": ans, "pipelines": pipes, "pipelines_runs": pipe_runs,
              "stage_concordance": stage_conc}
    for name, t in tables.items():
        t.drop(columns=[c for c in drop if c in t.columns and name != "jobs"]).to_csv(
            out / f"phase2_{name}.tsv", sep="\t", index=False)
    if not args.no_concordance:
        # Phase 1's concordance tables with "size" = dataset/subsample (report.py's definitions).
        tabs, _ = report.compute(df, n_perm=args.n_perm)
        for k, t in tabs.items():
            if isinstance(t, pd.DataFrame) and len(t):
                t.to_csv(out / f"phase2_concordance_{k}.tsv", sep="\t", index=False)
    print(f"wrote {out}/phase2_*.tsv: {len(runs)} clusterings, {len(stages)} stage rows, "
          f"{len(pipes)} named-pipeline rows")


if __name__ == "__main__":
    main()
