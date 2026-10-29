# Filters

Each file is an obfilter selection passed to `ob run --filter <file>`, which
prunes the DAG to the picked stages, modules and parameter combinations.

| File | Runs | Host |
|---|---|---|
| `smoke.yaml` | 10k, CPU modules (scanpy defaults + baseline), seed 0: 8 combinations | any |
| `smoke-gpu.yaml` | 10k, every module, seed 0: 27 combinations | GPU |
| `cpu-only.yaml` | all sizes, CPU modules, seed 0 | any |
| `noise-pca.yaml` | all sizes, CPU modules: 20 arpack PCA seeds, seed 0 downstream | any |
| `noise-knn.yaml` | all sizes, CPU modules: 20 pynndescent kNN seeds, seed 0 elsewhere | any |
| `noise-cluster.yaml` | all sizes, CPU modules: 20 Leiden seeds, seed 0 upstream | any |

`first` keeps a module's first parameter combination (seed 0), `all` keeps every
seed. The noise filters vary one stage's seed at a time; run them one after the
other into the same `out/` and the seed-0 runs they share are computed once.
Without a filter, every seed list expands against every other (tens of
thousands of jobs per size).

**A filter bypasses the capability gate.** Without a filter, `ob run` on a CPU
host drops the rapids modules (`requires_capabilities: [gpu]`) by itself. With a
filter, every picked module runs, so a filter meant for CPU hosts must leave the
rapids modules out.
