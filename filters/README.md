# Filters

Each file is an obfilter selection passed to `ob run --filter <file>`, which
prunes the DAG to the picked stages, modules and parameter combinations.

| File | Selects |
|---|---|
| `smoke.yaml` | Hao 10k, 2 seeds: quick end-to-end check |
| `cpu-only.yaml` | no GPU modules |
| `full.yaml` | all sizes, all seeds |

Not written yet: the picks name stage and module ids from `benchmark.yaml`.

CPU-only may not need a filter: if GPU modules declare
`requires_capabilities: [gpu]`, they are pruned unless the run passes
`--with-capability gpu`.
