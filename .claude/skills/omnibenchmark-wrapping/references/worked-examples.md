# Five wrappers, read end to end

All from the public `omni-scrna/split-stages-plan-modules` repo. All implement
the same stage (`PCA`): one HDF5 input, an embedding TSV and (in the later
arms) a loadings TSV. Comparing them is the fastest way to see what is
essential and what is incidental.

> These repos are legacy on the plan side (`api_version: "0.4.0"`, no
> `provides`/`requires`/`gather`). Read them for module structure and wrapper
> logic only; the plan contract's authority is design doc
> `004-yaml-specification.md` in `omnibenchmark/omnibenchmark`.

Sizes, measured (total lines / lines that are neither blank nor comment):

| module | entrypoint | total | code |
| --- | --- | --- | --- |
| `rcppml` | `pca.R` | 59 | 35 |
| `5-pca-truncatedsvd-sklearn` | `pca.py` | 75 | 55 |
| `5-pca-irlba-r` | `pca.R` | 92 | 58 |
| `scvi` | `dimred.py` | 151 | 115 |
| `scrapper` | `pca.R` | 158 | — |
| `rapids-singlecell` | `pca.py` | 185 | — |

The two shortest are the two that wrap the tool most directly. The longer ones
are longer for identifiable reasons — read on.

---

## 1. `5-pca-irlba-r` — the baseline shape

Wraps the CRAN package `irlba` (implicitly-restarted Lanczos, the algorithm
Seurat's `RunPCA` and BiocSingular's `IrlbaParam` both call underneath). The
module exposes the algorithm directly on the standardised stage input, without
Seurat's object scaffolding.

The whole method:

```r
Xt <- t(X)                          # stage input is genes x cells; PCA wants cells x genes
col_means <- Matrix::colMeans(Xt)
svd <- irlba::irlba(Xt, nv = args$n_components, center = col_means)
embedding <- svd$u %*% diag(svd$d)
```

Three things to notice:

- `center` is passed **as a vector argument** rather than by pre-centering the
  matrix, so the sparse matrix is never densified. That is a one-word decision
  with a large memory consequence, and the module records it in a header
  comment.
- The variance computation is done sparse-safe from row sums
  (`rowSums(X^2)`, `rowSums(X)`) rather than by materialising.
- `main()` prints the full command line and every parsed argument before doing
  anything. Every exemplar does this; it is what makes a failed benchmark run
  diagnosable from the log alone.

This module has **no vendored common code** — it sources a local `src/cli.R`.
It is the right starting point for a new port.

## 2. `rcppml` — thin because the shared parts moved out

Wraps `RcppML::svd`. The entrypoint is 35 lines of code because the reader,
writer, threading helper and version gate live in `src/rcppml.R`, shared with
the module's second entrypoint (`nmf.R`).

```r
fit <- RcppML::svd(X, k = args$n_components, center = TRUE,
                   method = args$solver, seed = args$random_seed,
                   resource = args$backend,
                   threads = omp_threads(), verbose = TRUE)
```

No transpose: `center = TRUE` subtracts *row* means, i.e. per-gene means, which
is the convention the sibling modules use, so the genes × cells input goes in
as-is and sparsity survives. With `A = u d v'`, scores are `v %*% diag(d)` and
loadings are `u` — the mirror of the cells-as-rows modules. Four comment lines
record this; without them the next reader would assume a bug.

Lessons:

- **Hand parameters straight to the upstream where you can.** `--solver` goes
  into `method` untouched, so RcppML validates it and names the accepted set in
  its own error. No enumeration to maintain in the wrapper.
- **Gate the version at runtime when a silent difference would change results.**
  `load_rcppml()` stops if `packageVersion("RcppML") < 1.0.0`, with an error
  naming the channel that provides it — conda-forge stops at 0.3.7.1, which
  predates `svd()` entirely.
- **Refuse rather than fall back.** `resolve_backend()` rejects `--backend gpu`
  when no device is visible, instead of accepting the upstream's
  warn-then-use-CPU. Also refuses the upstream's `"auto"`: it would pick a
  device from whatever the host happens to have, so the same invocation would
  mean different things on different machines.
- Extracting shared code into `src/` is worth it at the *second* entrypoint,
  not the first.

## 3. `5-pca-truncatedsvd-sklearn` — wrapping a Python class

```python
svd = TruncatedSVD(n_components=args.n_components,
                   algorithm=args.solver,
                   random_state=args.random_seed)
matrix = svd.fit_transform(adata.X).astype(np.float64, copy=False)
```

The interesting content of this module is not code, it is the docstring: it
explains why `TruncatedSVD` and not `PCA` (it runs on a sparse cells × genes
matrix without mean-centering, so it does not densify, and it is the one sklearn
decomposition the sibling scanpy module does not already dispatch to), and warns
that without centering the first component often picks up library-size
structure. It keeps the `PC*` column names anyway, for drop-in compatibility,
and says so.

Lesson: **the method-selection rationale is part of the deliverable.** A
benchmark arm whose reader cannot tell why that function was chosen is not
reviewable.

## 4. `scvi` — when the tool does not fit the stage

Wraps `scvi-tools`: `SCVI(adata, n_latent).train(...)` then
`get_latent_representation()`. It is longer than the others and every extra
block is a contract mismatch being handled honestly.

- **Input kind mismatch.** scVI's likelihood is negative-binomial over UMI
  counts, but the stage's only input is the normalized, selected matrix. The
  module guards: if the data are not integral it exits with a message telling
  the author to wire it to a counts-passthrough normalisation arm. Roughly six
  lines, and it prevents a silently wrong embedding.
- **Output with no natural value.** The stage declares `loadings_tsv`; scVI's
  decoder is a nonlinear MLP with no gene→factor map. The module writes the
  right shape filled with `NaN`, so a consumer that needs loadings fails on the
  numbers rather than using zeros. The docstring names the alternative
  (`scvi.model.LinearSCVI`) and says it is a different model, not a flag.
- **The stage is arguably wrong for this tool**, and the docstring says so: "a
  better option is to have a DIMR stage that takes raw inputs after
  qc/filtering". Raised, not worked around.
- **A genuinely new axis of variation.** Cell order changes minibatch
  composition, so SGD walks a different path — the module adds
  `--permutation_seed`, shuffles, and *undoes the permutation before writing* so
  the file is always in input order and the axis stays isolated to this stage.

Lesson: the extra length here is documentation and guards, not abstraction. That
is the kind of growth to accept.

## 5. `rapids-singlecell` — a GPU arm and a hostile dependency

Wraps `rapids_singlecell.pp.pca`. Two problems, both solved in the manifest and
in a lookup table rather than in control flow:

- **Distribution.** The package is PyPI-only; since 0.15 the plain
  `rapids-singlecell` dist is sdist-only, so installing it forces a from-source
  build of the CUDA extensions. The module takes `rapids-singlecell-cu13`
  (the prebuilt wheel, still imports as `rapids_singlecell`) pinned
  `==0.16.1`, and records in a manifest comment why not 0.14.1 (it imports a
  symbol cuML removed) and why no `cuda-version` pin is needed (the wheels
  bundle their own CUDA runtime).
- **Silent substitution.** `rsc` dispatches on input density *before* the
  solver and substitutes silently. The module keeps a five-entry `SOLVERS` dict
  mapping each `--solver` value to `(rsc svd_solver, valid density)` and raises
  on a mismatch, so a run cannot report a solver it did not use. There is no
  `"auto"`: the solver is always explicit, so the run is identifiable from its
  invocation line.

Lesson: when the upstream is willing to quietly do something other than what you
asked, the wrapper's job is to make that impossible. A dict plus one raise, not
a framework.

---

## What all five have in common

- One function is the method; it is called once, from a small function that
  takes the matrix and the parsed args and returns plain data.
- The full command line and every parsed argument are printed at start-up.
- Output filenames are built as `{output_dir}/{name}_<declared>.tsv` from the
  two arguments Omnibenchmark always passes.
- Ids are attached explicitly (`rownames(embedding) <- colnames(X)`), because
  the output tables are keyed by them.
- Every non-obvious choice — centering, orientation, read path, solver
  behaviour, why this function and not that one — is a comment on the line it
  explains.
- None of them has a class hierarchy, a config object, a logging framework, a
  retry loop, or a try/except blanket.
