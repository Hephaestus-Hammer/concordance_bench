# The stage contract

A stage in the plan is a promise to the people who write modules for it: *these
flags will arrive, these files must be written*. This page says exactly how the
plan's declarations turn into that promise, so a module author knows what she
has to produce and how it will be checked.

Two layers, and it is worth keeping them apart:

| Layer | Who defines it | Where it lives |
|---|---|---|
| The invocation and the output filenames | core `ob`, from the plan | compiled into `out/Snakefile` |
| The *named, typed* CLI contract and its validators | the benchmark author, by convention | the plan repo's `schema/` and `validators/` |

The first is mandatory and mechanical. The second is house style — used by
`omni-scrna/split-stages-plan` and the `omni-scrna/boilerplate` helpers — and
is what makes several modules in two languages expose the same flags.

## 1. What the runtime hands a module (core `ob`)

Every module is invoked from **inside its own checked-out source tree**, with
absolute paths:

```sh
cd .modules/<repo>/<commit>
./<entrypoint> \
  --output_dir /abs/path/to/<node output dir> \
  --name <see below> \
  --<input_id> /abs/path/to/<producer file> \
  --<param_key> <value> ...
```

Read off a real compiled rule (`ob run <plan> --dry` writes `out/Snakefile`;
this one is a PCA node in `omni-scrna/split-stages-plan`, filenames shortened):

```
    input:
        normalized_selected_h5="DATA/pbmc/.fc978a6f/.../FEAT/fe-scanpy/.7df64bd1/pbmc_normalized_selected.h5",
    output:
        ".../PCA/pc-scanpy/.07ef8b80/pbmc_pcas.tsv",
        ".../PCA/pc-scanpy/.07ef8b80/pbmc_loadings.tsv",
    params:
        module_dir=".modules/scanpy/53eb292",
        entrypoint="pca.py",
        cli_args="--n_components 50 --random_seed 42 --solver arpack",
    shell:
        ...
        cd {params.module_dir}
        ./{params.entrypoint} \
        --output_dir $OUTPUT_DIR \
        --name pbmc \
        --normalized_selected_h5 $INPUT_normalized_selected_h5 \
        {params.cli_args}
```

Consequences, each of which has bitten someone:

- **One flag per declared stage input, named after the output *id*.** The plan
  says `inputs: [normalized_selected_h5]`; the module gets
  `--normalized_selected_h5`. An id containing a dot keeps the dot in the flag
  (`--rawdata.clusters_truth`); in Python `argparse` that lands in
  `args.rawdata_clusters_truth` unless the parser sets `dest`.
- **One flag per parameter**, GNU style, in sorted-key order.
- `--output_dir` is absolute and already exists (`mkdir -p` runs first).
- The entrypoint runs with the **module root as cwd**, so relative paths inside
  the module (`src/common/…`, `envs/…`) work, and nothing may be written
  relative to cwd — all output goes under `--output_dir`.
- The entrypoint is executed as `./<entrypoint>`, so it needs a shebang and the
  executable bit (without a shebang `ob` falls back to an interpreter guess).
- The module never receives its output filenames. It must construct them.

### `--name` changes meaning at api_version 0.5.0 — read this before migrating

- `api_version <= 0.4.0`: `--name` is the **dataset** identifier (the initial
  stage's module id), extracted from the output path. In the rule above,
  `--name pbmc` while the module is `pc-scanpy`.
- `api_version >= 0.5.0`: `--name` is the **current module's own id**
  (`pc-scanpy`).

This is a deliberate, commented workaround in the Snakemake backend
(`omnibenchmark/backend/snakemake.py`): legacy modules build output filenames
as `{name}_something.tsv` while the plan declares `{dataset}_something.tsv`,
and the two only agree if `--name` carries the dataset. From 0.5.0 they do not
agree any more.

So a module that does `out = f"{args.output_dir}/{args.name}_pcas.tsv"` writes
`pbmc_pcas.tsv` under a 0.4.0 plan and `pc-scanpy_pcas.tsv` under a 0.7.0 plan.
Snakemake then fails the rule for a missing output. Options, in order of
preference:

1. Declare the output as `path: "{name}_pcas.tsv"` in the plan. At 0.7.0
   `{name}` and `--name` are both the current module id, so plan and module
   agree by construction.
2. Keep `{dataset}` in the path and have the module take the dataset value as
   an ordinary plan `parameter`, so it is explicit on the command line.

Do not have the module parse its own `--output_dir` to recover the dataset;
that couples the module to the path layout.

## 2. What the module must write

Exactly the files the stage declares, in `--output_dir`, with the template
resolved. Nothing else is collected.

```yaml
  - id: PCA
    outputs:
      - id: pcas_tsv
        path: "{dataset}_pcas.tsv"
      - id: loadings_tsv
        path: "{dataset}_loadings.tsv"
```

Every module in the `PCA` stage must write both files, under both names, for
every node. A missing declared output fails the rule; an extra file is ignored
by `ob` (it stays in the directory but no downstream stage can reference it).

Placeholders resolve per node: `{dataset}` = root module id, `{name}` = this
module's id, `{params.<key>}` = one of its parameter values, `{<label>}` = a
`provides` label or a gather group key. See the skill's path-vocabulary table.

### Where the files land

Verified output tree (default `out/`, configurable with `--out-dir`):

```
out/
├── Snakefile                  # fully resolved, runnable standalone
├── .metadata/                 # manifest.json, a copy of the plan, modules.txt
├── .logs/<rule>.log           # stdout+stderr of each module invocation
├── .modules/<repo>/<commit>/  # checked-out module trees (the cwd above)
├── .envs/<env>.yaml           # materialised software environments
└── <STAGE>/<module>/.<hash>/<STAGE2>/<module2>/.<hash2>/…
```

- The lineage is **nested, cumulative**: a PCA node's directory sits inside its
  FEAT parent's, which sits inside NORM's, and so on back to the dataset.
- `.<hash>` is the 8-char parameter hash, dot-prefixed so it hides; a module
  with no parameters gets the literal `.default`.
- Beside the hash directory the runtime writes a readable symlink
  (`n_components-50_random_seed-42_solver-arpack -> .07ef8b80`), and inside it
  a `parameters.json` and a `<dataset>_performance.txt` benchmark record. Those
  are written by `ob`, not by the module.

## 3. The typed CLI contract — `schema/<stage-id>.json`

> House style: `omni-scrna/split-stages-plan` + `omni-scrna/boilerplate`. Core
> `ob` knows nothing about these files. Adopt the pattern or don't, but if your
> benchmark has Python and R implementations of the same stage, this is what
> keeps their flags identical.

One JSON file per stage, named for the stage `id`, owned by the benchmark
author and copied into each module (overwrite-on-update) by the boilerplate's
`scripts/pull.py`:

```json
{
  "stage": "PCA",
  "version": "0.1.1",
  "benchmark": "omni-scrna/split-stages-plan",
  "args": [
    { "flag": "--normalized_selected_h5", "type": "path",
      "help": "Normalized, gene-selected matrix H5" }
  ]
}
```

| field | required | meaning |
|---|---|---|
| `flag` | yes | the option string, matching the plan's output id |
| `type` | yes | `path` \| `string` \| `integer` \| `number` |
| `help` | no | help text |
| `dest` | no | attribute name; defaults to the flag with `.`/`-` → `_` |
| `choices` | no | an enum, as in `argparse` |

Plus `schema/_base.json`, the two args every module gets (`--output_dir`,
`--name`). Every schema-declared arg is **required** — a run must be
reproducible from its invocation line, with no defaults. Each schema carries
its own `version`; bump it when the stage's contract changes.

Three kinds of argument, by owner:

| source | holds | owner | on `pull` |
|---|---|---|---|
| `_base.json` | `--output_dir`, `--name` | the benchmark | overwritten |
| `<stage-id>.json` | that stage's I/O contract | the benchmark | overwritten |
| the module's entrypoint | its method parameters (`--solver`, …) | the module author | never touched |

Method parameters are deliberately *not* schema-driven: they are written by
hand in plain `argparse` / `argparser`, so the whole CLI stays visible in the
entrypoint file.

The schema files are data the plan repo owns; keep `schema/<stage-id>.json` in
step with the stage's `inputs:` whenever you edit the plan. A stage input added
in the plan and not in the schema is a flag the module never learns to accept.

## 4. Checking that a module honours the contract

### Benchmark-side validators

> House style again: `omni-scrna/split-stages-plan` ships
> `validators/<stage-id>/<output-file>/validate.{R,py}`, each taking one or
> more file paths as arguments and printing `OK\t<path>` or
> `FAIL\t<path>\t<reason>` per file, plus a `validators/all.sh` that globs the
> output tree and runs them. `ob` does not run these; CI and the author do.

They are short and they check exactly what the contract promises. From the
plan's `validators/`:

- a PCA `pcas.tsv`: first column is `PC1`, non-empty, at least 10 columns,
  first data row numeric;
- a normalised `.h5`: `matrix/genes` length matches `matrix/shape[1]`, and no
  gene is all-zero (a zero-variance gene surfaces far downstream as a confusing
  number rather than an error);
- a dataset `.h5ad`: no `obs` column is categorical-encoded, because the
  downstream R modules read `obs` with `rhdf5::h5read`, which mangles the
  categorical group encoding that `anndata` writes.

Note the shape of those three: each encodes a **cross-language or cross-stage
invariant that a human cannot see by eye**, and each was written after
something went wrong. That is the bar. A validator asserting that a TSV is a
TSV is noise.

One of them carries a `--selftest` branch that writes a tiny fixture and
asserts the validator catches it — one check, not a suite. That is a good
pattern when the validator's own logic is non-obvious.

### Module-side invariants

The same invariants belong in the module too, where they fail fast and name the
line that broke them. The exemplar modules wire a `check` task in `pixi.toml`
(`check = "python check.py"` / `Rscript check.R`) — that is where this lives in
practice. What earns its place:

- the declared output file exists and is non-empty;
- row/column counts match the input (identifiers survive the transform, in the
  same order);
- dimensions equal the requested number of components;
- the degenerate cases the author named when the stage was designed.

Plain `assert` / `stopifnot` next to the code they guard is enough; a test that
asserts a function returns what it just returned is not documentation.

### End to end

```bash
ob validate plan benchmark.yaml            # the plan is well formed
ob run benchmark.yaml --dry                # inspect out/Snakefile: is the invocation what you expect?
ob run benchmark.yaml -m <module-id>       # run only this module's sub-graph, first input x param combo
sh validators/all.sh                       # benchmark-side checks over the output tree
```

`ob run -m` is the module author's inner loop: it prunes every stage after the
target's and keeps one upstream expansion, so it produces one real invocation
with real inputs. Land one entrypoint that passes this loop before adding the
second.

## Sources

- `omnibenchmark/omnibenchmark` — `docs/design/004-yaml-specification.md` §3.5
  (reserved parameters), §3.6 (inputs/outputs), §3.7 (path strategy);
  `docs/design/007-output-layout.md` (output tree, `manifest.json`);
  `omnibenchmark/backend/snakemake.py` (the invocation, and the `--name`
  workaround).
- `omni-scrna/split-stages-plan` — `docs/stage-schemas.md`, `schema/*.json`,
  `validators/`. Public and worth reading for module structure; its plan files
  still declare `api_version: "0.4.0"` and predate `provides`/`requires`/
  `gather`, so do not copy their plan-facing metadata.
- `omni-scrna/boilerplate` — `docs/cli.md` (the shared `add_base_args` /
  `add_stage_args` helpers), `scripts/pull.py`, `actions/validate-module`.
