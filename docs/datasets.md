# Phase 2 datasets

Every dataset enters the same way (docs/phase2-plan.md):

1. `scripts/publish_dataset.py raw.h5ad <id>.h5ad --label_key <column>` preprocesses the
   whole dataset once (recipe below) and puts the labels in `obs.label`.
2. Upload the file to Hugging Face; pin its revision and the printed sha256 in
   `benchmark-phase2.yaml` (`omnibenchmark/omni-huggingface` downloads it, like the Hao data).
3. `modules/dataset_input.py` cuts the nested, label-stratified subsamples in the plan.

One recipe for every dataset, so no pipeline starts from a different matrix. Input-stage
parameters apply to every dataset alike, which is why the per-dataset choices (label
column, raw or normalised) are settled at publishing time, not in the plan.

Hao is the exception that needs no publishing: its sc-brrr 100k rung is already
log-normalised on 2,000 HVGs with labels in `obs.label`, so it serves as Hao's whole
dataset (subsamples up to 100k, nested within it).

| Plan id | Cells | Labels (`label_key`) | Source | Status |
|---|---|---|---|---|
| `hao2021` | 100,000 (the sc-brrr 100k rung) | `label` (RNA + protein, CITE-seq) | `btraven/sc-brrr-hao2021`, `hao2021_100k.h5ad` | ready |
| `pancreas` | 12,115 | to check | to fill in: where Ben's runs read it | to publish |
| `tm-facs` | 44,104 | to check | to fill in | to publish |
| `tm-droplet` | 54,865 | to check | to fill in | to publish |
| `aifi-d1` | 149,737 | to check | to fill in | to publish |

Cell counts are from Ben's deck (Sept 2026); they should match the labelled cells after
`dataset_input.py` drops unlabelled ones.

## Preprocessing (identical for every dataset)

| Step | Setting | Note |
|---|---|---|
| Unlabelled cells | dropped | accuracy needs a reference label for every cell |
| Normalisation | `log1p_cp10k` from counts; `none` if the file is already log-normalised (Hao) | out of scope as a variable (README scope) |
| Genes | 2,000 HVGs of the whole dataset, scanpy `seurat` flavour | the same genes at every subsample size |
| Subsample sizes | 5k, 10k, 25k, 50k, 100k, and each dataset whole (`in-all`) | one input module per size; sizes above a dataset's cell count `exclude` it |
| Ordering | `order_seed: 0` | fixes the nested ordering; a design constant, not a seed axis |

## Labels: record how each set was made

Labels from an independent modality (protein, sorting gates) are preferable to labels made
by clustering the same RNA data, which favour pipelines like the one that made them. For
each dataset, note here what its labels are based on before its accuracy is reported.
