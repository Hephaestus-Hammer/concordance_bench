---
name: omnibenchmark-wrapping
description: "Port an existing tool into an Omnibenchmark benchmark: given an upstream PyPI package, R/Bioconductor package or git repo and a target stage in an existing plan, wrap it as a module that satisfies that stage's contract. Load this when asked to 'port', 'wrap', 'add an arm for' or 'benchmark' a named tool, when adding a method to an existing stage, when deciding which upstream function is the method and which of its arguments become plan parameters, or when the tool's natural output does not match the outputs the stage declares."
---

# Wrapping an upstream tool as a module

A wrapper module is small. In the public `omni-scrna/split-stages-plan-modules`
repo the PCA-stage wrappers run 59–92 lines including comments and the
licence-style header (`rcppml/pca.R` is 35 lines of actual code,
`5-pca-irlba-r/pca.R` 58, `5-pca-truncatedsvd-sklearn/pca.py` 55). In each of
them the *method* is one function call. Everything else is reading the stage's
input file, naming things the way the contract wants, and writing the declared
output files.

If your draft is heading past ~100 lines, the design is wrong. Stop and say so
rather than writing more.

> The `omni-scrna` repos cited throughout are public and are excellent worked
> examples of **module structure and wrapper logic**. Their plan-facing metadata
> is legacy — the plan declares `api_version: "0.4.0"` and predates `provides`,
> `requires` and `gather` — so do not copy their plan contract. For the plan
> grammar the authority is design doc `004-yaml-specification.md` in
> `omnibenchmark/omnibenchmark`, and new plans are written at
> `api_version: "0.7.0"`.

## Order of operations

Do these in order. Steps 1–3 happen before a single line of code exists.

0. Check obcommons for an existing module that already wraps the tool
   (`omnibenchmark-module` skill, §0). Reusing one beats writing one.
1. Read the stage contract.
2. Find the one upstream function that is the method.
3. Ask the author the design questions. Wait for answers.
4. Choose the entrypoint language to match the tool.
5. Scaffold with `ob create module --for-stage`.
6. Write the adapter — the smallest thing that satisfies the contract.
7. Pin the upstream version, export the environment, wire the module into the plan.

## 1. Read the stage contract first

You cannot write the adapter until you know exactly what arrives and what must
leave. Four places to look, in this order:

- **The plan's stage block.** `stages[].inputs` (the input ids, which become
  `--<input_id>` flags), `stages[].outputs[].{id,path}` (the files you must
  write, with `{dataset}`-style wildcards in the path), and — on an existing
  sibling module in the same stage — `parameters`, `software_environment`, and
  `repository.{url,commit,entrypoint}`.
- **Sibling modules in the same stage.** The fastest way to learn the real
  conventions: what the output columns are called, what orientation the input
  matrix has, whether ids go in a column or in row names. Read one before
  writing anything.
- **The stage schema, if the benchmark has one.** `omni-scrna` benchmarks keep
  `schema/<stage-id>.json` — a named, versioned list of flags every module in
  that stage accepts, shared by the Python and R CLI helpers. This is house
  style, not core `ob`; core `ob` only knows the plan.
- **The validators, if the benchmark has them.** `omni-scrna/split-stages-plan`
  keeps `validators/<stage>/<output-file>/validate.{R,py}`. These are the
  literal acceptance test. The PCA validator, for instance, requires the first
  column to be named `PC1`, a non-empty table, at least ten columns, and no
  non-numeric values in the first data row. That single file answers four
  questions you would otherwise have had to ask.

Write down, in one short block, what you concluded before you continue:

```
stage:    PCA
inputs:   --normalized_selected_h5   (TENx-layout HDF5, genes x cells, CSC)
outputs:  {name}_embedding.tsv   cells x k, first column PC1, >= 10 columns
          {name}_loadings.tsv    genes x k
always:   --output_dir, --name
```

`--output_dir` and `--name` are passed by Omnibenchmark on every invocation.
Outputs go inside `--output_dir`, named exactly as the stage's `path` declares.

## 2. Find the one upstream function that is the method

Most packages are large; the thing being benchmarked is usually a single
function. Name it explicitly before you start:

| module | upstream | the method |
| --- | --- | --- |
| `5-pca-irlba-r` | irlba (CRAN) | `irlba::irlba(Xt, nv = k, center = col_means)` |
| `rcppml` | RcppML | `RcppML::svd(X, k =, center = TRUE, method =, seed =)` |
| `scrapper` | scrapper / libscran | `runPca(X, number = k, seed =, num.threads =)` |
| `5-pca-truncatedsvd-sklearn` | scikit-learn | `TruncatedSVD(...).fit_transform(X)` |
| `scvi` | scvi-tools | `SCVI(adata, n_latent).train(...)` → `get_latent_representation()` |

If you cannot name it in one line, you do not yet understand the tool well
enough to wrap it — read the upstream docs, or ask.

## 3. Ask, do not assume

This is the step that pays for itself. A wrong assumption baked into a module is
far more expensive than one round-trip. Put the questions as concrete either/or
choices, not open-ended ones, and wait for answers before writing code.

The five that always matter:

1. **Which function is the method?** "`irlba::irlba` directly, or
   `BiocSingular::runPCA(BSPARAM=IrlbaParam())`? They differ in centering
   defaults."
2. **Which arguments become plan `parameters`, and which are fixed?**
   "`n_components` and `random_seed` are clearly parameters. Is `solver` a swept
   axis (one arm per solver) or fixed at the upstream default? Is `n_threads` a
   parameter or taken from the stage's `resources.cores`?"
3. **What exactly goes in each declared output?** "The stage declares
   `loadings_tsv`. For this tool that would be the gene × component rotation —
   confirm? Genes in the first column, or as row names?"
4. **How does the input file map to the tool's object?** "The input is
   genes × cells CSC HDF5; the tool wants cells × genes dense. Transpose and
   materialise, or is there a sparse path?"
5. **What should happen on degenerate input?** "Fewer cells than requested
   components, an all-zero gene, a matrix that is normalized when the tool needs
   counts — fail loudly, or clamp and log?"

The full list, with the wording to use and why each one matters, is in
`references/interview-checklist.md`.

Two of the exemplars show what a good answer to question 5 looks like in code.
`scvi/dimred.py` refuses non-integer input rather than silently producing a
wrong embedding, because scVI's likelihood is negative-binomial over counts; the
error message names the fix (wire the module to a counts-passthrough
normalisation arm). `rcppml/src/rcppml.R` refuses `--backend gpu` when no GPU is
visible, instead of accepting the upstream's warn-and-fall-back-to-CPU, on the
grounds that "a CPU run recorded as a GPU arm is worse than a failed job". Both
are three or four lines. That is the right size for a guard.

## 4. Choose the entrypoint language to match the tool

Wrap an R package from R, a Python package from Python. Do not call R from
Python or vice versa to avoid learning the other language — the bridge is more
code than the wrapper, and it becomes the thing that breaks.

`ob create module` takes `--entrypoint run.R`, `run.py` or `run.sh`. A shell
entrypoint is for a tool that is genuinely a command-line binary; `run.sh` is
also how the exemplars add a profiling variant of an existing entrypoint
(`pca-prof: prof.sh pca.py`).

## 5. Scaffold

Let the tool write the boilerplate. With a plan and a stage, `ob` generates one
argparse flag per stage input for you:

```bash
ob create module my-tool-pca \
  --benchmark ../split-stages-plan/benchmark_conda.yaml \
  --for-stage PCA \
  --entrypoint run.R \
  --name "my-tool PCA" \
  --author-name "Your Name" --author-email "you@example.com" \
  --description "PCA stage arm backed by <upstream>" \
  --license MIT
```

| flag | why it matters |
| --- | --- |
| `--benchmark` | path or URL to the plan; required by `--for-stage` |
| `--for-stage` | generates `--<input_id>` argparse flags from the stage's `inputs` — the reason to pass a plan at all |
| `--entrypoint` | `run.R` \| `run.py` \| `run.sh`; picks the language pair it emits |
| `--license` | `MIT` \| `Apache-2.0` \| `GPL-3.0-or-later` \| `BSD-3-Clause` \| `CC0-1.0` |
| `--no-input` / `--non-interactive` | skip the prompts in a scripted run |

It emits `CITATION.cff`, `omnibenchmark.yaml`, `README.md`, `.gitignore`, the
entrypoint pair (`run.py` + `src/main.py`), `docs/`, `env/`, and runs `git init`.
Editing that scaffold in place beats replacing it. What still needs fixing by
hand — the `CHANGE_ME` URLs in `CITATION.cff`, the empty `env/` that should be
`envs/<name>.yml`, the missing `pixi.toml` and CI — belongs to the
`omnibenchmark-module` skill; this skill picks up at the entrypoint's body.

Note that `ob validate module` passes on a bare scaffold. It is a structural
check, not evidence the module works.

## 6. Write the adapter

Four parts, in this order, flat and linear. No classes, no helper layer, no
dependency injection — a biologist reading the diff should see what it does
without tracing indirection.

```
parse args   -> the generated flags, plus your method's parameters
read input   -> stage input file to the object the tool wants
call         -> the one upstream function
write        -> the declared output files, named exactly as the stage says
```

`rcppml/pca.R` is the whole shape in 35 lines of code, because its readers and
writers live in a shared `src/rcppml.R` used by both of its entrypoints:

```r
run_pca <- function(X, args) {
  fit <- RcppML::svd(X, k = args$n_components, center = TRUE,
                     method = args$solver, seed = args$random_seed,
                     resource = args$backend,
                     threads = omp_threads(), verbose = TRUE)
  list(embedding = fit@v %*% diag(fit@d, nrow = length(fit@d)),
       loadings  = fit@u)
}

main <- function() {
  log_args(args)
  load_rcppml()
  args$backend <- resolve_backend(args$backend)
  m <- read_tenx(args$normalized_selected_h5)
  res <- run_pca(m, args)
  rownames(res$embedding) <- colnames(m)
  rownames(res$loadings)  <- rownames(m)
  write_factors(res$embedding, res$loadings, args)
}
```

Things worth copying from it: `--solver` is handed straight to the upstream's
`method` argument so the upstream validates it and names the accepted set in its
own error; the row-name assignment is explicit because the output TSVs are keyed
by those ids; and the argument-to-argument mapping is visible on one screen.

Put the method in a small function (`run_pca`) that takes the matrix and the
parsed args and returns plain data. That is enough structure for a test to call
it directly, and it is the only structure the exemplars have.

More worked examples — what each one had to adapt and why — are in
`references/worked-examples.md`.

## 7. When the tool's output does not match the contract

Four moves, in order of preference:

1. **Reshape.** Usually the whole problem. `scrapper::runPca` returns
   `components` as k × cells, so the module transposes it and takes `rotation`
   as-is. Two lines.
2. **Rename to the stage's convention.** The `omni-scrna` PCA stage names
   columns `PC1..PCk`. The `rcppml` NMF arm and the `scvi` latent arm both keep
   `PC*` names for factors that are not principal components, so every
   downstream consumer and validator reads them unchanged — with a comment
   saying exactly that. Renaming is cheap; teaching four downstream stages a
   second convention is not.
3. **Write the declared file with the right shape and a value that fails
   loudly.** `scvi/dimred.py` must produce `loadings_tsv`, but scVI's decoder is
   a nonlinear MLP with no gene→factor map. It writes the correct shape filled
   with `NaN`, and documents in the module docstring that a consumer which
   genuinely needs loadings will fail on the numbers rather than silently using
   zeros. Never write zeros, and never skip a declared output.
4. **Change the contract.** Sometimes the honest answer is that the stage is
   wrong for this tool — the `scvi` module's docstring says so plainly ("a
   better option is to have a DIMR stage that takes raw inputs after
   qc/filtering"). That is a plan change: raise it with the benchmark author,
   do not work around it in the module.

If the mismatch is in the *input* — the tool needs something the stage does not
deliver — that is a guard, not an adaptation. Fail with a message naming the fix
(see the `scvi` counts guard in §3).

## 8. Pin the upstream version

The point of the module is to record *which* version of the tool produced the
numbers. Three routes, all in `pixi.toml`:

```toml
# conda / bioconda package, tight where the version changes results
[dependencies]
r-rcppml = ">=1.0.0"       # conda-forge stops at 0.3.7.1, which lacks svd()

# PyPI-only package, exact, with the reason for the distribution choice
[pypi-dependencies]
rapids-singlecell-cu13 = { version = "==0.16.1", extras = ["rapids"] }

# a git repo with no release: pin a rev, never a branch
omnibenchmark = { git = "https://github.com/omnibenchmark/omnibenchmark.git", rev = "071c56d98" }
```

`rev` rather than `branch` because two machines installing from a branch on
different days land on different commits — the plan manifest in
`omni-scrna/split-stages-plan` records exactly that having happened.

When the needed version is not on conda-forge, add the channel that has it and
put it **first** in `[workspace].channels` (channel order is precedence); the
`rcppml` module does this for `https://prefix.dev/almost-conductor`.

Belt and braces for a version that changes results silently: assert it at
runtime. `rcppml/src/rcppml.R` has a five-line `load_rcppml()` that stops if
`packageVersion("RcppML") < "1.0.0"`, with an error naming the channel to use.

### When upstream does not install cleanly

Some tools have no usable release: the PyPI wheel is broken, the setup
metadata pins something unsolvable, or the code needs a fix before it runs.
Try, in order: a `git` + `rev` pin (above) to a commit that works; relaxing
the offending pin via an extra `[dependencies]` entry; only then vendor.

To vendor:

1. Copy the upstream source at one commit into `vendor/<tool>/`, and put its
   `LICENSE` there with it. Check the licence permits redistribution first; if
   it does not, stop and tell the author.
2. Keep the fix as a separate file, `vendor/<tool>.patch`, applied on top and
   committed alongside, so a reviewer sees exactly what changed from upstream
   and the patch can be sent back. Do not edit the copy silently.
3. Record the upstream URL, commit and the reason in `vendor/README.md` — three
   lines. That is the version pin now, so it has to be as exact as a `rev`.
4. Import it from the repo (`sys.path.insert(0, <module root>/vendor)` in the
   entrypoint), and put the tool's own runtime dependencies in `pixi.toml`.
   The plan clones the module at its pinned commit, so vendored code travels
   with it. Do not route it through a local `path =` PyPI dependency: check the
   exported `envs/<name>.yml` never carries a path that only exists on your
   machine.

Say in the PR which route you took and why the cheaper ones failed.

Then export the environment and wire the module into the plan:

```bash
pixi run check          # do the imports work?
pixi run export-env     # regenerate envs/<name>.yml
```

```yaml
# in the plan's stage block, alongside the sibling modules
- id: pc-my-tool
  name: "my-tool PCA"
  software_environment: "my-tool"
  repository:
    url: https://github.com/<org>/my-tool-pca
    commit: <sha>
    entrypoint: pca
  parameters:
    - n_components: 50
      random_seed: 42
```

For the environment side see the `omnibenchmark-packaging` skill; for the plan
side, `omnibenchmark-plan`.

## 9. Land one increment at a time

A module that serves one stage correctly is mergeable. A module half-serving
four is not.

- **One entrypoint, finished, before the second.** If the tool covers PCA, kNN
  and clustering, port PCA, get it running against a real sample input, merge
  it. Then the next. The multi-entrypoint exemplars grew that way.
- **Write the invariants down and assert them where it is cheap.** The ones that
  earn their place encode the stage contract: output exists and is non-empty,
  row count equals the input cell count, column count equals `--n_components`,
  cell ids survive the transform. Those are what a reviewer cannot check by eye.
  A one-line `stopifnot` / `assert` next to the code it guards beats a test file
  elsewhere; the exemplars' `check.R` / `check.py` task is the other natural
  home.
- **Cover exactly that** — the contract and the degenerate cases the author
  named in step 3. This is not a licence to generate a test suite nobody asked
  for. A test encoding an invariant the author named is documentation; a test
  asserting a function returns what it just returned is noise.
- **Keep the diff reviewable in one sitting**, and end your report by saying
  what the next increment will be instead of doing it in the same change.

Run it once, by hand, against a real input before you call it done:

```bash
pixi run Rscript pca.R \
  --normalized_selected_h5 <sample>.h5 \
  --n_components 50 --random_seed 42 \
  --output_dir /tmp/myrun --name datasets
```

If the declared output files appear and the stage's validator passes on them,
the wrapper is done.

## References

- `references/interview-checklist.md` — the questions to put to the module
  author before writing code, with suggested wording.
- `references/worked-examples.md` — five exemplar wrappers read end to end:
  what each adapted, how large it is, and the one lesson each carries.
