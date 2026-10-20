# Decisions

Why the blessed baseline's settings are what they are, and what the code actually
does. The summary is in the README's *Blessed baseline* section; this is the full
record. Every non-default setting in `benchmark.yaml` gets an entry here.

## Defaults table

"scanpy defaults" is what the `pc-scanpy`, `nn-scanpy` and `cl-scanpy` modules
run now, through `omni-scrna/scanpy@b98b70b`.

| Stage | Setting | scanpy defaults | Blessed | Why |
|---|---|---|---|---|
| PCA | solver | `arpack` | `covariance_eigh` | Direct method: no iterations, tolerance or random start, so the seed has no effect. `arpack` is iterative and seed-dependent. |
| PCA | dtype | float64 (set in the plan) | float64 | |
| kNN | search | exact below 8,192 cells, pynndescent (approximate) above | exact (brute force) at every size | The switch is silent. All three sizes in the plan (10k, 50k, 100k) are above it, so the scanpy-defaults kNN is approximate everywhere. |
| kNN | connectivities | `umap` | `umap` | Deterministic once the neighbours are fixed. |
| Leiden | implementation | igraph | leidenalg | Reproducible per seed; avoids igraph's `n_iterations=-1` bug. |
| Leiden | iterations | 2 | `-1` (until converged) | |
| Leiden | graph | undirected | undirected | Like the GPU implementation. |
| Leiden | resolution | 1.0 | 1.0 | |
| Leiden | seeds | 0 | 0–19 | Different seeds reach different, equally valid partitions; seed-to-seed agreement is the noise floor. |
| All | BLAS threads | inherited from Snakemake (`OMP_NUM_THREADS` = rule threads) | 1 | Multithreaded reductions can change results in the last bits between runs. |
| All | versions | loose ranges (`envs/`) | pinned to exact builds | |

## Code findings

Checked against the pinned commits.

- **scanpy's exact/approximate kNN threshold is 8,192 cells for euclidean
  distance.** `scanpy/neighbors/__init__.py` (scanpy 1.12.4) uses dense, exact
  distances when `metric == "euclidean" and n_obs < 8192`; otherwise it falls
  back to pynndescent above 4,096 cells. The 4,096 threshold applies only to other
  metrics.
- **`omni-scrna/scanpy` `pca.py` has no `covariance_eigh`.** Its `--solver`
  choices are `arpack`, `randomized` and `full`, although scanpy itself supports
  `svd_solver="covariance_eigh"` for sparse input.
- **`omni-scrna/scanpy` `knn.py` cannot force exact search.** It calls
  `sc.pp.neighbors(..., method=flavor)` with `--n_neighbors`, `--flavor`
  (`umap`/`gauss`) and `--random_seed` only, so the threshold above decides.
- **`omni-scrna/scanpy` `cluster.py` hardcodes `n_iterations=2`** for both
  flavors (lines 84 and 89), with `directed=False`. Only `--resolution`,
  `--random_seed`, `--flavor` and `--partition_type` are exposed.
- **Only `pca.py` exposes `--blas_threads`** (0 = inherit `OMP_NUM_THREADS`);
  `knn.py` and `cluster.py` have no thread setting.
