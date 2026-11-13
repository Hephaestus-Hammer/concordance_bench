# Phase 2 plan

Agreed with Ben on 06/11, after Phase 1 and his deck *Post-leaderboard evaluation of
single-cell clustering pipelines* (Sept 2026). Phase 1 stays frozen as it is; Phase 2 is
a new plan file and a new report.

## Where Phase 1 left us

On Hao 2021 (10k, 50k, 100k cells), with exact baselines and 20 seeds per seeded stage:

- **PCA** made no difference: subspaces agree to about 10⁻⁷ degrees, and changing the
  arpack seed leaves every downstream result identical.
- **kNN**: exact search agrees across CPU and GPU (99.98% of neighbourhoods). The
  approximate search (pynndescent) drifts further with size, but stays within its own
  seed noise.
- **Leiden** is where results diverge. GPU Leiden (cuGraph, through rapids) differs from
  both CPU implementations by more than either one's own seed noise, at every size; it
  reaches lower modularity, finds fewer clusters, and is not fully reproducible at a
  fixed seed (same-seed ARI down to 0.90 at 50k).

Phase 1 varied only *which library* runs each stage. Phase 2 widens what varies, adds
datasets, and scores every pipeline on accuracy, stability and cost.

## Questions

1. Which pipelines (PCA solver × kNN method × Leiden implementation) give the best
   accuracy, stability and cost, and how does that change with the number of cells?
2. When is a GPU worth it, measured: at what size does a rapids stage reach an answer
   faster without losing accuracy or stability?
3. Is PCA really irrelevant, or did Phase 1 only use solvers that cannot vary?

## Experiment

### What varies

One stage at a time against fixed exact baselines, plus a small cross, so every
difference can be attributed to one stage and the grid stays affordable.

Plan file: `benchmark-phase2.yaml`. Module ids in brackets.

| Stage | Exact | Approximate, seeded (5 seeds) |
|---|---|---|
| PCA | covariance-eigh: CPU baseline [pc-baseline], GPU [pc-rapids]; Jacobi, GPU, dense input [pc-rapids-jacobi] | arpack, scanpy's default [pc-scanpy]; **randomized** CPU [pc-randomized] and GPU [pc-rapids-randomized]; **Lanczos** CPU [pc-lanczos] and GPU [pc-rapids-lanczos] |
| kNN | sklearn brute force, CPU [nn-baseline]; cuVS brute force, GPU [nn-rapids] | pynndescent on 1 thread, scanpy's default [nn-scanpy]; **pynndescent on 8 threads** [nn-scanpy-mt] |
| Leiden | — | leidenalg [cl-baseline], igraph [cl-scanpy], cuGraph [cl-rapids], each at **resolutions 0.05, 0.2, 0.5, 1, 2** |

Every approximate PCA method has a CPU and a GPU implementation, so CPU against GPU is
compared method for method. The CPU randomized and Lanczos solvers are new in the fork
(patch 1): scanpy used to turn `randomized` into arpack silently on sparse input.

Hypothesis for PCA: Phase 1 saw no variability because every solver was exact, not
because PCA cannot vary. Ben's deck shows two exact solvers differing by up to 0.098 ARI
on aifi-d1 (likely near-equal eigenvalues around PC 50 on that dataset), so it may also
depend on the dataset; the new datasets test both.

The kNN mismatch (scanpy stored 15 neighbours on its pynndescent path, 14 on its exact
path) is fixed in the fork: every module now stores 14. Leiden's connectivities were
always built from 14 on every path, so no Phase 1 clustering is affected.

### Slices

5 seeds per seeded module for now (more is a change to the plan's seed lists).

| Slice | Upstream | Varies | Jobs per dataset × size | All 23 dataset × size combinations |
|---|---|---|---|---|
| `slice-cluster` | exact PCA, exact kNN | 3 Leiden × 5 resolutions × 5 seeds | 78 | 1,799 |
| `slice-knn` | exact PCA | 4 kNN modules and their seeds → baseline Leiden, seed 0, 5 resolutions | 74 | 1,707 |
| `slice-pca` | — | 8 PCA modules and their seeds → exact kNN → baseline Leiden, seed 0, 5 resolutions | 197 | 4,536 |
| `pipelines/` | — | 5 named end-to-end pipelines × 5 matched seeds, Leiden at 5 resolutions | — | 3,455 |

The three slices vary one stage against the exact baselines, so every difference is
attributed to one stage: they feed the PCA, kNN and Clustering tabs of the report. The
pipelines slice runs whole pipelines, seed *i* at every seeded stage (what re-running a
pipeline with a new seed means), and feeds the Full pipeline tab:

| Pipeline | PCA | kNN | Leiden |
|---|---|---|---|
| baseline | covariance-eigh (CPU) | brute force (CPU) | leidenalg |
| scanpy-defaults | arpack | pynndescent, 1 thread | igraph, 2 iterations |
| tuned-cpu | randomized (CPU) | pynndescent, 8 threads | leidenalg |
| all-gpu | covariance-eigh (GPU) | brute force (GPU) | cuGraph |
| hybrid | covariance-eigh (GPU) | brute force (GPU) | leidenalg |

Counts from `scripts/make_filters.py` (`pixi run filters`), which writes the filters
(`filters/phase2/`) and matches ob's dry run; jobs shared between slices run once. Every
Leiden runs at all 5 resolutions, so oracle resolutions are picked in the analysis
afterwards, without a second round of runs. `--sizes in-10k in-50k in-all` builds the same
filters on fewer sizes; each stage slice also has a `-cpu` variant without the rapids modules.

### Datasets

Ben's four, so results are directly comparable with his, plus Hao. Sources, label
provenance and the one preprocessing recipe: `docs/datasets.md`.

| Dataset | Cells | Subsample sizes |
|---|---|---|
| pancreas | 12,115 | 5k, 10k, whole |
| tm-facs (Tabula Muris) | 44,104 | 5k, 10k, 25k, whole |
| tm-droplet (Tabula Muris) | 54,865 | 5k, 10k, 25k, 50k, whole |
| Hao 2021 PBMC (sc-brrr 100k rung) | 100,000 | 5k, 10k, 25k, 50k, 100k |
| aifi-d1 | 149,737 | 5k, 10k, 25k, 50k, 100k, whole |

Each dataset is published once, preprocessed the same way (`scripts/publish_dataset.py`),
and subsampled in nested, label-stratified steps (`modules/dataset_input.py`): one input
module per size, and a size larger than a dataset excludes it. So cell number varies
*within* a dataset; comparing sizes across datasets would confound size with tissue,
technology and label quality.

### Replicates

- **Node pinning**: all replicates of one comparison on the same node and GPU model,
  so they measure run-to-run noise, not hardware.
- **Stage-level replicates**: re-run one stage on the *same* upstream file, rather than
  recomputing the whole pipeline. Otherwise a Leiden replicate also carries any
  run-to-run noise from its kNN (multithreaded pynndescent will have some). Where
  whole-pipeline replicates are used, a replicate counts as one stage's own only if its
  upstream output is byte-identical (checked by hash).

## Metrics

The report is organised by stage. Each stage tab (PCA, kNN, Clustering) has the same four
subtabs, read from its slice; the Full pipeline tab reads the pipelines slice.

| | PCA | kNN | Clustering |
|---|---|---|---|
| **Stability** (seeds differ, one folder) | variance-weighted agreement between seeds; downstream ARI | shared neighbours between seeds; downstream ARI | ARI between seeds, per resolution |
| **Reproducibility** (same seed, other folder) | the same measures | the same | the same |
| **Concordance** | each pair of implementations against each one's own seed noise (permutation test), with PCA subspace angles | the same, with shared neighbours | the same, at equal resolutions |
| **Accuracy** | **fidelity**: share of the exact top-50 variance captured; downstream accuracy | **fidelity**: recall of the exact neighbours; downstream accuracy | ARI against the labels, per resolution; oracle resolution |
| **Cost** | wall time of the PCA job | wall time of the kNN job | wall time per Leiden run |

- **PCA fidelity** = Σᵢ λᵢ ‖V̂ᵀ vᵢ‖² / Σᵢ λᵢ, with vᵢ and λᵢ the exact solver's (covariance-
  eigh, CPU) i-th component and its variance and V̂ the method's 50 loadings: the share of the
  variance of the exact top 50 that the method's subspace holds. One number in [0, 1];
  a miss on an important component costs its share of the variance, a miss on PC 49
  almost nothing; rotations within near-degenerate components and sign flips cost nothing.
  Between two seeds (stability) the same measure, averaged over both directions.
- **kNN fidelity** = recall: the share of each cell's exact (brute-force) neighbours the
  method finds, averaged over cells.
- **Accuracy** against labels: ARI, as a share of the range between chance (0: ARI is
  chance-adjusted) and the oracle bound (the better of logistic regression and 15-NN,
  cross-validated on the exact embedding; Ben's cb-oracle).
- **Resolution.** In the stage tabs, downstream accuracy is read at the **baseline
  pipeline's oracle resolution**, fixed per dataset and size, so a worse PCA or kNN cannot
  be rescued by another resolution. In the Clustering tab and the Full pipeline tab, each
  implementation or pipeline is read at **its own oracle resolution** (best median accuracy
  over seeds, never chosen per seed). Both are oracle choices and labelled as such.
- **Cost** is wall time: a stage's own job in the stage tabs; per answer (PCA and kNN once,
  Leiden at every resolution of the sweep) in the Full pipeline tab. Queue time excluded,
  start-up included. The first rapids job of a module in a folder (a cold start: GPU kernels
  compiled and cached, ~12 s) is flagged and left out where there are others. Wall time
  answers *time to an answer*; cores, GPU and memory per job are kept alongside.

## Full pipeline tab

The five named pipelines, as in Ben's deck: accuracy distributions over seeds against the
chance and oracle bounds, stability, reproducibility and cost per answer, per dataset and
size; then cost against stability, cost against accuracy and accuracy against stability;
and two ways to choose:

    trade-off = w_a · accuracy + w_s · stability − w_c · log10(cost / fastest cost at that size)

with weights the reader sets (sliders), on absolute scales, so a score does not change when
a pipeline is added, plotted against cell number; and, without weights, the fastest
pipeline meeting accuracy ≥ X and stability ≥ Y at each dataset and size. Accuracy and
stability are positively correlated (Ben: Spearman 0.44–0.73), so equal weights partly
count the same thing twice; the weights make that choice visible.

## Report

- **Python computes, Quarto presents.** `analysis/phase2.py` (`pixi run phase2`) runs on the
  cluster and writes one TSV per table; `report/phase2.qmd` (`pixi run report2`) reads only
  those and renders in seconds to one self-contained HTML file, which works opened from
  disk, offline (Quarto's OJS cells do not run from `file://`, so the interactive part is
  plain JavaScript with d3 and Observable Plot vendored).
- **Tabs**: Overview · PCA · kNN · Clustering (each: Stability, Concordance, Accuracy, Cost)
  · Full pipeline. Concordance plots draw each implementation's own stability as a grey band.
- Colours: omnicol, noise floors grey (`CLAUDE.md`).

## Open questions and risks

- **Oracle resolution flatters every method.** A label-free rule (e.g. matching the
  number of clusters to the number of labels) is what a user faces; worth adding as a
  second reading once the oracle version works.
- **Labels are not neutral.** Annotations made by clustering favour pipelines like the
  one that made them; prefer independent labels (protein, FACS) where a dataset has them.
- **Budget.** At most about 11,500 jobs over all slices and sizes at 5 seeds (fewer: slices share their baseline jobs), before replicates
  (`pixi run filters` prints the counts); `--sizes` drops sizes that add nothing new.
- **Fair CPU comparison.** Most CPU modules use one core; the multithreaded pynndescent
  variant is what keeps "GPU against CPU" from being "GPU against one core".
- **Reuse, don't reimplement**: Ben's `almost-dominance-perf` code (dominance relation,
  transitivity check) can be fed the same tables later, as an extra section.

## Order of work

Each step is one patch, applied in order.

1. **Fork** (`Hephaestus-Hammer/scanpy`): randomized and Lanczos PCA on sparse input,
   `--n_jobs` for pynndescent, the same stored k on every kNN path.
2. **Datasets**: `scripts/publish_dataset.py`, `modules/dataset_input.py`, `docs/datasets.md`.
3. **Plan**: `benchmark-phase2.yaml`, `scripts/make_filters.py`, `filters/phase2/` (three
   stage slices and the pipelines slice), `scripts/run_pipelines.sh`, this document.
4. **Analysis**: per-stage stability, reproducibility, concordance, accuracy (fidelity and
   against labels) and cost; the named pipelines' summary; per dataset and size.
5. **Report**: the Quarto document, organised by stage.

Before the first run: push patch 1 and patch 2 and put their commits into the plan's
`CHANGE_ME` values, publish the four datasets and pin them, then re-run
`scripts/make_filters.py` (filter hashes include the commits). Run `slice-cluster` first,
into its own folder: `ob run benchmark-phase2.yaml --filter filters/phase2/slice-cluster.yaml
--out-dir out-phase2`, never Phase 1's `out/`.
