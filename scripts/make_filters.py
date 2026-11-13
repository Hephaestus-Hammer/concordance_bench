#!/usr/bin/env python3
"""Write the Phase 2 slice filters (filters/phase2/) from benchmark-phase2.yaml, and count their jobs.

A filter can only keep a module's "all" or "first" parameter combination, or a list of
combination hashes. The slices need "every resolution at seed 0" for the baseline Leiden,
which is neither, so this script expands each module's parameters with omnibenchmark's own
code and lists the hashes of the combinations a predicate keeps. Re-run it whenever the plan's
parameters change (hashes follow the parameter values):

    python scripts/make_filters.py            # writes filters/phase2/*.yaml, prints job counts
    python scripts/make_filters.py --sizes in-10k in-50k in-all --out filters/phase2/core
                                              # the same slices on a subset of subsample sizes

Hashes include every parameter value, the module URLs with their commits too: after filling
in or bumping a commit in the plan, re-run this, or ob refuses the stale filters.
Counts include the dataset downloads; ob's dry run reports the same number of rules.

Each slice is written twice: <slice>.yaml (every module, for a GPU host) and <slice>-cpu.yaml
(rapids modules left out: a filter bypasses ob's capability gate, see filters/README.md).

The pipelines slice is five named end-to-end pipelines with matched seeds. A filter picks
modules per stage and ob runs every combination across stages, so one filter for five
pipelines would run all of their crossings, and "seed i" at each stage would run every
combination of seeds. So pipelines/ holds one filter per pipeline and seed, each keeping
exactly one parameter combination per stage (seed i where the module is seeded, its only
run where it is not; Leiden at every resolution). scripts/run_pipelines.sh runs them.
"""

import argparse
from pathlib import Path

import yaml
from omnibenchmark.model.benchmark import Benchmark
from omnibenchmark.model.params import Params

ROOT = Path(__file__).resolve().parent.parent
ALL = "all"


def seed0(params):
    return int(params.get("random_seed", 0)) == 0


# stage -> module -> "all" | predicate on a parameter combination (dict). Stages not listed run
# every module ("*": all): the datasets and the subsample sizes.
SLICES = {
    "slice-cluster": {
        "pca": {"pc-baseline": ALL},
        "knn": {"nn-baseline": ALL},
        "cluster": {"cl-baseline": ALL, "cl-scanpy": ALL, "cl-rapids": ALL},
    },
    "slice-knn": {
        "pca": {"pc-baseline": ALL},
        "knn": {"nn-baseline": ALL, "nn-scanpy": ALL, "nn-scanpy-mt": ALL, "nn-rapids": ALL},
        "cluster": {"cl-baseline": seed0},
    },
    "slice-pca": {
        "pca": {m: ALL for m in ("pc-baseline", "pc-scanpy", "pc-randomized", "pc-lanczos", "pc-rapids",
                                 "pc-rapids-randomized", "pc-rapids-lanczos", "pc-rapids-jacobi")},
        "knn": {"nn-baseline": ALL},
        "cluster": {"cl-baseline": seed0},
    },
}


# The named pipelines (docs/phase2-plan.md): PCA, kNN and Leiden module of each.
PIPELINES = {
    "baseline":        {"pca": "pc-baseline",   "knn": "nn-baseline",  "cluster": "cl-baseline"},
    "scanpy-defaults": {"pca": "pc-scanpy",     "knn": "nn-scanpy",    "cluster": "cl-scanpy"},
    "tuned-cpu":       {"pca": "pc-randomized", "knn": "nn-scanpy-mt", "cluster": "cl-baseline"},
    "all-gpu":         {"pca": "pc-rapids",     "knn": "nn-rapids",    "cluster": "cl-rapids"},
    "hybrid":          {"pca": "pc-rapids",     "knn": "nn-rapids",    "cluster": "cl-baseline"},
}


def combos(module):
    out = []
    for pset in module.parameters or []:
        out.extend(Params.expand_from_parameter(pset))
    return out


def picks_and_counts(bench, spec, cpu_only, sizes=None):
    stages = {s.id: s for s in bench.stages}
    gpu = {m.id for s in bench.stages for m in s.modules if "gpu" in (m.requires_capabilities or [])}
    picks, n_combos = {}, {}
    for stage in bench.stages:
        wanted = spec.get(stage.id)
        if stage.id == "input" and sizes:
            picks[stage.id] = {m.id: ALL for m in stage.modules if m.id in sizes}
            continue
        if wanted is None:
            picks[stage.id] = {"*": ALL}
            continue
        picks[stage.id] = {}
        for m in stage.modules:
            if m.id not in wanted or (cpu_only and m.id in gpu):
                continue
            rule, cs = wanted[m.id], combos(m)
            if rule == ALL:
                picks[stage.id][m.id], n_combos[m.id] = ALL, len(cs)
            else:
                keep = [c for c in cs if rule(dict(c.items()))]
                picks[stage.id][m.id], n_combos[m.id] = [c.hash_short() for c in keep], len(keep)
    # jobs per (dataset, size), respecting the input modules' excludes
    per_stage = {sid: sum(n_combos[m] for m in picks[sid]) for sid in spec}
    data_ids = [m.id for m in stages["data"].modules]
    rows = []
    datasets = set()
    for size in stages["input"].modules:
        if sizes and size.id not in sizes:
            continue
        for d in data_ids:
            if d in (size.exclude or []):
                continue
            p = per_stage["pca"]
            k = p * per_stage["knn"]
            c = k * per_stage["cluster"]
            rows.append((d, size.id, 1 + p + k + c))
            datasets.add(d)
    return picks, rows, len(datasets)


def _seed(c):
    return int(dict(c.items()).get("random_seed", 0))


def pipeline_filters(bench, sizes=None):
    """{(pipeline, seed): picks}, and the job count over their union (shared jobs counted once)."""
    stages = {s.id: s for s in bench.stages}
    mods = {m.id: m for s in bench.stages for m in s.modules}
    seeds = sorted({_seed(c) for p in PIPELINES.values() for mid in p.values() for c in combos(mods[mid])})
    data_ids = [m.id for m in stages["data"].modules]
    sizes_kept = [m for m in stages["input"].modules if not sizes or m.id in sizes]
    out, lineages = {}, set()
    for name, p in PIPELINES.items():
        for i in seeds:
            picks = {"data": {"*": ALL},
                     "input": {m.id: ALL for m in sizes_kept} if sizes else {"*": ALL}}
            chosen = {}
            for stage in ("pca", "knn", "cluster"):
                cs = combos(mods[p[stage]])
                keep = [c for c in cs if _seed(c) == i] or [c for c in cs if _seed(c) == min(map(_seed, cs))]
                picks[stage] = {p[stage]: [c.hash_short() for c in keep]}
                chosen[stage] = [c.hash_short() for c in keep]
            out[(name, i)] = picks
            for size in sizes_kept:
                for d in data_ids:
                    if d in (size.exclude or []):
                        continue
                    pc = (d, size.id, p["pca"], chosen["pca"][0])
                    kn = pc + (p["knn"], chosen["knn"][0])
                    lineages.update({("pca",) + pc, ("knn",) + kn})
                    lineages.update(("cluster",) + kn + (p["cluster"], h) for h in chosen["cluster"])
                    lineages.add(("input", d, size.id))
    jobs = len(lineages) + len({l[1] for l in lineages if l[0] == "input"})  # + dataset downloads
    return out, jobs


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plan", type=Path, default=ROOT / "benchmark-phase2.yaml")
    ap.add_argument("--out", type=Path, default=ROOT / "filters" / "phase2")
    ap.add_argument("--sizes", nargs="+", help="input modules to keep (default: every subsample size)")
    args = ap.parse_args()
    bench = Benchmark.from_yaml(args.plan)
    args.out.mkdir(parents=True, exist_ok=True)
    grand = {}
    for name, spec in SLICES.items():
        for cpu_only in (False, True):
            picks, rows, n_data = picks_and_counts(bench, spec, cpu_only, args.sizes)
            fname = f"{name}{'-cpu' if cpu_only else ''}.yaml"
            total = n_data + sum(r[2] for r in rows)
            head = (f"# GENERATED by scripts/make_filters.py from {args.plan.name}: re-run after editing "
                    f"the plan.\n# {name}{' (CPU modules only)' if cpu_only else ''}: "
                    f"{total} jobs over {len(rows)} dataset x size combinations.\n")
            (args.out / fname).write_text(head + yaml.safe_dump({"picks": picks}, sort_keys=False))
            grand[fname] = (total, rows)
    pdir = args.out / "pipelines"
    pdir.mkdir(parents=True, exist_ok=True)
    for old in pdir.glob("*.yaml"):
        old.unlink()
    pfilters, pjobs = pipeline_filters(bench, args.sizes)
    for (name, i), picks in pfilters.items():
        head = (f"# GENERATED by scripts/make_filters.py from {args.plan.name}: re-run after editing the plan.\n"
                f"# Pipeline {name}, seed {i}: {' > '.join(PIPELINES[name].values())}, Leiden at every resolution.\n")
        (pdir / f"{name}-seed{i}.yaml").write_text(head + yaml.safe_dump({"picks": picks}, sort_keys=False))
    print(f"{'filter':24s} {'jobs':>7s}  {'per dataset x size':>18s}  dataset x size")
    for fname, (total, rows) in grand.items():
        print(f"{fname:24s} {total:7d}  {rows[0][2]:18d}  {len(rows)}")
    print(f"{'pipelines/ (' + str(len(pfilters)) + ' files)':24s} {pjobs:7d}  {'(shared jobs once)':>18s}")


if __name__ == "__main__":
    main()
