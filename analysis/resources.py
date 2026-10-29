"""Runtime, cores and memory per job: from denet traces where they exist, else from ob's benchmark file.

denet: the `stage` entrypoint (modules/stage.sh) runs each module script under
`denet --json run` and writes <output_dir>/denet.jsonl next to the outputs: a `metadata` line (t0_ms), one
`tree` line per sample (every ~0.1-1 s; `aggregated` = the module and its child
processes: cpu_usage in % with 100 = one busy core, mem_rss_kb, thread_count, and a
`gpu` block when run with --gpu), and an `exit` line. From it: wall time, CPU time
(integral of cpu_usage), mean and peak cores used, peak memory, peak threads, GPU
utilisation and GPU memory of the process, and the CPU series over time.

Fallback, for jobs without a trace: the `performance.txt` (Snakemake benchmark) ob
writes next to every job: s = wall time, max_rss = peak memory (MB), cpu_time.
Snakemake samples every 0.5 s for 15 s and then every 30 s and loses what happens
after the last sample, so for longer jobs cpu_time and max_rss are lower bounds.
No GPU there.

Both measure the whole module call: Python start-up, imports, reading inputs, the
computation and writing outputs. Every job is a fresh process, so one-off costs such
as numba compiling pynndescent (~13 s at 10k cells in sc-brrr) are in every kNN job.
"""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

# output id -> the stage whose node writes it
STAGE_OF_OUTPUT = {"embedding_tsv": "pca", "neighbors_h5": "knn", "clusters_tsv": "cluster",
                   "rawdata_clusters_truth": "input"}
FIELDS = ["s", "max_rss", "cpu_time", "peak_cores", "max_threads", "gpu_util_mean", "gpu_util_max",
          "gpu_mem_peak_mb", "source"]


def read_performance(path):
    """One job's Snakemake benchmark record, or None if the file is missing or empty."""
    path = Path(path)
    if not path.exists():
        return None
    t = pd.read_csv(path, sep="\t")
    if not len(t):
        return None
    row = t.iloc[0]
    rec = {k: pd.to_numeric(row.get(k), errors="coerce") for k in ("s", "max_rss", "cpu_time")}
    return {**rec, "source": "snakemake"}


def _gpu(record, aggregated):
    """(utilisation %, memory in bytes) from one sample's GPU block, or (nan, nan).

    denet 0.10.3's traces carry it under parent.gpu.system_metrics (device-wide memory,
    as sc-brrr's runner reads it); its docs show aggregated.gpu.devices, with the
    process's own memory where NVML reports it. Both are read; the process's own memory
    is preferred, else the device's (which counts anything else on the GPU too).
    """
    for g in ((record.get("parent") or {}).get("gpu"), (aggregated or {}).get("gpu")):
        if not g:
            continue
        devs = g.get("system_metrics") or g.get("devices") or []
        util = g.get("max_gpu_utilization")
        if util is None:
            us = [d.get("utilization_gpu", d.get("gpu_utilization")) for d in devs]
            us = [u for u in us if u is not None]
            util = max(us) if us else None
        own = [d["process_memory_usage"] for d in devs if d.get("process_memory_usage") is not None]
        mem = sum(own) if own else g.get("total_memory_used")
        if mem is None and devs:
            mem = sum(d.get("memory_used") or 0 for d in devs)
        return (math.nan if util is None else util), (math.nan if mem is None else mem)
    return math.nan, math.nan


def read_denet(path):
    """(summary dict, series DataFrame) for one denet trace, or (None, None) if unusable."""
    path = Path(path)
    if not path.exists():
        return None, None
    t0 = end = None
    rows = []
    with open(path) as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:  # last line of a job killed mid-write
                continue
            kind = r.get("kind")
            if kind == "metadata":
                t0 = r.get("t0_ms")
            elif kind in ("tree", "sample"):
                a = r.get("aggregated") if kind == "tree" else r
                if not a:
                    continue
                gpu_util, gpu_mem = _gpu(r, a)
                rows.append({"ts": r.get("ts_ms") or a.get("ts_ms"), "cpu": a.get("cpu_usage") or 0.0,
                             "rss_kb": a.get("mem_rss_kb") or 0, "threads": a.get("thread_count") or 0,
                             "gpu_util": gpu_util, "gpu_mem": gpu_mem})
            elif kind == "exit":
                end = r.get("ts_ms")
    if not rows:
        return None, None
    d = pd.DataFrame(rows)
    t0 = t0 if t0 is not None else d["ts"].iloc[0]
    end = end if end is not None else d["ts"].iloc[-1]
    d["t"] = (d["ts"] - t0) / 1000.0
    d["cores"] = d["cpu"] / 100.0
    dt = np.diff(np.concatenate([[0.0], d["t"].to_numpy()]))  # cpu_usage covers the interval before each sample
    wall = max((end - t0) / 1000.0, float(d["t"].iloc[-1]), 1e-9)
    gpu_util = pd.to_numeric(d["gpu_util"], errors="coerce")
    gpu_mem = pd.to_numeric(d["gpu_mem"], errors="coerce")
    summary = {"s": wall, "max_rss": d["rss_kb"].max() / 1024.0, "cpu_time": float((d["cores"] * dt).sum()),
               "peak_cores": float(d["cores"].max()), "max_threads": int(d["threads"].max()),
               "gpu_util_mean": float(gpu_util.mean()) if gpu_util.notna().any() else np.nan,
               "gpu_util_max": float(gpu_util.max()) if gpu_util.notna().any() else np.nan,
               "gpu_mem_peak_mb": float(gpu_mem.max()) / 2**20 if gpu_mem.notna().any() else np.nan,
               "source": "denet"}
    return summary, d[["t", "cores", "rss_kb", "threads", "gpu_util"]]


def runtimes(df):
    """(one row per job, {pipeline label: CPU series}) for every job (node) in df.

    df is load.index(...); each output's directory is its node's directory. A job's
    denet trace is used when present, else its Snakemake benchmark record.
    """
    rows, series, seen = [], {}, set()
    for _, r in df.iterrows():
        node_dir = Path(r["path"]).parent
        if node_dir in seen:
            continue
        seen.add(node_dir)
        rec, ser = read_denet(node_dir / "denet.jsonl")
        if rec is None:
            rec = read_performance(node_dir / "performance.txt")
        if rec is None:
            continue
        node = r["nodes"][-1]
        stage = STAGE_OF_OUTPUT.get(r["output"], node.stage)
        rows.append({"size": r["size"], "stage": stage, "module": node.module,
                     "settings": ", ".join(f"{k}={v}" for k, v in node.settings),
                     "seed": ", ".join(f"{k}={v}" for k, v in node.seeds),
                     "pipeline": r["label"], **{k: rec.get(k, np.nan) for k in FIELDS}})
        if ser is not None:
            series[(r["size"], stage, r["label"])] = ser
    cols = ["size", "stage", "module", "settings", "seed", "pipeline", *FIELDS]
    return pd.DataFrame(rows, columns=cols), series


def allocated_cores(plan):
    """{stage id: cores} from the stages' `resources: {cores: N}` in benchmark.yaml (1 if unset)."""
    if plan is None or not Path(plan).exists():
        return {}
    p = yaml.safe_load(Path(plan).read_text())
    return {s["id"]: int((s.get("resources") or {}).get("cores", 1)) for s in p.get("stages", [])}


def add_cores(rt, allocated):
    """Cores used = CPU time / wall time: the average number of busy cores over the whole job."""
    rt = rt.copy()
    rt["cores used"] = rt["cpu_time"] / rt["s"]
    rt["cores allocated"] = rt["stage"].map(allocated)
    return rt


def summarise(rt):
    """Per size, stage and module: runs, wall time, memory, cores used vs allocated, GPU."""
    if not len(rt):
        return rt
    agg = {"runs": ("s", "count"), "measured by": ("source", lambda x: ", ".join(sorted(set(x)))),
           "wall time (s) median": ("s", "median"), "wall time (s) min": ("s", "min"),
           "wall time (s) max": ("s", "max"), "peak memory (MB) median": ("max_rss", "median"),
           "mean cores used median": ("cores used", "median"),
           "peak cores used median": ("peak_cores", "median"),
           "threads (max)": ("max_threads", "max"), "cores allocated": ("cores allocated", "first")}
    if rt["gpu_util_mean"].notna().any():
        agg.update({"GPU utilisation % (mean) median": ("gpu_util_mean", "median"),
                    "GPU memory (MB, peak) median": ("gpu_mem_peak_mb", "median")})
    out = rt.groupby(["size", "stage", "module"]).agg(**agg).reset_index()
    return out.dropna(axis=1, how="all")
