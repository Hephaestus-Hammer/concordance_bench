# Worked example: scanpy PCA

The module is `omni-scrna/scanpy`, entrypoint `pca`, at commit `7827695`. The
run used linux-64 x86_64 (AMD Zen 4) on 2026-09-30, first with `ob` 0.6.0
(plan at `api_version: "0.4.0"`) and then with the 0.7.0 release (plan at
`"0.7.0"`, the template in SKILL.md §4). Both gave the same verdict, and the
two versions' outputs for the same parameter hash were byte-identical. A
0.7.0 replicate takes about a minute once the conda environment exists.

## Audit (§1)

```
source                       where                               controlled?
sklearn/ARPACK random_state  sc.pp.pca(random_state=seed)        yes: --random_seed, required
BLAS threads (OpenBLAS)      threadpool_limits(--blas_threads)   yes: 0 = inherit OMP_NUM_THREADS
solver substitution          sparse + randomized -> arpack       guarded for full; randomized
                                                                 silently becomes arpack (docstring)
output writer                polars write_csv, ids from h5       deterministic, no metadata
by-products                  obkit-events.jsonl, *_performance   per-run, excluded by --include
```

No code change was needed. The seed and the thread count were already exposed.

## Setup (§3–4)

- `pixi workspace export conda-environment --from-lock-file --platform linux-64`
  gave 157 lines of `pkg ==version build` pins, including
  `libopenblas 0.3.32 pthreads`.
- Input was a fixture module copying `rapids-singlecell/tests/data/datasets_normalized_selected.h5`
  (3,779 cells × 2,000 genes, sparse). The PCA stage's output ids came from
  `split-stages-plan`, with the templates rewritten from `{dataset}_…` to
  `{name}_…` for 0.7.0.
- Arms: `arpack` sparse, `full` dense, and `randomized` dense, each with seeds
  {1, 2}, and `blas_threads: [1, 4]` on the two dense arms. That is 10 PCA jobs
  per replicate.

## Results (§5)

| comparison | result |
| --- | --- |
| rep1 vs rep2, all arms and thread counts | 21/21 IDENTICAL (incl. the input `.h5`) |
| `full` seed 1 vs 2 | IDENTICAL → seed-inert, correct for an exact solver |
| `arpack` seed 1 vs 2 | embedding IDENTICAL, loadings CLOSE `max_abs=4e-14` → effectively seed-inert (the seed only sets ARPACK's start vector) |
| `randomized` seed 1 vs 2 | DIFFERENT `max_abs=7.7 max_rel=2` → seed-live, with sign flips |
| `blas_threads` 1 vs 4 (`full`, `randomized`) | embedding IDENTICAL, loadings CLOSE `max_abs≈2.5e-14` |
| same hash, `ob` 0.6.0 vs 0.7.0 | byte-identical |

**Tier: B** at a fixed thread count (tested 1 and 4), C across thread counts.
The thread effect (1e-14) is 14 orders of magnitude below the seed effect of
the randomised arm (7.7), so for any downstream metric the thread count is
irrelevant. Not tested: osx-arm64, MKL, and cross-machine runs (A tier).

## What went wrong on the way, and is now in the skill

1. **Under 0.6.0, the thread test first passed without testing anything.** Replicate 3 used
   a copy of the plan with `resources.cores: 1` in place of 4, and it came out
   IDENTICAL to replicate 1. But neither generated Snakefile had a `threads:`
   directive, so both ran with `OMP_NUM_THREADS=1`. `mean_load` in
   `*_performance.txt` (70% in both) showed it. The fix was to sweep the
   module's `--blas_threads` as a parameter; load then rose to 242% at 4
   threads. 0.7.0 does emit `threads:` from `resources.cores`, but the
   parameter sweep stays the method: it puts both counts in one run, and the
   load check stays mandatory.
2. **Unfiltered comparisons are useless.** `compare_runs.py rep1 rep2`
   without `--include` reports 39 DIFFERENT files (timings, obkit event
   logs, Snakemake logs, metadata) and 58,242 MISSING (the conda environment
   Snakemake built inside the first out-dir). None of them is a result.
   Compare `rep*/DATA` with `--include` set to the declared outputs.
3. **`--dirty` is required** for local-path modules, even clean ones.
4. **Template/`api_version` mismatch.** The first draft of the skill's
   template declared `api_version: "0.7.0"` with `{dataset}_…` paths. Against
   this module, which writes `<--name>_…`, that is a missing output. At 0.7.0
   the template is `{name}_…`.
