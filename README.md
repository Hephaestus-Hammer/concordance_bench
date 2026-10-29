# concordance-bench

An [Omnibenchmark](https://github.com/omnibenchmark/omnibenchmark) (`ob`) benchmark
measuring concordance between single-cell pipelines (scanpy, rapids) across runs
and seeds, plus resource use (CPU, memory, GPU) per job.

## Goals

Answering how much invisible computational choices in the PCA $\rightarrow$ kNN step (hardware, library, build, seed) and clustering change the results, how does that compare with seed noise, and does it grow with dataset size?

## Blessed baseline

The reference every other pipeline is compared against: a CPU pipeline with every
source of randomness and approximation removed, so that repeated runs give
bitwise-identical results. Full reasoning and the defaults it overrides:
[`docs/decisions.md`](docs/decisions.md).

```mermaid
flowchart LR
    data[("Hao 2021<br/>log-normalised,<br/>2,000 HVGs")] --> pca
    pca["<b>PCA</b><br/>covariance_eigh<br/>50 PCs · float64"] --> knn
    knn["<b>kNN graph</b><br/>exact (brute force)<br/>k = 15 · UMAP weights"] --> leiden
    leiden["<b>Leiden</b><br/>leidenalg · undirected<br/>until converged · γ = 1<br/>seeds 0–19"]
```

| Stage | Setting | Why |
|---|---|---|
| PCA | `covariance_eigh`, float64 | Direct method: no iterations, tolerance or random start, so the seed has no effect. scanpy's default (`arpack`) is iterative and seed-dependent. |
| kNN | exact search, `method="umap"` | Exact at every size; scanpy's default switches silently to approximate search above 8,192 cells. Connectivities are deterministic once the neighbours are fixed. |
| Leiden | leidenalg, `directed=False`, `n_iterations=-1`, resolution 1.0 | Reproducible per seed and runs to convergence; avoids igraph's `n_iterations=-1` bug; undirected like the GPU implementation. |
| All | single-threaded BLAS, versions pinned | Multithreaded reductions can change results in the last bits between runs. |

Leiden is a randomised heuristic: different seeds reach different, equally valid
partitions. The baseline is therefore run over 20 seeds, and the **seed-to-seed
agreement is the noise floor** against which other pipelines (scanpy defaults,
rapids-singlecell, other kNN libraries and builds) are judged.

**Status:** `omni-scrna/scanpy` does not yet expose `covariance_eigh`, exact kNN
or `n_iterations`. The baseline modules (`pc-baseline`, `nn-baseline`,
`cl-baseline`) therefore run the
[`Hephaestus-Hammer/scanpy`](https://github.com/Hephaestus-Hammer/scanpy/tree/baseline-options)
fork, which adds them; the plan moves back to `omni-scrna/scanpy` once they are
merged upstream.

## Setup

The environment is managed with [pixi](https://pixi.sh) and pins `ob`, denet and
the analysis stack in `pixi.lock`.

```sh
pixi install
pixi shell        # or prefix commands with `pixi run`
```

## The plan

`benchmark.yaml` runs the Hao 2021 PBMC data at 10k, 50k and 100k cells through
separate PCA, kNN and clustering stages, each with three modules: scanpy
defaults (CPU), the blessed baseline (CPU) and rapids-singlecell (GPU):

```
data -> input (hao_input) -> pca -> knn -> cluster
```

| Stage | scanpy defaults | baseline | rapids-singlecell |
|---|---|---|---|
| `data` | the published sc-brrr input on Hugging Face, pinned to a dataset revision | | |
| `input` | `hao_input`: `.h5ad` -> omni-scrna feature-selection format + truth labels | | |
| `pca` | arpack, 50 PCs, float64 | covariance_eigh, 50 PCs, float64, 1 BLAS thread | covariance eigh, 50 PCs, float64 |
| `knn` | 15 neighbours, pynndescent (approximate above 8,192 cells) | 15 neighbours, exact (sklearn brute force) | 15 neighbours, cuVS brute force (exact) |
| `cluster` | Leiden (igraph, 2 iterations), resolution 1.0 | Leiden (leidenalg, until converged), resolution 1.0 | Leiden, resolution 1.0 |

Every module consumes every upstream output, so implementations mix (e.g. rapids
PCA -> baseline kNN -> scanpy Leiden): 27 combinations per size, 81 in all (8 per
size on a CPU host). That is what attributes disagreement to a stage. The
scanpy-defaults and rapids modules are
[omni-scrna/scanpy](https://github.com/omni-scrna/scanpy) and
[omni-scrna/rapids-singlecell](https://github.com/omni-scrna/rapids-singlecell),
run unchanged.

Seeded modules (arpack PCA, pynndescent kNN, every Leiden) list seeds 0-19. The
noise floor is measured one stage at a time: `filters/noise-*.yaml` vary one
stage's seed while every other stage stays at seed 0. Always run through a
filter: without one, the seed lists expand against each other.

## Running

```sh
pixi run validate                                         # ob validate plan benchmark.yaml
pixi run dry                                              # ob run benchmark.yaml --dry (writes out/Snakefile only)
ob run benchmark.yaml --cores 8                           # the whole plan; on a CPU host, rapids is skipped
ob run benchmark.yaml --cores 8 --with-capability gpu     # the whole plan, including rapids
ob run benchmark.yaml --filter filters/smoke.yaml         # a slice of the plan (see below)
ob run benchmark.yaml -- --profile profiles/slurm         # on the lab cluster (flags after -- go to Snakemake)
ob run benchmark.yaml -m <module>                         # dev: one module's sub-graph only
```

Results land in `out/` (gitignored), nested by stage, module and parameters.

```sh
pixi run report        # every metric and figure in one file: results/report/concordance_report.html
```

The report also writes one TSV per table next to the HTML. It reads `out/` and
never writes into it. Its Runtime tab shows per job: wall time, mean and peak
cores used against the cores the stage is given, peak memory, GPU use, and cores
over time. It reads each job's denet trace (`denet.jsonl`, see below) and falls
back to the `performance.txt` ob writes next to every job; Snakemake samples that
sparsely after a job's first 15 s, so its CPU time and memory are lower bounds.
The data stage downloads from Hugging Face, so the host running it needs network
access.

### Running part of the plan

`ob run --filter <file>` prunes the plan to the stages, modules and parameter
combinations picked in an obfilter file. The files in `filters/` are those picks:

| Filter | Runs | Host |
|---|---|---|
| `smoke.yaml` | 10k, CPU modules (scanpy defaults + baseline), seed 0: 8 combinations | any |
| `smoke-gpu.yaml` | 10k, every module, seed 0: 27 combinations | GPU |
| `cpu-only.yaml` | all sizes, CPU modules, seed 0 | any |
| `noise-pca.yaml` | all sizes, CPU modules: 20 arpack PCA seeds, seed 0 downstream | any |
| `noise-knn.yaml` | all sizes, CPU modules: 20 pynndescent kNN seeds, seed 0 elsewhere | any |
| `noise-cluster.yaml` | all sizes, CPU modules: 20 Leiden seeds, seed 0 upstream | any |

**A filter bypasses the capability gate:** every module it picks runs, even
rapids on a CPU host. That is why the CPU filters leave the rapids modules out.
`--allow-drift` lets a filter run after the plan has changed, skipping picks that
no longer exist.

## Layout

```
concordance-bench/
├── README.md
├── CLAUDE.md                  # working rules for Claude Code sessions
├── CITATION.cff
├── LICENSE
├── pixi.toml                  # environment for running ob and for the analysis
├── pixi.lock                  # committed: pins ob, denet and analysis versions
├── .gitignore                 # out/, runs/, *.h5ad, caches
│
├── benchmark.yaml             # the ob plan: stages, modules pinned to commits, parameter sets
├── filters/                   # which parts of the plan to run (ob run --filter)
│   ├── smoke.yaml
│   ├── smoke-gpu.yaml
│   └── cpu-only.yaml
├── envs/                      # one conda env per software_environment in the plan
│   ├── data.yml               #   omni-huggingface (data download)
│   ├── scanpy.yml             #   omni-scrna/scanpy; also runs hao_input
│   └── rapids.yml             #   omni-scrna/rapids-singlecell (CUDA 13)
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
│   ├── figures.py             #   one function per report figure
│   └── report.py              #   all of the above in one self-contained HTML file
│
├── docs/
│   ├── decisions.md           # why the blessed settings: defaults table, code findings
│   └── metrics.md             # definition of every metric, what "agreement" means
│
├── results/                   # small, committed: what goes in the thesis
│   ├── tables/                #   summary CSVs (per stage x pipeline x dataset)
│   └── figures/
│
└── out/                       # gitignored: ob writes here
```

Not written yet: `modules/concordance.py`, `analysis/resources.py` and `LICENSE`.

## Citation

See [`CITATION.cff`](CITATION.cff).
