# CI for a module, and running a plan's validators locally

**What is core `ob`:** `ob validate module`, `ob validate plan`, `ob run`.
Everything else on this page — the `validate-module` GitHub Action, the
`validators/` directory convention, the boilerplate sync — is **omni-scrna
house style**: conventions of the `omni-scrna` organisation, useful as a
worked pattern, not part of the tool. Where a convention is on its way into the
core, this page says so.

## GitHub CI for a module (house style)

One file in the module, `.github/workflows/validate-module.yml`, deliberately
tiny so upstream fixes land without re-installing anything:

```yaml
name: Validate module

on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:

jobs:
  validate-module:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: omni-scrna/boilerplate/actions/validate-module@main
```

That is the whole file. The composite action (`omni-scrna/boilerplate` →
`actions/validate-module/action.yml`) brings its own pixi manifest with
omnibenchmark in it and runs `ob validate module`, so **the module does not have
to be pixi-based and takes on no omnibenchmark dependency of its own**.

Inputs:

| input | default | meaning |
| --- | --- | --- |
| `path` | `.` | module directory to validate |
| `strict` | `"false"` | pass `--strict` (warnings become failures) |

```yaml
      - uses: omni-scrna/boilerplate/actions/validate-module@main
        with:
          strict: "true"
```

Two things to tell the author:

- `strict: "true"` will fail any module whose `entrypoints:` has no `default:`
  key — which is every module that replaced `default` with named entrypoints.
  Keep `default:` as an alias, or leave CI non-strict.
- `@main` means upstream fixes arrive automatically, and so would a breaking
  change. Pin a tag if the module needs stability.

The boilerplate also ships `actions/install.sh <action> <module-path>`, a POSIX
installer that copies the same caller workflow in and never overwrites an
existing one. Hand-writing the six lines above is equally fine.

### What this CI does and does not prove

It runs metadata validation only: CITATION.cff, LICENSE consistency,
`omnibenchmark.yaml` shape. It does not execute your entrypoint, does not look
at outputs, and passes on an empty scaffold. Output correctness is the
validators' job, below.

## The plan's output validators (house style, prototype of a core feature)

A plan repository may carry validators for its stages' outputs, routed by path:

```
validators/<STAGE>/<OUTPUT_FILE>/validate.{R,py}
validators/all.sh
```

Convention (from the reference plan `omni-scrna/split-stages-plan` and the
boilerplate's copy of it):

- each validator receives **one output file path per invocation** (in practice
  several, via `xargs`, and loops over `commandArgs()` / `sys.argv[1:]`);
- as few dependencies as possible — they run in a small `validation`
  environment, not the module's;
- they print `OK\t<path>` or `FAIL\t<path>\t<reason>` **and exit 0 either way**.
  Grep the output; do not rely on the exit status.

A real one, checking a PCA output table, asserts: the first column is named
`PC1`, the file is non-empty, there are at least 10 columns, and the first data
row has no NAs. A data-stage validator asserts that no `obs` column in an
`.h5ad` is categorical-encoded, because the downstream R modules read those
columns with `rhdf5::h5read`, which mangles the categorical group encoding.
That is the flavour to aim for: each check exists because something broke once.

### Run them against your own outputs before pushing

```bash
# from the plan checkout, after `ob run … -m <your-module>` wrote into out/
find ../out -name "*pcas.tsv" | xargs Rscript validators/five-pca/pcas.tsv/validate.R
sh validators/all.sh                 # runs every validator over ../out
```

`all.sh` hardcodes `../out` relative to the plan root — if you ran with
`--out-dir`, invoke the individual validators instead.

Two gotchas worth reading the directory for rather than guessing:

- the directory names are mid-rename in the reference plan (`five-pca`, `NORM`,
  `one-data` coexist), so `ls validators/` before constructing a path;
- the output subdirectory is named for the *file*, not the plan's output id
  (`pcas.tsv`, `rawdata.h5ad`), and your module's file may be named differently
  while satisfying the same contract — check which validator applies.

Design doc `002-module-artifact-validation.md` (Draft) in
`omnibenchmark/omnibenchmark` proposes folding this into the core as a
`validation.yaml` with a mini-DSL. Until that lands, validators are a plan-side
convention that `ob` neither knows about nor runs.

## Ordering: local first, CI second

1. `pixi run check` — the environment imports.
2. Run the entrypoint directly on one small input; look at the output file.
3. The contract assertions (SKILL.md §6) fire during that run.
4. `ob run <plan> -m <module-id> --dirty --cores 4` — the module under the plan.
5. The plan's validators over `out/`.
6. `ob validate module` — cheap, last, and only tells you the metadata is sane.
7. Push; CI repeats step 6 on a clean checkout.

CI is a regression net, not the feedback loop. Anything you can check in step 2
should not be discovered in step 7.

## The boilerplate sync (lab-specific)

Modules in this organisation vendor shared CLI helpers and the benchmark's stage
schemas into `src/common/`, driven by two keys in `omnibenchmark.yaml` that
**core `ob` ignores**:

```yaml
templates:                       # where the shared cli.py / cli.R comes from
  repo: https://github.com/omni-scrna/boilerplate
  ref: main
  lang: python

benchmarks:                      # whose schema/ dir to vendor
  - name: split-stages
    repo: https://github.com/omni-scrna/split-stages-plan
    plan: benchmark_conda.yaml
    ref: main
```

`pixi run -e dev sync` fetches both and writes `src/common/` plus
`src/common/.origin.json` (the resolved commits). Outside this organisation,
skip all of it: write the parser by hand, as the generated scaffold does.

Two known drifts, so you do not trust the wrong source: the boilerplate's
`AGENTS.md` documents the first key as `boilerplate:` while its own
`scripts/pull.py` reads `templates:` (the script and the real modules win), and
one exemplar module declares `templates:` twice, so YAML silently keeps the
second block.
