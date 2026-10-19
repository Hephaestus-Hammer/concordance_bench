# Filters

Each file is an obfilter selection passed to `ob run --filter <file>`, which
prunes the DAG to the picked stages, modules and parameter combinations.

| File | Runs | Host |
|---|---|---|
| `smoke.yaml` | 10k, scanpy only | any |
| `smoke-gpu.yaml` | 10k, all 8 scanpy/rapids combinations | GPU |
| `cpu-only.yaml` | all sizes, scanpy only | any |

The full plan needs no filter: `ob run benchmark.yaml --with-capability gpu`.

**A filter bypasses the capability gate.** Without a filter, `ob run` on a CPU
host drops the rapids modules (`requires_capabilities: [gpu]`) by itself. With a
filter, every picked module runs, so a filter meant for CPU hosts must leave the
rapids modules out.
