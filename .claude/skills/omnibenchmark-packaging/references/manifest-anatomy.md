# Anatomy of a module `pixi.toml` — what the exemplars actually share

Surveyed: the thirteen `pixi.toml` files in the public
`omni-scrna/split-stages-plan-modules` repo (`5-pca-irlba-r`,
`5-pca-onlinepca.jl`, `5-pca-truncatedsvd-sklearn`, `9-annotate`, `cookbook`,
`datasets`, `metrics`, `pca-biocsingular-r`, `rapids-singlecell`, `rcppml`,
`scanpy`, `scvi`, `seurat`), cross-checked against `omni-scrna/boilerplate`
(`pixi.toml`) and the plan repo `omni-scrna/split-stages-plan` (`pixi.toml`).

These repos are public and are good worked examples of **module structure and
packaging**. Their plan-facing metadata is legacy: the plan declares
`api_version: "0.4.0"` and predates `provides`/`requires`/`gather`. Copy their
packaging patterns; do not copy their plan contract. For the plan grammar the
authority is design doc `004-yaml-specification.md` in
`omnibenchmark/omnibenchmark`.

Not every repo listed is a benchmark module: `cookbook` is a sample-collection
repo and `boilerplate`/`split-stages-plan` are tooling manifests for the
template and the plan themselves. They are included because the contrast is
informative — a module manifest looks different from a tooling manifest.

## Field by field

| field | shared? | detail |
| --- | --- | --- |
| `[workspace]` vs `[project]` | 12 / 13 use `[workspace]` | only `cookbook` still uses the older `[project]`. New manifests: `[workspace]`. |
| `channels` | `["conda-forge", "bioconda"]` in 8 | 3 use `conda-forge` alone (`cookbook`, `rapids-singlecell`, `scvi` — no bioconda package needed). `datasets` appends `https://prefix.dev/almost-conductor`; `rcppml` puts it **first**, deliberately, for precedence. |
| `platforms` | `["linux-64"]` in 12 | `scanpy` adds `osx-arm64`; `cookbook` adds `osx-arm64` and `osx-64`. Benchmark runs are linux-64; extra platforms are a developer convenience and they constrain the solve, so add one only if someone develops there. |
| `name` | always present | usually the repo directory name; `9-annotate` uses the numbered directory name while its exported env is `annotate.yml`, so the two can differ. |
| `version` | `"0.1.0"` in 11 | `metrics` is `0.1.1`; `cookbook` omits it. Nothing reads it — the plan pins modules by git commit, not by this version. |
| `authors` | 10 of 13 | free-form; `metrics`, `seurat` and `cookbook` omit it. |
| `[tasks] export-env` | 11 of 13 | absent only in `9-annotate` and `cookbook`. Character-identical across all eleven apart from the output filename. |
| `[tasks] check` | 9 of 13 | `python check.py` / `Rscript check.R` / `julia --project=. check.jl`. |
| `[pypi-dependencies]` | 4 of 13 | `metrics` (`scib-metrics`), `rapids-singlecell` (3 entries), `scanpy` and `scvi` (`obkit`). |
| dev/bootstrap feature | 5 of 13 | `9-annotate`, `rapids-singlecell`, `scanpy`, `scvi` (feature `dev`), `seurat` (feature `bootstrap`). All five set `no-default-feature = true`. |
| test feature | 2 of 13 | `scanpy` (`test` feature → `test` env, layered) and `seurat` (`test` feature → env confusingly *named* `dev`). |
| `pixi.lock` committed | 10 of 13 | absent in `5-pca-irlba-r`, `5-pca-truncatedsvd-sklearn`, `cookbook`. |

## Where the canonical scanpy pattern does not generalise

The scanpy manifest is a fair template for a **Python** module. Two of its
features are not lab-wide conventions:

1. **Both-bounds pinning is a Python-side habit, not a house rule.** The Python
   modules pin tightly (`h5py = ">=3.16.0,<4"`, `anndata = ">=0.12.11,<0.13"`,
   `numpy = ">=2.4.3,<3"`). The R modules mostly use `"*"` with a floor on
   `r-base` only: `5-pca-irlba-r`, `pca-biocsingular-r`, `rcppml` and `seurat`
   leave every bioconductor and CRAN dependency unbounded. `9-annotate` is the
   exception and bounds everything.

   Neither is wrong, and the difference is not arbitrary: the R packages come
   from bioconductor, which already ships one coherent release set per
   `bioconductor-biocversion` (the `metrics` module pins that instead:
   `bioconductor-biocversion = "3.22.*"`), whereas conda-forge Python packages
   move independently. Follow the convention of the language you are packaging,
   and pin tightly wherever a version difference would change the numbers.

2. **The `test` environment is rare.** Only scanpy has the exact
   `test = { features = ["test"] }` shape. Do not add one unless there are tests.

Three things *are* effectively universal and should go in every new module
manifest: `[workspace]` with `channels`/`platforms`/`name`/`version`, the
`export-env` task, and a `check` task.

## Manifests that are not modules

- `omni-scrna/boilerplate` → `pixi.toml` is for working *on* the template. It is
  never copied into a generated module. Its tasks (`docs`, `lint`, `typecheck`,
  `test`, `check` as a `depends-on` aggregate) are a fine model for a repo with
  CI, and a bad model for a benchmark module, which should stay small.
- `omni-scrna/split-stages-plan` → `pixi.toml` is the *plan's* manifest and shows
  the pattern for pinning `ob` itself:

  ```toml
  [feature.plan.dependencies]
  python = ">=3.12,<3.14"
  pip = "*"
  conda = "*"      # so `ob run` (snakemake --use-conda) has a backend in-env

  [feature.plan.pypi-dependencies]
  omnibenchmark = { git = "https://github.com/omnibenchmark/omnibenchmark.git", rev = "071c56d98" }

  [feature.plan.tasks]
  validate-plan = "ob validate plan benchmark_conda.yaml"
  ```

  Note `rev =` rather than `branch =`: the manifest's own comment records that
  two machines installing from a branch on different days landed on different
  commits, which would have run two halves of one benchmark on two different
  `ob` versions. Pin a rev for anything that affects results.

  The `omni-scrna/boilerplate` CI action (`actions/validate-module`) uses
  `branch = "main"` instead — acceptable there because it only runs
  `ob validate module`, which does not produce results.

## The exported YAML

`pixi workspace export conda-environment` emits, in order: the `name:` from
`--name`, `channels:` in manifest order with `nodefaults` appended, then
`dependencies:` as `- <package> <spec>` in manifest order, then (if there are
any) a bare `- pip` followed by a `- pip:` list. The exports in the exemplars
are 8–30 lines. A module export that is much longer than its `[dependencies]`
table means something unexpected happened — read it before committing.
