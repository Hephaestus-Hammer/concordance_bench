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

## Open questions

- **Own modules in this repo**: the plan pins modules to commits; local paths with
  uncommitted changes need `--dirty`. Either reference this repo's URL + commit,
  or move `hao_input`/`concordance` to a separate module repo (own CITATION.cff,
  LICENSE, envs/, as `ob validate module` expects).
