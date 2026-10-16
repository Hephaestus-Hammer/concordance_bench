# Migrating a plan to `api_version: "0.7.0"`

The convention is **0.7.0 everywhere, migrate on sight**: any plan you open,
check; any plan you write, declare.

## Why it matters that the key is optional

`api_version` is an optional field whose model default is `0.4.0` (verified in
`omnibenchmark/model/benchmark.py`). A plan that never mentions it is a 0.4.0
plan, and nothing says so. `ob create benchmark` emits `name`, `id`,
`description`, `benchmarker`, `version`, `software_backend`,
`software_environments` and three example stages — and **no `api_version`**, so
every freshly scaffolded benchmark starts on the legacy contract.

## The recipe

```bash
grep -n '^api_version' benchmark.yaml          # absent? it is 0.4.0
```

1. **Set it, alone, in its own commit:**

   ```yaml
   api_version: "0.7.0"
   ```

   Quote it. Put it next to `version:` where a reader will see it.

2. **Validate:**

   ```bash
   ob validate plan benchmark.yaml
   ```

3. **Read the two behavioural changes below** and decide whether either
   affects this plan. They are not visible in the diff.

4. **Only then** consider adopting the new keywords. The bump does not require
   them; `provides`/`requires`, `requires_capabilities` and `gather` are opt-in.

Errors you may see at step 2, and what each means:

| Error | Cause |
|---|---|
| `Invalid API version: 0.4` | unquoted or truncated; the enum values are `0.1.0` … `0.7.0` |
| `Stage 'X' declares reserved label 'dataset'` | `provides:` may not use `name` or `dataset` |
| `Stage 'X' declares label 'Y' … also a stage id` | labels and stage ids share one namespace |
| `Module 'M' in initial stage 'S' declares requires` | nothing upstream to gate on |

The full table of validator messages is in `plan-reference.md`.

## Change 1 — `--name` stops meaning "dataset"

At `api_version <= 0.4.0` the Snakemake backend passes the **dataset**
identifier as `--name`; from `0.5.0` it passes the **module's own id**
(verified: an explicit, commented workaround in
`omnibenchmark/backend/snakemake.py`, gated on `api_version <= V0_4_0`).

A module whose entrypoint builds its output filename as
`{output_dir}/{name}_pcas.tsv` therefore writes `pbmc_pcas.tsv` before the bump
and `pc-scanpy_pcas.tsv` after it, while the plan still declares
`path: "{dataset}_pcas.tsv"` — and Snakemake fails the rule for a missing
output. This is the one migration failure that does not show up in
`ob validate plan`.

Check for it before running:

```bash
grep -rn 'args.name\|args\$name\|{name}' <module-repos>/*.py <module-repos>/*.R
```

Fixes, preferred first:

1. Change the declared output template to `path: "{name}_pcas.tsv"`. At 0.7.0
   `{name}` in a path and `--name` on the command line are both the current
   module id, so plan and module agree by construction. Downstream consumers
   reference the output *id*, not the filename, so nothing else moves — but
   any glob or validator matching `<dataset>_*` should be re-checked.
2. Keep `{dataset}` and pass the dataset value as an explicit plan
   `parameter`.

Modules that write `{output_dir}/<fixed name>` or derive the filename from a
declared output id are unaffected.

## Change 2 — shared output ids and fan-in stop being linearised

Below 0.7.0 the resolver puts every stage on a single upstream lineage:

- when one output id has several producers, a consumer binds one of them and
  the others silently fall out;
- a stage whose inputs come from **divergent branches** (a diamond) is
  rejected outright at validation time — `ob validate plan` calls
  `detect_diamond_input_joins()` only when `api_version < 0.7.0`.

From 0.7.0 both are first-class (spec §3.11, §3.12): parallel producers of a
shared id are *alternatives* and the consumer expands once per producer; a
downstream producer *shadows* an upstream one; divergent branches resolve into
a join node with several parents.

The practical consequence is that **the same plan can expand into more nodes
after the bump**. That is usually the point — but check the node count before
committing to a full run:

```bash
ob run benchmark.yaml --dry            # writes out/Snakefile
grep -c '^rule ' out/Snakefile
```

## Worked example: a 21-stage plan at 0.4.0

`omni-scrna/split-stages-plan` → `benchmark_conda.yaml`. It is public, real,
and still declares `api_version: "0.4.0"` — a migration subject, not a model of
the target contract. 21 stages (`DATA`, `FILT`, `NORM`, `FEAT`, `PCA`,
`ISOMAP`, `EMBED-M`, `NNG`, `GRAPH-M`, `CLUST`, `CLUST-M`, `CLUSTBOUND`,
`INTG8`, `INTG8-M`, `NNG-C`, `CLUST-C`, `CLUST-E`, `ANNO`, `ANNO-M`, `CNTFCT`,
`NORM-M`), 35 modules, conda backend, 11 software environments, S3 storage.

**What changes: one line.**

```diff
-api_version: "0.4.0"
+api_version: "0.7.0"
```

Verified by loading the plan through the model at both versions: it parses and
passes `validate_execution_context` either way, and
`detect_diamond_input_joins()` returns nothing, so no stage needs restructuring
to satisfy the 0.7.0 gate.

**What stays exactly as it is:**

- the header (`name`, `id`, `description`, `benchmarker`, `version`),
  `provenance.canonical_url`, the `storage` block, `software_backend: conda`;
- the `software_environments` mapping, one `{name, conda: envs/*.yml}` per
  entry;
- every stage, module, `repository: {url, commit, entrypoint}` pin, parameter
  grid, `resources:` block and `exclude:` list. None of them changed shape
  between 0.4.0 and 0.7.0.

**What to review afterwards, in this plan specifically:**

- Three output ids have more than one producer (verified):
  `embedding_tsv` (`PCA`, `ISOMAP`, `CNTFCT`), `loadings_tsv` (`PCA`,
  `CNTFCT`), `clusters_tsv` (`CLUST`, `CLUSTBOUND`). Under 0.4.0 semantics a
  consumer such as `CLUST-M` binds one producer of `clusters_tsv`; at 0.7.0 it
  expands over both, which is what the plan's own comment beside `CLUSTBOUND`
  says it wants ("Needs an ob with shared-output-id fan-in … on main CLUST-M
  silently takes only one producer"). Expect more nodes, and a bigger results
  table.
- The `--name` question above, for every module repository this plan pins.

**Optional, after the bump — do not bundle these into the migration commit:**

- Several `INTG8` modules repeat the same `exclude:` list
  (`d-pca`, `d-annotation`, `d-feat-sel`, and `cntfct` twice — a duplicate
  entry that is harmless but signals the list is being copy-pasted). Where the
  axis belongs to **one** stage — here "which dataset collection is this" on
  `DATA` — a lineage label says it once:

  ```yaml
    - id: DATA
      provides: [collection]
      modules:
        - id: d-integration
          provides: {collection: integration}
        - id: d-pca
          provides: {collection: pca}
    - id: INTG8
      modules:
        - id: in-harmony
          requires: {collection: integration}
  ```

  Keep `exclude:` for genuinely pairwise, cross-stage incompatibilities (a
  module that must not meet another module), since a label is owned by exactly
  one stage and cannot express "not with that one".
- A metrics stage that wants every arm of an upstream stage at once is a
  `gather`, not a hand-written fan-in — see `lineage-and-gather.md`.

## Caveat on scope

The statements above about **validation** were checked by running the plan
through the parser and the model validators at both api versions. The
statements about **run-time expansion** (more nodes, joins resolving) are read
off the resolver and backend source, not off an executed run: a real run needs
the module repositories and their conda environments. Confirm with
`ob run <plan> --dry` on the machine that will run the benchmark before
promising anyone a node count.
