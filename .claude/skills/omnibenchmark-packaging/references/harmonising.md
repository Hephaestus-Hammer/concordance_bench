# Harmonising a new module against the existing environments

The question this answers: *I am adding a module to a benchmark that already has
a dozen. Which of my pins should match my neighbours, and which are mine to
choose?*

## The two rules

1. **Modules do not co-solve.** Each `software_environments` entry is its own
   conda environment. Your `numpy` bound cannot break another module's solve.
2. **Comparability is not solvability.** A benchmark comparing two
   implementations of a method must not accidentally be comparing two versions
   of the shared I/O stack. Anything that touches the benchmark's shared file
   formats, readers, writers or instrumentation should carry the *same*
   constraint as the sibling modules, even though nothing forces it to.

The exemplars apply rule 2 by hand, with the reason in a comment. From
`rapids-singlecell/pixi.toml` in `omni-scrna/split-stages-plan-modules`:

```toml
# Same pin as the scanpy module: the TSV writers are the same code in both, so
# they must be the same polars (see src/writers._write_tsv).
polars = ">=1,<2"
```

and from `scvi/pixi.toml`:

```toml
obkit = ">=0.0.3, <0.0.4"   # phase logging, same pin as the rapids module
```

## The surveyed constraint table

Every dependency appearing in two or more of the thirteen exemplar module
manifests, with the spec each module uses. Read it before you invent a pin.

| dependency | modules | specs in use |
| --- | --- | --- |
| `r-base` | 6 | `>=4.5` (irlba, metrics, seurat) · `>=4.5,<4.6` (biocsingular, rcppml) · `>=4.5.3,<4.6` (9-annotate) |
| `bioconductor-rhdf5` | 6 | `*` (irlba, metrics, biocsingular, rcppml, seurat) · `>=2.54.1,<3` (9-annotate) |
| `python` | 6 | `>=3.14.4,<3.15` (sklearn, scanpy) · `>=3.14,<3.15` (scvi) · `>=3.13,<3.14` (rapids) · `>=3.12,<3.14` (metrics) · `>=3.11` (cookbook) |
| `bioconductor-hdf5array` | 5 | `*` (irlba, biocsingular, rcppml, seurat) · `>=1.38.0,<2` (9-annotate) |
| `polars` | 5 | `>=1,<2` (sklearn, rapids, scanpy, scvi) · `*` (metrics) |
| `r-argparser` | 5 | `*` (metrics, biocsingular, rcppml, seurat) · `>=0.7.1,<1` (9-annotate) |
| `r-data.table` | 5 | `*` (metrics, biocsingular, rcppml, seurat) · `>=1.17.8,<2` (9-annotate) |
| `r-matrix` | 4 | `*` (irlba, biocsingular, rcppml) · `>=1.7_5,<2` (9-annotate) |
| `h5py` | 4 | `>=3.16.0,<4` (sklearn, scanpy) · `>=3.16,<4` (scvi) · `*` (metrics) |
| `numpy` | 4 | `>=2.4.3,<3` (sklearn, scanpy) · `>=2.5,<3` (scvi) · `<2.5` (metrics) |
| `r-jsonlite` | 4 | `*` (metrics, biocsingular, rcppml) · `>=1.8.0,<3` (9-annotate) |
| `anndata` | 3 | `>=0.12.11,<0.13` (sklearn, scanpy) · `>=0.13,<0.14` (scvi) |
| `scipy` | 3 | `>=1.17.1,<2` (sklearn, scanpy) · `>=1.17,<2` (scvi) |
| `bioconductor-delayedarray` | 2 | `*` (irlba, biocsingular) |
| `r-optparse` | 2 | `*` (irlba, seurat) |
| `scikit-learn` | 2 | `>=1.5,<2` (sklearn) · `*` (metrics) |
| `pyyaml` | 2 | `*` (cookbook, metrics) |
| `bioconductor-anndatar` | 2 | `>=1.0.2,<2` (datasets) · `*` (seurat) |
| `r-yaml` | 2 | `*` (metrics, seurat) |

PyPI side: `obkit = ">=0.0.3, <0.0.4"` in three modules (`scanpy`,
`rapids-singlecell`, `scvi`) — that one is a genuine house constant; match it.

## Reading the table

The stack is **not** fully harmonised today, and the divergences are
informative rather than accidental:

- `numpy` spans `<2.5` (metrics), `>=2.4.3,<3` (scanpy/sklearn) and `>=2.5,<3`
  (scvi). `metrics` and `scvi` are mutually unsatisfiable. That is fine because
  they are separate environments — but it does mean the two could not be merged
  into one env without resolving it, and the `metrics` cap is documented in the
  manifest as an upstream numba limitation to retry later.
- `python` spans 3.12→3.15 for the same reason: `rapids` is held at 3.13 by its
  CUDA wheels, `metrics` at <3.14 by numba, and everything else runs 3.14.
- The R modules' `*` specs mean "whatever bioconductor's current release set
  gives me", which is coherent per solve but not pinned across time.

## Procedure for a new module

1. List the dependencies your entrypoint actually imports. Nothing else.
2. For each one, look it up in the table above.
   - **In the table, and it touches shared I/O or instrumentation** (`polars`,
     `h5py`, `anndata`, `obkit`, `r-data.table`, `bioconductor-rhdf5`,
     `bioconductor-hdf5array`, the CLI-helper packages `r-argparser`/`r-jsonlite`):
     use the same spec as the sibling modules, and say in the commit message
     that you matched it.
   - **In the table, but it is your method's own stack** (`scikit-learn` for an
     sklearn wrapper, `r-irlba` for irlba): pin it as tightly as the result
     demands, independently.
   - **Not in the table**: it is new to the benchmark. Pin both bounds and
     comment what it is for.
3. If a matched spec does not solve with your method's stack, do not silently
   loosen it — that would break the comparability the match was for. Either cap
   the conflicting package with a comment naming the cause (the `metrics`
   pattern), or raise it: a shared writer that cannot run at the same polars in
   two arms is a real finding about the benchmark, not a packaging annoyance.
4. Re-solve, `pixi run check`, `pixi run export-env`, commit all three files.

## When the environment really is shared

Some plan environments serve several modules (in
`omni-scrna/split-stages-plan`, the `scanpy` and `scrapper` environments each
back multiple entrypoints). There, constraints genuinely do co-solve, and a bump
changes every arm that uses the environment. Two consequences:

- Re-run every entrypoint in the environment after a bump, not just the one you
  were working on.
- Say in the PR which arms are affected. A dependency bump that silently changes
  four arms of a published benchmark is exactly the kind of change reviewers
  need flagged.

## Checking your work

```bash
pixi install                 # solve
pixi run check               # imports + version gates
pixi run export-env          # regenerate envs/<name>.yml
diff -u envs/<name>.yml ../<plan-checkout>/envs/<name>.yml   # plan-side copy in sync?
```

The last line matters: in `omni-scrna/split-stages-plan` the plan-side copies
have drifted from the module exports (different bounds, an extra channel, a
`pip:` block flattened), and only six of eighteen plan env files carry the pixi
banner at all. The plan-side copy is a manual step; treat it as part of the
change, not as somebody else's problem.
