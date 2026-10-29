# concordance-bench

Omnibenchmark (`ob`) benchmark measuring concordance between single-cell
pipelines (scanpy, rapids) across runs and seeds, plus resource use per job.
`README.md` has the goals, the repository layout and how to run; read it first.

## Rules

- `analysis/` only reads `out/`; it never writes into the ob output tree.
- `results/` holds only small, committed outputs (summary CSVs, final figures).
- Metrics are developed in `analysis/concordance.py` first and become the
  `modules/concordance.py` stage only once proven.
- Every metric is defined in `docs/metrics.md`; every non-default setting is
  justified in `docs/decisions.md`.
- Keep `README.md` in step when the layout or the run commands change.

## Working with ob

- Use the omnibenchmark-* skills in `.claude/skills/` before writing plan YAML,
  modules or running `ob`.
- `ob` is pinned to 0.7.0 in `pixi.toml`. Its CLI changes between releases, so
  check `ob <cmd> --help` in the pixi environment rather than guessing flags.
- The plan uses `api_version: "0.7.0"`.
- Stages, outputs and plan parameters are the author's decisions: ask before
  writing them into `benchmark.yaml`.
- Run everything inside the pixi environment (`pixi run <cmd>` or `pixi shell`).
- This repo's own modules (`modules/`, entrypoints in `omnibenchmark.yaml`) are
  referenced from the plan by this repo's URL and a commit. Changing one is two
  commits: the module, then the plan bumped to that commit's SHA. For local
  development, point the module at `url: .` and run with `--dirty`.
- `--filter` bypasses the capability gate: a filter that picks rapids modules runs
  them even on a CPU host. Filters meant for CPU hosts must leave them out.
- The omni-scrna module CLIs reject unknown arguments, so a plan parameter they
  don't define fails the job.

## Open questions

- **Seeds (decided 27/10).** Seeded modules list `random_seed` 0-19 (seed 0
  first); the noise floor is measured one stage at a time through
  `filters/noise-*.yaml` (`all` on one stage, `first` elsewhere). Matched seeds
  across stages are not needed: a seed number means nothing across stages. Every
  `ob run` goes through a filter. Same-seed replicates (non-seed noise such as
  GPU atomics) will be separate `ob run`s into separate output folders, merged in
  `analysis/`, instead of `hao_input`'s `replicate` parameter (Ben's suggestion).
- **Baseline on a fork.** `pc-/nn-/cl-baseline` pin `Hephaestus-Hammer/scanpy`
  (branch `baseline-options`), which adds `covariance_eigh`, `--transformer` and
  `--n_iterations` to omni-scrna/scanpy. Move them back to `omni-scrna/scanpy`
  once those are merged upstream. `knn.py` and `cluster.py` have no BLAS thread
  setting yet, so only the baseline PCA is single-threaded.
- **Environment pinning.** `envs/` are the modules' own exports with loose version
  ranges. Lock them to exact builds (as sc-brrr does) before comparing results.
- **Resource traces.** Every PCA, kNN and Leiden module runs through the `stage`
  entrypoint (`modules/stage.sh`, like sc-brrr's `prof.sh`): the module is the
  `module` parameter (`<url>@<commit>`), its script `script`; the script runs
  unchanged under denet (`<output_dir>/denet.jsonl`, `module.log`). Changing a
  module means changing its `module` parameter. Jobs without a trace fall back to
  Snakemake's `performance.txt` (sparse sampling: lower bounds).
