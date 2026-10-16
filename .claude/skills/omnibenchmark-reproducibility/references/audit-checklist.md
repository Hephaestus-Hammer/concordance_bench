# Sources of variation, and how to control them

Go through these for the module **and** for every upstream call it makes. For
each row, record whether it applies, where it is in the code, and whether it is
controlled. That table is the audit.

## Python

| source | control |
| --- | --- |
| `random` module | `random.seed(seed)`, or better, a `random.Random(seed)` instance passed down |
| numpy global RNG (`np.random.rand`, `shuffle`, ...) | Replace with `rng = np.random.default_rng(seed)` passed explicitly. `np.random.seed` covers only the legacy global state |
| An upstream `random_state=None` default (sklearn, umap-learn, pynndescent, leidenalg, `igraph` `community_leiden`) | Pass `random_state=seed` / `seed=seed` explicitly at every call. Grep the upstream signature, because the default is often not in the docs |
| scanpy | Most functions default to `random_state=0`. That is fixed but hidden, so pass the module's seed through anyway, or `--random_seed` is silently inert |
| torch | `torch.manual_seed(seed)` (seeds CPU and CUDA), `torch.use_deterministic_algorithms(True)`, `torch.backends.cudnn.benchmark = False`, env `CUBLAS_WORKSPACE_CONFIG=:4096:8`; `DataLoader(worker_init_fn=..., generator=torch.Generator().manual_seed(seed))` |
| JAX | Explicit `PRNGKey(seed)` is deterministic on CPU; on GPU set `XLA_FLAGS=--xla_gpu_deterministic_ops=true` |
| scvi-tools / lightning | `scvi.settings.seed = seed`; lightning `seed_everything(seed, workers=True)` |
| `set` / `frozenset` iteration order of `str` | Depends on `PYTHONHASHSEED`. Iterate `sorted(...)` rather than pinning the hash seed |
| `os.listdir`, `glob`, `Path.iterdir` | Order is filesystem-dependent. Wrap in `sorted()` |
| multiprocessing / joblib | Result order follows completion order unless collected by index. Each worker needs its own seed derived from `SeedSequence(seed).spawn(n)` |
| numba `parallel=True`, `prange` reductions | Reduction order varies. Use serial code or accept `@threads` |

## R

| source | control |
| --- | --- |
| `set.seed(seed)` | Call it once, early, and **before** any package that draws at load time. Record `RNGkind()` in the log, because the default sampler changed in R 3.6 |
| `parallel::mclapply`, `parLapply` | `RNGkind("L'Ecuyer-CMRG")` + `set.seed`; `mc.set.seed = TRUE` |
| BiocParallel | `BPPARAM = SerialParam(RNGseed = seed)` / `MulticoreParam(RNGseed = seed)` |
| future / furrr | `future.seed = seed` (or `furrr_options(seed = seed)`) |
| Rcpp / C++ code with its own RNG (`std::mt19937`, RcppML, irlba's C path) | Check that the package exposes a `seed =` argument and pass it. `set.seed` does not reach a C++ RNG unless the package reads R's RNG |
| `irlba` | Start vector is random. Pass `v =` or rely on `set.seed` (it uses R's RNG) |
| `uwot::umap` | `set.seed` + `n_sgd_threads = 1` for exact replicates. Multi-threaded SGD is not reproducible |
| data.table / dplyr grouping | Sort order is locale-dependent (`LC_COLLATE`). Set `Sys.setlocale("LC_COLLATE", "C")` or sort explicitly |

## BLAS, LAPACK and OpenMP

| source | control |
| --- | --- |
| Thread count | `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `BLIS_NUM_THREADS`, set before import. In Python `threadpoolctl.threadpool_limits(n)` works after import |
| MKL code-path dispatch (picks kernels per CPU) | `MKL_CBWR=COMPATIBLE` (or `AVX2`) for conditional numerical reproducibility across CPUs. This is the main lever for A tier on MKL |
| OpenBLAS kernel dispatch | `OPENBLAS_CORETYPE=<type>` pins the kernel. Without it x86 generations differ |
| BLAS vendor itself | Part of the environment. Pin it (`libblas=*=*openblas` / `*mkl`) in `pixi.toml` so the lock records it |
| OpenMP `schedule(dynamic)` reductions | Can vary run-to-run at a fixed thread count. The upstream fix is `static`. Otherwise accept `@threads=1` |

## GPU

| source | control |
| --- | --- |
| Atomic adds in reductions (scatter, index_add, sparse matmul) | Deterministic mode where the library has one (torch above). Otherwise expect C at best, and mark upstream-limited |
| cuDNN autotuning | `cudnn.benchmark = False`, `cudnn.deterministic = True` |
| RAPIDS / cuML | Many estimators take `random_state`. Some (UMAP, t-SNE on GPU) are not deterministic even when seeded |
| GPU model and driver | Part of the platform. Record `nvidia-smi` output with the tier |

## I/O and output metadata

These are cases where the file differs but the result does not.

| source | control |
| --- | --- |
| gzip header mtime and filename | Python `gzip.GzipFile(filename="", mode="wb", fileobj=f, mtime=0)` (`gzip.open` takes no `mtime`). CLI `gzip -n` |
| AnnData `.h5ad` `uns` entries (timestamps, versions) | Drop or fix them before writing. HDF5 object timestamps also differ, so compare contents with `h5diff`, not bytes |
| HDF5 via h5py | `create_dataset(..., track_times=False)`, and no `attrs["created"]` |
| RDS | `saveRDS` output is stable for identical objects, but objects carry attributes such as call or environment. Strip them or `all.equal` the loaded object |
| Float formatting | `%.17g` is round-trip exact. `repr` differs between numpy versions (environment, not the run). Pandas `to_csv(float_format=...)` rounding can hide real differences |
| Row/column order from a dict or hash map | Sort by id before writing |
| Absolute paths, hostnames, `datetime.now()` in outputs | Write them to the log, not the declared outputs |

## Upstream nondeterminism with no knob

If the upstream library has no way to make a step deterministic, do not
work around it in the module. Record it in the tier as upstream-limited, name
the function, and file or link the upstream issue. It is still worth checking
whether a single-threaded or CPU path exists that makes it deterministic. That
gives a `B@threads=1` result, and the author can decide whether that
configuration is worth offering as a separate arm.
