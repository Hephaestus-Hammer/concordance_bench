---
name: omnibenchmark-reproducibility
description: "Check that one Omnibenchmark module is deterministic, and give it a reproducibility tier (A to D). Audit the module and its upstream tool for sources of variation it could control (RNG seeds, thread counts, BLAS/MKL settings, GPU nondeterminism, hash and file ordering, timestamps written into outputs). Expose what is missing as `--random_seed` or a thread setting. Then build a small benchmark plan that runs the module as same-seed replicates and different-seed arms, and compare the output trees file by file. Load this when asked whether a module is reproducible or deterministic, why two runs differ, whether a seed is actually used, how to certify or tier a module's reproducibility, or before publishing results that depend on a stochastic method."
---

# Reproducibility of a module

The claim under test is narrow. **Given a fixed environment and a fixed seed, two
runs with the same inputs write byte-identical outputs, and changing the seed
changes them.** A seed only guarantees results for the triple

```
(environment, seed, platform)
```

where *environment* means a locked conda environment (not a re-solved one),
and *platform* means OS, CPU architecture and instruction set, BLAS vendor,
GPU model and driver. The same seed can give different numbers on another
platform. That is normal. The tier records which parts of the triple a module's
results survive changing.

## Tiers

| tier | the claim | evidence required |
| --- | --- | --- |
| **A** | Identical across platforms | Same-seed replicates byte-identical on ≥ 2 distinct platforms (e.g. `linux-64` x86 and `osx-arm64`, or two CPU vendors), same lock |
| **B** | Identical on one platform | Same-seed replicates byte-identical on one platform. Record the triple and thread count |
| **C** | Variance reduced | Same-seed replicates are not identical but `CLOSE`, and their spread is clearly smaller than the spread across seeds |
| **D** | No control | Same-seed replicates spread as widely as different seeds, or the module has no way to set a seed |

Qualifiers that belong with the tier:

- **`@threads=N`** if results change with the thread count. B at one thread
  count and C across counts is common for BLAS and OpenMP reductions. Write
  `B@threads=1, C across threads`.
- **`seed-inert`** if different seeds give identical outputs. Either the method
  is deterministic (fine; say so, and A/B still apply) or the seed is not
  reaching the RNG, which is a bug. The audit (§1) tells you which.
- **Upstream-limited** if the variation comes from an upstream library the
  module cannot control, such as nondeterministic cuDNN kernels. Name the
  library.

The tiers are a proposal. Where the certificate is recorded and who grants it
are open questions (`docs/ROADMAP.md`). Until those are settled, record the
result in the module README (§6).

## Order of operations

1. Audit the code for sources of variation it could control.
2. Expose the missing controls as CLI flags, with the author's agreement.
3. Lock the environment.
4. Write the reproducibility plan: small input, a seed axis, the module under test.
5. Run replicates and compare.
6. Assign the tier and record it.

## 1. Audit

Read the module's entrypoint **and the upstream calls it makes**. Most hidden
randomness is in upstream defaults, not in the module. Build a table like this
one before changing anything:

```
source                       where                          controlled?  how
numpy global RNG             src/main.py:40 np.random.*     no           Generator(seed) passed down
sklearn random_state         TruncatedSVD(...)              no           random_state=args.random_seed
BLAS threads (OpenBLAS)      implicit in fit_transform      no           OPENBLAS_NUM_THREADS from resources.cores
PYTHONHASHSEED               set iteration in build_groups  no           sorted() instead of set order
gzip mtime in output         write_tsv(..., .gz)            no           GzipFile(..., mtime=0)
```

The full checklist is in `references/audit-checklist.md`, by language and
library: Python, R, BLAS/OpenMP, GPU, I/O and output metadata. These cause
most failures:

- **An upstream default of `random_state=None`** (sklearn, umap-learn,
  leidenalg, igraph). Each run is seeded from the OS, and nothing in the
  module's code shows it.
- **A global RNG seeded once while a library draws from its own RNG.**
  `np.random.seed` does not seed `random`, torch, or a `Generator` an upstream
  library creates internally. In R, `set.seed` does not cover parallel workers
  unless `RNGkind("L'Ecuyer-CMRG")` or the BiocParallel/future seed mechanism
  is used.
- **Threaded floating-point reductions.** Summation order changes with the
  thread count, and with dynamic scheduling it can change between runs at the
  same thread count.
- **Output metadata.** Timestamps, hostnames, absolute paths or package
  versions written into the file itself: a gzip header, AnnData `uns`, RDS
  attributes, a PDF creation date. These are a D-tier *file* around a B-tier
  *result*. Fix the writer rather than excluding the file.

## 2. Expose the controls

Ask first, as with any change to a module's CLI (`omnibenchmark-wrapping`,
interview question 2). The conventions:

- **`--random_seed`** (int, `required=True`) is the one seed flag. Derive every
  RNG the module uses from it, including an upstream `random_state`, torch,
  R's `set.seed`, and a permutation seed. If the method needs two independent
  streams, derive them from `--random_seed` (e.g. `np.random.SeedSequence(seed).spawn(2)`)
  instead of adding a second flag. The exception is a deliberately separate
  axis such as `scvi`'s `--permutation_seed`.
- **A thread flag with an "inherit" default.** The scanpy module has
  `--blas_threads` (0 = inherit `OMP_NUM_THREADS`), which wraps the call in
  `threadpoolctl.threadpool_limits(n)`. Production runs leave it at 0 and
  inherit from the scheduler. The reproducibility plan sweeps it (§5). Without
  the flag, the thread axis cannot be tested at all, because `resources.cores`
  does not reliably reach the process (§5, step 4). Put shared helpers in the
  module's `src/`, as `rcppml`'s `omp_threads()` is.
- **Log what was actually used.** At startup, print the seed, the thread count,
  the BLAS vendor (`numpy.show_config()`, `sessionInfo()`) and whether the
  chosen solver consumes the seed at all (the `rapids-singlecell` `SEEDED`
  set). Tiering a module from its logs is far cheaper than re-running it.

A seed that makes the output byte-identical should not need a tolerance. If
you find yourself adding rounding to outputs to get identical files, stop. That
hides the variation instead of controlling it, and the result is C tier.

## 3. Lock the environment

`envs/<name>.yml` exported from the manifest is a constraint file, not a lock.
Conda re-solves it, so two runs a month apart can get different package builds.
For any tier above D, export from the lock:

```bash
pixi workspace export conda-environment --from-lock-file --platform <platform> \
  --name <env> envs/<name>.repro.yml
```

The flags and their caveats are in `omnibenchmark-packaging` §3. Record the
`pixi.lock` commit sha with the tier. It is the *environment* part of the triple.
Cross-platform (A-tier) runs need one export per platform from the same lock.

## 4. The reproducibility plan

This is a separate, small plan. Do not reuse the real benchmark. It exists only
to test this module and should run in minutes.

- **Input:** one small but realistic dataset, fed in by a **fixture module**:
  a local git repo holding the file and a `run.sh` that copies it to
  `$output_dir/${name}_<suffix>`. It is deterministic by construction and
  removes every upstream stage from the question. Use the stage input the
  real benchmark feeds the module, e.g. an existing `tests/data/` file of a
  sibling module. Stochastic behaviour can be absent at toy sizes, because
  solvers take exact paths below a threshold (e.g. sklearn's
  `svd_solver="auto"`). Check the input is big enough to reach the code path
  the real benchmark uses.
- **The module under test:** a clean `git clone` of it at the commit being
  certified, referenced by local path. `ob run` refuses local paths without
  `--dirty`. That is safe here because both repos are clean clones at pinned
  commits, and the tier record names the commit.
- **Output templates must match what the module writes.** At
  `api_version: "0.7.0"` `--name` is the module's own id, so a module that
  writes `<name>_x.tsv` needs `path: "{name}_x.tsv"`. A `{dataset}_x.tsv`
  template (the 0.4.0 habit) makes the run fail on a missing output rather
  than test anything. Keep the output ids of the real plan's stage. See
  `omnibenchmark-plan`, "check `api_version`".
- **Seed axis:** `random_seed: [1, 2]` on the module under test. The two seeds
  get two parameter hashes, so both arms are in one run.
- **Solver axis:** if the module has several solvers, include each one
  with both seeds. Tiers are per arm, since exact solvers are seed-inert and
  randomised ones are not.
- **Thread axis:** the module's own thread flag, e.g. `blas_threads: [1, 4]`,
  on the arms that do BLAS work. Two counts get two hash directories in the
  same run. `resources.cores` is not in the hash, so a sweep over it cannot be
  compared within one run.
- **Replicates come from separate out-dirs, not from the plan.** Identical
  parameters hash to the identical path, and Snakemake will not re-run a
  finished job. Do not add a dummy `replicate:` parameter: the module's parser
  would reject it, and it pollutes the path hash.

```yaml
id: repro_pc_scanpy
version: "0.1.0"
api_version: "0.7.0"
benchmarker: "Name <name@example.org>"
software_backend: conda
software_environments:
  scanpy: { name: scanpy locked linux-64, conda: envs/scanpy.repro.yml }
stages:
  - id: DATA
    outputs:
      - { id: normalized_selected_h5, path: "{name}_normalized_selected.h5" }
    modules:
      - id: fixture
        software_environment: scanpy
        repository: { url: /abs/path/fixture-data, commit: <sha> }
  - id: PCA
    resources: { cores: 4 }         # ob 0.7.0 turns this into threads: 4
    inputs: [normalized_selected_h5]
    outputs:
      - { id: embedding_tsv, path: "{name}_embedding.tsv" }
      - { id: loadings_tsv,  path: "{name}_loadings.tsv" }
    modules:
      - id: pc-scanpy
        software_environment: scanpy
        repository: { url: /abs/path/scanpy, commit: <sha>, entrypoint: pca }
        parameters:
          - { solver: arpack,     dense: "false", n_components: 50, random_seed: [1, 2], blas_threads: 1 }
          - { solver: full,       dense: "true",  n_components: 50, random_seed: [1, 2], blas_threads: [1, 4] }
          - { solver: randomized, dense: "true",  n_components: 50, random_seed: [1, 2], blas_threads: [1, 4] }
```

The fixture's `run.sh`:

```sh
#!/bin/sh
while [ $# -gt 0 ]; do case "$1" in --output_dir) out=$2; shift 2;; --name) name=$2; shift 2;; *) shift;; esac; done
mkdir -p "$out" && cp "$(dirname "$0")/data.h5" "$out/${name}_normalized_selected.h5"
```

Do not use `ob run -m`. It keeps only the first parameter expansion, which
drops the second seed. For plan grammar, see `omnibenchmark-plan`.

## 5. Run and compare

```bash
ob run repro.yaml --dirty --cores 4 --out-dir rep1
ob run repro.yaml --dirty --cores 4 --out-dir rep2
C=skills/omnibenchmark-reproducibility/scripts/compare_runs.py
OUT="--include *_embedding.tsv --include *_loadings.tsv --include *.h5"   # declared outputs

python3 $C rep1/DATA rep2/DATA $OUT                       # replicates
cd rep1/DATA/fixture/.default/PCA/pc-scanpy && ls         # one symlink per combination
python3 $C blas_threads-1_..._random_seed-1_solver-randomized \
           blas_threads-1_..._random_seed-2_solver-randomized $OUT   # seed 1 vs seed 2
```

`ob` 0.7.0 puts a readable symlink next to each hash directory, named after
its parameters (`blas_threads-1_dense-true_n_components-50_random_seed-1_solver-full
-> .6687eaa2`). Compare through those. `compare_runs.py` does not follow them
when walking a tree, so they are never counted twice. Every hash directory
also has a `parameters.json`. Hashes are stable across `ob` versions: the same
combination got the same hash, and byte-identical output, under 0.6.0 and
0.7.0.

**Always pass `--include` with the declared outputs.** Next to them, `ob` and
the module write per-run files that are guaranteed to differ:
`performance.txt` (Snakemake benchmark timings; `<name>_performance.txt`
before 0.7.0), `obkit-events.jsonl`, `.logs/`, `.metadata/`, `Snakefile`, and
the conda environment under `.snakemake/`. Without `--include` every
replicate looks `DIFFERENT`.

`compare_runs.py` pairs files by relative path. It prints `IDENTICAL`, `CLOSE`
(text tables within `--rtol/--atol`), `DIFFERENT` (with the largest absolute
and relative difference), or `MISSING`. It exits 0 when everything is
identical, 3 when the worst is close, and 1 when anything differs or is
missing (2 is argparse's usage error). It needs only the standard library.

Read the result in this order:

1. **Upstream outputs differ between rep1 and rep2** → the test is not valid
   yet. Fix or replace the upstream module, then re-run. With a fixture
   module this cannot happen.
2. **Module outputs between rep1 and rep2**: `IDENTICAL` is a B candidate,
   `CLOSE` is C, and `DIFFERENT` means go back to §1.
3. **Seed 1 vs seed 2**: `DIFFERENT` means the seed is live. `IDENTICAL` (or
   `CLOSE` at ~1e-14) means `seed-inert`, and the audit decides whether that
   is correct or a bug. For C, compare the size of the differences: the
   replicate `max_abs` should be orders of magnitude below the seed-to-seed
   `max_abs`. **`max_rel=2` means a sign flip**: some value is `x` on one
   side and `-x` on the other. With SVD/PCA, that is the component sign.
4. **Threads.** Compare the `blas_threads-1_…` and `blas_threads-4_…`
   directories of one run. rep1 vs rep2 already covers B at each count.
   **Confirm the count actually changed**: the `mean_load` column (%, 9th) of
   `performance.txt` should rise with the threads. That is a clear signal
   only for arms dominated by BLAS; the scanpy `full` arm went from ~85% to
   ~216%, while the short `randomized` arm stayed under 100% either way. Do not
   rely on `resources.cores` alone. `ob` 0.7.0 emits `threads:` from it, but
   0.6.0 did not, and Snakemake then left `OMP_NUM_THREADS=1`. A module
   without a thread flag gets one (§2) before it can be tiered across
   threads.
5. **Platform** (A only): run the same plan with the same-lock export on a
   second platform (`rep_osx`), then compare `rep1` with `rep_osx`.

Binary outputs (`.h5`, `.h5ad`, `.rds`) are reported as `DIFFERENT` whenever
their bytes differ, and embedded metadata often causes that. Before accepting
a lower tier, compare their contents with a format-aware tool
(`h5diff`, `all.equal(readRDS(a), readRDS(b))`). If the contents match, the
fix is in the writer (§1). Eigen/SVD sign flips across platforms are real
differences under A. Canonicalise the sign in the module (e.g. largest
loading positive) if the stage contract allows it; that is a legitimate fix.

A full worked run, the scanpy PCA module, is in `references/worked-example-scanpy.md`.

## 6. Record it

Add this to the module README. It is short and complete, and it says what was
*not* tested:

```markdown
## Reproducibility

Tier **B** at blas_threads 1 and 4 (C across thread counts: loadings ~1e-14).
- arms: randomized seed-live; arpack and full seed-inert (exact solvers)
- env: pixi.lock @ <sha>, exported --from-lock-file for linux-64, OpenBLAS 0.3.32
- platform: linux-64, x86_64 (AMD Zen 4)
- test: repro plan @ <sha>, 2 replicates x seeds {1,2} x solvers, ob 0.7.0, 2026-09-30
- not tested: osx-arm64, MKL, GPU
```

A later change to the lock, the upstream pin, or the module's numerical code
invalidates the tier. Re-run §5 and update the record in the same PR.

## References

- `references/audit-checklist.md`: sources of variation by language and
  library, and how to control each one.
- `references/worked-example-scanpy.md`: the whole procedure on a real
  module under `ob` 0.7.0, including the thread test that looked like it passed
  under 0.6.0 but hadn't.
- `scripts/compare_runs.py`: run-tree comparison (`--selftest` checks the script
  itself).
