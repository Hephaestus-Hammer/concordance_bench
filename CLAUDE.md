# concordance-bench

Omnibenchmark (`ob`) benchmark measuring concordance between single-cell
pipelines (scanpy, rapids) across runs and seeds, plus resource use per job.
The README has the goals, the blessed baseline and how to run.

## Layout

```
concordance-bench/
├── README.md                  # goals, blessed baseline, how to run
├── CITATION.cff
├── LICENSE
├── pixi.toml                  # environment for running ob and for the analysis
├── pixi.lock                  # committed: pins ob, denet and analysis versions
├── .gitignore                 # out/, runs/, *.h5ad, caches
│
├── benchmark.yaml             # the ob plan: stages, modules pinned to commits, parameter sets
├── filters/                   # which parts of the plan to run
│   ├── smoke.yaml             #   Hao 10k, 2 seeds: quick end-to-end check
│   ├── cpu-only.yaml          #   no GPU modules
│   └── full.yaml              #   all sizes, all seeds
├── envs/                      # one conda env per software_environment in the plan
│   ├── data.yml
│   ├── scanpy.yml
│   ├── rapids.yml
│   └── analysis.yml
│
├── omnibenchmark.yaml         # entrypoints for this repo's own modules (below)
├── modules/
│   ├── hao_input.py           # Hao .h5ad -> feature-selection output format + truth labels
│   └── concordance.py         # later: pairwise metric stage (once proven in analysis/)
│
├── profiles/
│   └── slurm/config.yaml      # how Snakemake submits jobs on the lab cluster
│
├── analysis/                  # offline: reads the ob output tree, never writes into it
│   ├── load.py                #   finds runs in out/: stage, module, parameters, seed
│   ├── concordance.py         #   PCA |cos| and subspace, kNN overlap, ARI between runs and seeds
│   ├── resources.py           #   parses denet traces: CPU, memory, GPU over time per job
│   └── figures.py             #   the plotting.py panels, plus resource plots
│
├── docs/
│   ├── decisions.md           # why the blessed settings: defaults table, code findings
│   └── metrics.md             # definition of every metric, what "agreement" means
│
├── results/                   # small, committed: what goes in the thesis
│   ├── tables/                #   summary CSVs (per stage x pipeline x dataset)
│   └── figures/
│
└── out/                       # gitignored: ob writes here (nested by stage/module/parameters)
```

## Rules

- `analysis/` only reads `out/`; it never writes into the ob output tree.
- `results/` holds only small, committed outputs (summary CSVs, final figures).
- Metrics are developed in `analysis/concordance.py` first and become the
  `modules/concordance.py` stage only once proven.
- Every metric is defined in `docs/metrics.md`; every non-default setting is
  justified in `docs/decisions.md`.
- Use the omnibenchmark-* skills before writing plan YAML, modules or running `ob`;
  the CLI changes between releases, so check `ob <cmd> --help` rather than guessing.

## Open questions

- **filters/**: `ob run` has no option for running a subset of the plan (as of the
  CLI reference checked). Options: separate plan files sharing a base, a script
  that writes a filtered plan from `benchmark.yaml` + a filter file, or
  `ob run -m <module>` for quick checks. Confirm with `ob run --help`.
- **Own modules in this repo**: the plan pins modules to commits; local paths with
  uncommitted changes need `--dirty`. Either reference this repo's URL + commit,
  or move `hao_input`/`concordance` to a separate module repo (own CITATION.cff,
  LICENSE, envs/, as `ob validate module` expects).

## Running

```sh
ob run benchmark.yaml --cores 8                          # local
ob run benchmark.yaml -- --profile profiles/slurm        # lab cluster (flags after -- go to Snakemake)
ob run benchmark.yaml -m <module>                        # dev: one module's sub-graph only
```
