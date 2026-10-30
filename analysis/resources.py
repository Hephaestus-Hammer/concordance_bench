"""Runtime, cores and memory per job, and per phase where the module logs phases.

denet: the `stage` entrypoint (modules/stage.sh) runs each module script under
`denet --json run` and writes <output_dir>/denet.jsonl next to the outputs. Modules
that use obkit's logger also write <output_dir>/obkit-events.jsonl: start and end
records for named phases (load, compute, write, ...). Parsing and the join of the two
are obkit.prof's (installed from the Hephaestus-Hammer/obkit fork, see pixi.toml):
`load_denet` reads the trace, `summarise` gives the whole job, `attribute` splits it
into phases plus "(unphased)", the time no phase covers (Python start-up, imports).

From a trace: wall time, CPU time (cpu_usage integrated over time; 100 % = one busy
core, the module and its child processes), mean and peak cores used, peak memory,
peak threads, GPU utilisation and GPU memory (the process's own where NVML reports
it, else the device's), and the CPU series over time.

Fallback, for jobs without a trace: the `performance.txt` (Snakemake benchmark) ob
writes next to every job: s = wall time, max_rss = peak memory (MB), cpu_time.
Snakemake samples every 0.5 s for 15 s and then every 30 s and loses what happens
after the last sample, so for longer jobs cpu_time and max_rss are lower bounds.
No GPU and no phases there.

Every job is a fresh process, so one-off costs such as numba compiling pynndescent
(~13 s at 10k cells in sc-brrr) are in every kNN job; with phases they land in the
phase that triggers them.
"""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from obkit import prof

# output id -> the stage whose node writes it
STAGE_OF_OUTPUT = {"embedding_tsv": "pca", "neighbors_h5": "knn", "clusters_tsv": "cluster",
                   "rawdata_clusters_truth": "input"}
FIELDS = ["s", "max_rss", "cpu_time", "peak_cores", "max_threads", "gpu_util_mean", "gpu_util_max",
          "gpu_mem_peak_mb", "source"]
PHASE_FIELDS = ["start_s", "duration_s", "cpu_s", "mean_cores", "peak_cores", "peak_rss_mb", "gpu_util_mean",
                "gpu_mem_peak_mb", "samples"]


def _nan(v):
    return np.nan if v is None else v


def read_performance(path):
    """One job's Snakemake benchmark record, or None if the file is missing or empty."""
    path = Path(path)
    if not path.exists():
        return None
    rec = prof.load_snakemake_benchmark(path)
    if rec is None:
        return None
    return {**{k: _nan(rec.get(k)) for k in ("s", "max_rss", "cpu_time")}, "source": "snakemake"}


def read_denet(path):
    """(trace, summary dict, series DataFrame) for one denet trace, or (None, None, None)."""
    path = Path(path)
    if not path.exists():
        return None, None, None
    trace = prof.load_denet(path)
    if trace is None:
        return None, None, None
    tot = prof.summarise(trace)
    d = pd.DataFrame(trace["samples"])
    d["t"] = (d["ts_ms"] - trace["t0_ms"]) / 1000.0
    d["cores"] = d["cpu_usage"] / 100.0
    gpu_util = pd.to_numeric(d["gpu_util"], errors="coerce")
    summary = {"s": tot["duration_s"], "max_rss": tot["peak_rss_mb"], "cpu_time": tot["cpu_s"],
               "peak_cores": tot["peak_cores"], "max_threads": _nan(tot["peak_threads"]),
               "gpu_util_mean": tot["gpu_util_mean"],
               "gpu_util_max": float(gpu_util.max()) if gpu_util.notna().any() else np.nan,
               "gpu_mem_peak_mb": tot["gpu_mem_peak_mb"], "source": "denet"}
    return trace, summary, d[["t", "cores", "mem_rss_kb", "thread_count", "gpu_util"]]


def read_phases(node_dir, trace):
    """obkit.prof.attribute rows for one job, or [] if it logged no phases.

    The logger appends, so an output directory that was run before (a failed attempt,
    a rerun) holds phases from earlier processes too. Only phases that overlap this
    trace are kept. start_s is the phase start in seconds since the trace began.
    """
    path = Path(node_dir) / "obkit-events.jsonl"
    if trace is None or not path.exists():
        return []
    with warnings.catch_warnings():  # a killed job leaves an unmatched start; the rest still counts
        warnings.simplefilter("ignore")
        events = prof.load_events(path)
    events = [e for e in events if e["end_ms"] > trace["t0_ms"] and e["start_ms"] < trace["end_ms"]]
    if not events:
        return []
    rows = prof.attribute(events, trace)
    for r in rows:
        r["start_s"] = 0.0 if r["event"] == "(unphased)" else (r["start_ms"] - trace["t0_ms"]) / 1000.0
    return rows


def runtimes(df):
    """(one row per job, {(size, stage, pipeline): CPU series}, one row per job and phase)
    for every job (node) in df.

    df is load.index(...); each output's directory is its node's directory. A job's
    denet trace is used when present, else its Snakemake benchmark record. Phases need
    both a trace and an obkit event log.
    """
    rows, series, phase_rows, seen = [], {}, [], set()
    for _, r in df.iterrows():
        node_dir = Path(r["path"]).parent
        if node_dir in seen:
            continue
        seen.add(node_dir)
        trace, rec, ser = read_denet(node_dir / "denet.jsonl")
        if rec is None:
            rec = read_performance(node_dir / "performance.txt")
        if rec is None:
            continue
        node = r["nodes"][-1]
        stage = STAGE_OF_OUTPUT.get(r["output"], node.stage)
        job = {"size": r["size"], "stage": stage, "module": node.module,
               "settings": ", ".join(f"{k}={v}" for k, v in node.settings),
               "seed": ", ".join(f"{k}={v}" for k, v in node.seeds), "pipeline": r["label"]}
        rows.append({**job, **{k: rec.get(k, np.nan) for k in FIELDS}})
        if ser is not None:
            series[(r["size"], stage, r["label"])] = ser
        for ph in read_phases(node_dir, trace):
            phase_rows.append({**job, "phase": ph["event"], **{k: _nan(ph.get(k)) for k in PHASE_FIELDS}})
    cols = ["size", "stage", "module", "settings", "seed", "pipeline"]
    return (pd.DataFrame(rows, columns=[*cols, *FIELDS]), series,
            pd.DataFrame(phase_rows, columns=[*cols, "phase", *PHASE_FIELDS]))


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
    if rt["gpu_util_mean"].notna().any() or rt["gpu_mem_peak_mb"].notna().any():
        agg.update({"GPU utilisation % (mean) median": ("gpu_util_mean", "median"),
                    "GPU utilisation % (max) max": ("gpu_util_max", "max"),
                    "GPU memory (MB, peak) median": ("gpu_mem_peak_mb", "median")})
    out = rt.groupby(["size", "stage", "module"]).agg(**agg).reset_index()
    return out.dropna(axis=1, how="all")


def phase_order(ph):
    """{phase: rank}: "(unphased)" first, then by median start time across jobs."""
    starts = ph[ph["phase"] != "(unphased)"].groupby("phase")["start_s"].median().sort_values()
    return {"(unphased)": 0, **{p: i + 1 for i, p in enumerate(starts.index)}}


def summarise_phases(ph, allocated=None):
    """Per size, stage, module and phase ("(unphased)" first, then the order the module
    runs them): jobs, median wall time, its share of the job, mean and peak cores, GPU."""
    if not len(ph):
        return ph
    ph = ph.copy()
    total = ph.groupby(["size", "stage", "pipeline"])["duration_s"].transform("sum")
    ph["share"] = 100 * ph["duration_s"] / total
    # "(unphased)" first (mostly start-up and imports), then phases by when they start
    order = phase_order(ph)
    agg = {"jobs": ("duration_s", "count"), "wall time (s) median": ("duration_s", "median"),
           "share of job (%) median": ("share", "median"), "CPU time (s) median": ("cpu_s", "median"),
           "mean cores used median": ("mean_cores", "median"), "peak cores used max": ("peak_cores", "max"),
           "samples (min)": ("samples", "min")}
    if ph["gpu_util_mean"].notna().any() or ph["gpu_mem_peak_mb"].notna().any():
        agg.update({"GPU utilisation % (mean) median": ("gpu_util_mean", "median"),
                    "GPU memory (MB, peak) max": ("gpu_mem_peak_mb", "max")})
    out = ph.groupby(["size", "stage", "module", "phase"]).agg(**agg).reset_index()
    if allocated:
        out.insert(4, "cores allocated", out["stage"].map(allocated))
    out["_o"] = out["phase"].map(order)
    stage_o = {s: i for i, s in enumerate(STAGE_OF_OUTPUT.values())}
    out = out.sort_values(["size", "stage", "module", "_o"], key=lambda c: c.map(stage_o) if c.name == "stage" else c)
    return out.drop(columns="_o").dropna(axis=1, how="all")
