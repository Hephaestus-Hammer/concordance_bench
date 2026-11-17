#!/usr/bin/env python3
"""Float32 against float64 PCA: does the precision change the results beyond replicate noise?

Reads the replicate folders of two Phase 2 runs that differ only in the PCA precision
(scripts/run_phase2.sbatch with and without PRECISION=float32, same hardware) and compares
every result with its counterpart: the same modules, settings and seeds in the other precision.
Each comparison is set against the noise floor, the same comparison between same-seed replicates
of one precision (what rerunning alone changes):

  agreement   PCA: variance-weighted agreement of the embeddings (concordance.pca_agreement);
              kNN: shared neighbours per cell; Leiden: ARI and best-match Jaccard of the
              clusters. cross = float32 against float64 pairs; floor = replicate pairs within
              either precision. gap = floor median - cross median. Beyond noise: the cross
              median is below the floor's lower quartile by more than TOL.
  accuracy    ARI and Jaccard against the labels, and the number of clusters: median per
              precision, delta = float32 - float64, against the noise, the largest spread
              (max - min) of the per-folder medians within either precision. Beyond noise:
              |delta| > max(noise, TOL). Per resolution and at each precision's own oracle
              resolution (the best median ARI).
  cost        wall time, CPU time and peak memory (RAM + GPU) of every PCA, kNN and Leiden job:
              warm median per precision, ratio = float32 / float64, against the largest
              max/min ratio of the per-folder medians within either precision. Beyond noise:
              max(ratio, 1/ratio) > max(noise, COST_TOL).

TOL and COST_TOL are the deck's dominance tolerances (analysis/dominance.py): 0.01 on agreement
and accuracy, a factor 1.25 on cost.

    python analysis/precision.py --float64 out-phase2_float64_<hw>_rep* \\
        --float32 out-phase2_float32_<hw>_rep* --output_dir results/precision_<hw>

Outputs (precision_<name>.tsv), then report/precision.qmd rendered to precision.html:
  folders     folder, precision, replicate tag
  pairs       every pair: level (pca, knn, cluster), measure, dataset, subsample, group,
              resolution, kind (cross, floor float64, floor float32), value
  agreement   level x measure x dataset x size x group (x resolution): cross and floor
              quartiles, gap, beyond_noise
  accuracy    group x dataset x size x res_key: medians per precision, delta, noise,
              beyond_noise, for ARI, Jaccard and the number of clusters
  cost        stage x module x dataset x size: warm medians per precision, ratio, noise,
              beyond_noise, for wall time, CPU time and memory
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
import dominance as dm  # noqa: E402
import phase2 as p2  # noqa: E402
import resources as rs  # noqa: E402
from load import index_runs  # noqa: E402

PRECISIONS = ("float64", "float32")
TOL = dm.DELTA_S                    # 0.01: agreement and accuracy
COST_TOL = float(np.exp(dm.DELTA_C))  # 1.25: cost ratios
NAMED = {" > ".join(m): n for n, m in p2.PIPELINES.items()}


# ---- folders ---------------------------------------------------------------------------

def folder_tags(dirs):
    """The run tag load.index_runs gives each folder (its name, '+' appended on a clash)."""
    tags = []
    for d in dirs:
        tag = Path(d).resolve().name
        while tag in tags:
            tag += "+"
        tags.append(tag)
    return tags


def load(f64, f32):
    """(index of all folders, {run tag: precision}). Needs two folders at least."""
    dirs = [*f64, *f32]
    df = index_runs(dirs)
    prec = dict(zip(folder_tags(dirs), ["float64"] * len(f64) + ["float32"] * len(f32)))
    return df, prec


def _kind(a, b):
    """cross (other precision), floor <precision> (same precision, other folder) or None."""
    if a["run"] == b["run"]:
        return None
    return "cross" if a["precision"] != b["precision"] else f"floor {a['precision']}"


def group_name(pipeline):
    """A clustering's pipeline as it reads in the report: the named pipeline, else the modules."""
    return NAMED.get(pipeline, pipeline)


# ---- agreement -----------------------------------------------------------------------------

def _pair_rows(t, key, items, sims, level, group):
    """Every cross and floor pair within groups of identical modules, settings and seeds."""
    out = []
    for k, g in t.groupby(key, dropna=False):
        if g["run"].nunique() < 2:
            continue
        rows = list(g.iterrows())
        for (_, a), (_, b) in itertools.combinations(rows, 2):
            kind = _kind(a, b)
            if kind is None:
                continue
            x, y = items(a), items(b)
            base = {"level": level, "dataset": a["dataset"], "subsample": a["subsample"], "group": group(a),
                    "resolution": a.get("resolution", np.nan), "kind": kind}
            out += [{**base, "measure": m, "value": float(f(x, y))} for m, f in sims.items()]
    return out


def pca_pairs(df, prec):
    t = p2.stage_rows(df, "embedding_tsv", 2)
    load_ = p2.stage_rows(df, "loadings_tsv", 2)
    if not len(t) or not len(load_):
        return []
    t = t.merge(load_[["dir", "path"]].rename(columns={"path": "loadings"}), on="dir", how="left")
    t["precision"] = t["run"].map(prec)
    cache = {}

    def items(r):
        if r["dir"] not in cache:
            emb = cc.read_embedding(r["path"])
            cache[r["dir"]] = (cc.read_loadings(r["loadings"]), emb.var(axis=0, ddof=1).to_numpy())
        return cache[r["dir"]]

    def agree(x, y):
        return cc.pca_agreement(x[0].to_numpy(), x[1], y[0].reindex(x[0].index).to_numpy(), y[1])

    return _pair_rows(t, ["dataset", "subsample", "module", "seed"], items, {"pca_agreement": agree},
                      "pca", lambda r: r["module"])


def knn_pairs(df, prec):
    t = p2.stage_rows(df, "neighbors_h5", 3)
    if not len(t):
        return []
    t["precision"] = t["run"].map(prec)
    cache, order = {}, {}

    def items(r):
        if r["dir"] not in cache:
            g, cells = cc.read_neighbors(r["path"])
            key = (r["dataset"], r["subsample"])  # one cell order for every folder
            order.setdefault(key, cells)
            cache[r["dir"]] = cc.align_graph(g, cells, order[key])
        return cache[r["dir"]]

    def shared(x, y):
        return float(cc.knn_shared_fraction(x, y).mean())

    def group(r):
        return r["module"] if r["upstream"] == p2.BASELINE["pca"] else f'{r["upstream"]} > {r["module"]}'

    return _pair_rows(t, ["dataset", "subsample", "module", "seed", "upstream", "upstream_seeds"], items,
                      {"knn_shared": shared}, "knn", group)


def cluster_pairs(runs):
    cache, order = {}, {}

    def items(r):
        if r["path"] not in cache:
            lab = cc.read_clusters(r["path"])
            key = (r["dataset"], r["subsample"])
            order.setdefault(key, lab.index)
            cache[r["path"]] = cc.codes(lab.reindex(order[key]))
        return cache[r["path"]]

    key = ["dataset", "subsample", "pipeline", "resolution", "pca_seed", "knn_seed", "cluster_seed"]
    return _pair_rows(runs, key, items, {"ari": cc.ari, "jaccard": cc.jaccard}, "cluster",
                      lambda r: group_name(r["pipeline"]))


def _q(v, q):
    return float(np.quantile(v, q)) if len(v) else np.nan


def agreement(pairs, tol=TOL):
    """Cross against floor per level, measure, dataset, size, group and resolution."""
    if not len(pairs):
        return pd.DataFrame()
    key = ["level", "measure", "dataset", "subsample", "group", "resolution"]
    rows = []
    for k, g in pairs.groupby(key, dropna=False):
        cross = g.loc[g["kind"] == "cross", "value"].to_numpy()
        floor = g.loc[g["kind"].str.startswith("floor"), "value"].to_numpy()
        if not len(cross):
            continue
        row = dict(zip(key, k))
        row.update({"cross_pairs": len(cross), "cross_q25": _q(cross, 0.25), "cross_median": _q(cross, 0.5),
                    "cross_min": float(cross.min()), "floor_pairs": len(floor), "floor_q25": _q(floor, 0.25),
                    "floor_median": _q(floor, 0.5), "floor_min": float(floor.min()) if len(floor) else np.nan})
        for p in PRECISIONS:
            f = g.loc[g["kind"] == f"floor {p}", "value"].to_numpy()
            row[f"floor_{p}_median"] = _q(f, 0.5)
        row["gap"] = row["floor_median"] - row["cross_median"]
        row["beyond_noise"] = (bool(row["cross_median"] < row["floor_q25"] - tol) if len(floor) else np.nan)
        rows.append(row)
    return pd.DataFrame(rows)


# ---- accuracy --------------------------------------------------------------------------------

ACC = {"ari": "ari_truth", "jaccard": "jaccard_truth", "n_clusters": "clusters"}


def _medians(g, col):
    """(median over all runs, per-folder medians) of one precision's runs."""
    return float(g[col].median()), g.groupby("run")[col].median().to_numpy()


def _spread(per_folder):
    return float(per_folder.max() - per_folder.min()) if len(per_folder) > 1 else np.nan


def accuracy(runs, tol=TOL):
    """float32 - float64 per group, dataset, size and resolution, and at each precision's own
    oracle resolution, against the spread of per-folder medians within either precision."""
    rows = []
    for (d, s, pipe), g in runs.groupby(["dataset", "subsample", "pipeline"]):
        by = {p: g[g["precision"] == p] for p in PRECISIONS}
        if any(not len(x) for x in by.values()):
            continue
        oracle = {p: p2.oracle_resolution(x) for p, x in by.items()}
        choices = [(p2.ORACLE, oracle)] + [(p2.res_key(r), {p: r for p in PRECISIONS})
                                           for r in sorted(g["resolution"].dropna().unique())]
        for key, res in choices:
            at = {p: by[p][by[p]["resolution"] == res[p]] for p in PRECISIONS}
            if any(not len(x) for x in at.values()):
                continue
            row = {"dataset": d, "subsample": s, "group": group_name(pipe), "pipeline": pipe, "res_key": key,
                   "resolution_float64": res["float64"], "resolution_float32": res["float32"],
                   "runs_float64": len(at["float64"]), "runs_float32": len(at["float32"])}
            for m, col in ACC.items():
                (m64, f64), (m32, f32) = _medians(at["float64"], col), _medians(at["float32"], col)
                spreads = [x for x in (_spread(f64), _spread(f32)) if np.isfinite(x)]
                noise = max(spreads) if spreads else np.nan
                delta = m32 - m64
                row.update({f"{m}_float64": m64, f"{m}_float32": m32, f"{m}_delta": delta, f"{m}_noise": noise,
                            f"{m}_beyond_noise": (bool(abs(delta) > max(noise, tol if m != "n_clusters" else 0.5))
                                                  if np.isfinite(noise) else np.nan)})
            rows.append(row)
    return pd.DataFrame(rows)


# ---- cost -----------------------------------------------------------------------------------

COST = {"wall_s": "wall time (s)", "cpu_s": "CPU time (s)", "mem_gb": "peak memory (GB)"}


def job_rows(df, runs, prec):
    """Every PCA, kNN and Leiden job once: stage, module, dataset, size, folder, job dir."""
    parts = []
    for stage, out, idx in (("pca", "embedding_tsv", 2), ("knn", "neighbors_h5", 3)):
        t = p2.stage_rows(df, out, idx)
        if len(t):
            parts.append(t.assign(stage=stage)[["stage", "module", "dataset", "subsample", "run", "dir"]])
    c = runs.rename(columns={"cluster": "module", "cluster_dir": "dir"})
    parts.append(c.assign(stage="cluster")[["stage", "module", "dataset", "subsample", "run", "dir"]])
    t = pd.concat(parts, ignore_index=True).drop_duplicates("dir")
    t["precision"] = t["run"].map(prec)
    return t


def cost(jobs, rt, cold, cost_tol=COST_TOL):
    """Warm medians per precision and their ratio, per stage, module, dataset and size."""
    t = p2.add_cost(jobs, rt, cold)
    rows = []
    for (st, m, d, s), g in t.groupby(["stage", "module", "dataset", "subsample"]):
        by = {p: p2.warm(g[g["precision"] == p]) for p in PRECISIONS}
        if any(not len(x) for x in by.values()):
            continue
        row = {"stage": st, "module": m, "dataset": d, "subsample": s,
               "jobs_float64": len(by["float64"]), "jobs_float32": len(by["float32"])}
        for col in COST:
            med = {p: float(x[col].median()) for p, x in by.items()}
            spreads = []
            for x in by.values():
                f = x.groupby("run")[col].median().dropna()
                if len(f) > 1 and f.min() > 0:
                    spreads.append(float(f.max() / f.min()))
            noise = max(spreads) if spreads else np.nan
            ratio = med["float32"] / med["float64"] if med["float64"] > 0 else np.nan
            row.update({f"{col}_float64": med["float64"], f"{col}_float32": med["float32"], f"{col}_ratio": ratio,
                        f"{col}_noise": noise,
                        f"{col}_beyond_noise": (bool(max(ratio, 1 / ratio) > max(noise, cost_tol))
                                                if np.isfinite(noise) and np.isfinite(ratio) and ratio > 0 else np.nan)})
        rows.append(row)
    return pd.DataFrame(rows)


# ---- main ------------------------------------------------------------------------------------

def compare(f64, f32, tol=TOL, cost_tol=COST_TOL):
    """Every table, from the two precisions' folders."""
    df, prec = load(f64, f32)
    runs = p2.clustering_table(df)
    if not len(runs):
        raise SystemExit("no Phase 2 clusterings found (data > input > pca > knn > cluster)")
    runs["precision"] = runs["run"].map(prec)
    runs, _ = p2.accuracy(df, runs, with_bounds=False)
    pairs = pd.DataFrame(pca_pairs(df, prec) + knn_pairs(df, prec) + cluster_pairs(runs))
    rt = rs.runtimes(df)[0]
    cold = p2.cold_starts(rt)
    folders = pd.DataFrame({"folder": [Path(f).name for f in [*f64, *f32]], "tag": folder_tags([*f64, *f32]),
                            "precision": ["float64"] * len(f64) + ["float32"] * len(f32)})
    return {"folders": folders, "pairs": pairs, "agreement": agreement(pairs, tol),
            "accuracy": accuracy(runs, tol), "cost": cost(job_rows(df, runs, prec), rt, cold, cost_tol)}


def render_report(out):
    """Render report/precision.qmd from the TSVs in `out` to out/precision.html (needs quarto)."""
    out = out.resolve()
    qmd = Path(__file__).resolve().parent.parent / "report" / "precision.qmd"
    subprocess.run(["quarto", "render", str(qmd), "--output-dir", str(out)], check=True,
                   env={**os.environ, "PRECISION_RESULTS": str(out)})
    print(f"wrote {out / 'precision.html'}")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--float64", type=Path, nargs="+", required=True, help="the float64 replicate folders")
    p.add_argument("--float32", type=Path, nargs="+", required=True, help="the float32 replicate folders")
    p.add_argument("--output_dir", type=Path, default=Path("results/precision"))
    p.add_argument("--tol", type=float, default=TOL, help="agreement and accuracy tolerance (default 0.01)")
    p.add_argument("--cost_tol", type=float, default=COST_TOL, help="cost ratio tolerance (default 1.25)")
    p.add_argument("--no_report", action="store_true", help="write the TSVs only")
    args = p.parse_args()
    if len(args.float64) + len(args.float32) < 2:
        raise SystemExit("need at least one folder of each precision")

    tables = compare(args.float64, args.float32, args.tol, args.cost_tol)
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    for name, t in tables.items():
        t.to_csv(out / f"precision_{name}.tsv", sep="\t", index=False)
    a = tables["agreement"]
    flagged = int((a["beyond_noise"] == True).sum()) if len(a) else 0  # noqa: E712
    print(f"wrote {out}/precision_*.tsv: {len(tables['pairs'])} pairs, {len(a)} agreement rows "
          f"({flagged} beyond replicate noise), {len(tables['accuracy'])} accuracy rows, "
          f"{len(tables['cost'])} cost rows")
    if not args.no_report:
        render_report(out)


if __name__ == "__main__":
    main()
