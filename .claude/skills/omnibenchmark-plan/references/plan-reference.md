# Plan field reference

Every field the plan model accepts, its type, and what rejects it. Source of
truth: `docs/design/004-yaml-specification.md` (Accepted, v7) and
`omnibenchmark/model/benchmark.py` + `omnibenchmark/model/validation.py` in
`omnibenchmark/omnibenchmark`. Where the spec prose and the model disagree, the
model is what runs and it is flagged below.

## Top level

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | must not start with a digit |
| `benchmarker` | string | yes | author or organisation |
| `version` | string | yes | strict semver `x.y` or `x.y.z`, no leading zeros; quote it |
| `name` | string | no | human-readable |
| `description` | string | no | |
| `authors` | list of strings | no | defaults to `[benchmarker]` |
| `api_version` | enum string | no | `0.1.0` … `0.7.0`; **default `0.4.0`** — always write `"0.7.0"` |
| `software_backend` | enum | yes | `apptainer` \| `conda` \| `docker` \| `envmodules` \| `host` |
| `software_environments` | mapping | yes | id → definition (see below) |
| `stages` | list | yes | ≥ 1 |
| `metric_collectors` | list | no | legacy fan-in; prefer `gather` at 0.7.0 |
| `storage` | object | no | `{api, endpoint, bucket_name}` |
| `provenance` | object | no | `{canonical_url, derived_from, subset_of}`; informational only |

Deprecated, still accepted: `benchmark_yaml_spec` (use `api_version`),
`storage_api` / `storage_bucket_name` as top-level keys, and `storage:` as a
bare endpoint string. Mixing the old top-level storage keys with a `storage:`
mapping is rejected with "Mixed storage format detected".

Spec §3.1 prose says the `api_version` default is `"0.4"` in one place and
`"0.3"` in another; the model's default is the `0.4.0` enum member. Treat the
model as authoritative and set the field explicitly.

## `software_environments`

Written as a mapping; the key becomes the environment `id` (the loader
converts it to the model's list form).

```yaml
software_environments:
  r_conda:
    name: R conda env
    description: optional prose
    conda: envs/r.yml
```

| Field | Type | Notes |
|---|---|---|
| `name`, `description` | string | free text |
| `conda` | path or URL | conda backend |
| `apptainer` | path or URL | apptainer/docker backend |
| `docker` | string | docker image |
| `envmodule` | string | envmodules backend |
| `easyconfig` | path | EasyBuild |
| `repository` | `{url, commit}` | optional |

- For any backend other than `host`, a relative path is resolved against the
  plan's directory and **must exist** at validation time; an absolute path must
  exist; a URL is not checked.
- Exactly one environment declared ⇒ modules and metric collectors may omit
  `software_environment:` and it is filled in automatically.
- An environment with no backend key at all currently passes the per-object
  validator (the check is commented out in the model) and fails later at the
  benchmark level for the active backend.

## `storage`

| Field | Type | Notes |
|---|---|---|
| `api` | enum | `S3` (default) or `MINIO` — MinIO is deprecated, emits a `DeprecationWarning`; use `S3` with a custom endpoint |
| `endpoint` | string | required when `storage` is present |
| `bucket_name` | string | needed for S3 |

Only consulted with `ob run --use-remote-storage` and the `ob remote`
subcommands.

## `stages[]`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | unique; must not start with a digit; shares a namespace with `provides` labels |
| `modules` | list | yes | ≥ 1 |
| `outputs` | list of `{id, path}` | yes | |
| `inputs` | list of output ids | no | absent ⇒ initial stage |
| `provides` | list of strings | no | **api ≥ 0.7.0** |
| `gather` | list of `{from, group_by}` | no | **api ≥ 0.7.0**; alternative to `inputs` |
| `resources` | object | no | stage default for its modules |
| `name`, `description` | string | no | |

`outputs[].path` is a filename template. A `/` in it emits a `FutureWarning`
("Full paths are deprecated"); an absolute path is an error; an empty path is
an error.

`inputs:` is a plain list of output ids. The legacy
`inputs: [{entries: [...]}]` form still parses but warns.

## `stages[].modules[]`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | keep unique **across the whole plan** (see the caveat below); becomes a wildcard value and part of the rule name |
| `repository` | `{url, commit, entrypoint?, type?}` | yes | |
| `software_environment` | string | yes* | *optional when exactly one environment is declared |
| `parameters` | list of dicts | no | |
| `exclude` | list of module ids | no | |
| `requires` | map label → value | no | lineage gate (§3.9) |
| `provides` | map label → value | no | **api ≥ 0.7.0** |
| `requires_capabilities` | list of strings | no | host gate (§3.10) |
| `resources` | object | no | overrides the stage's |
| `name`, `description` | string | no | |

**Caveat on module ids.** The model collapses all modules into one dict keyed
by id before checking for duplicates, so the "duplicate module ids" check can
never fire: reusing one id in two stages validates cleanly (verified). It is
still a mistake — the id is a wildcard value, part of the Snakemake rule name,
and the key by which `exclude:`, `requires:` and `ob run -m` identify a module.
Keep module ids unique across the plan yourself; nothing will tell you.

`repository.commit` is coerced to a string if written as a number — avoid that;
quote shas that look numeric. `repository.entrypoint` names a key in the
module's own `omnibenchmark.yaml`; omitted, it is `default`.

`exclude` is matched by **module id**, is symmetric, transitive across
non-adjacent stages, and OR-ed over the list. An entry that is not a module id
is silently ignored — a typo prunes nothing and says nothing.

## `parameters`

```yaml
parameters:
  - solver: [arpack, randomized]     # list ⇒ grid expansion
    n_components: 50
```

- Every item should carry the **same key set**; mixed key sets produce a
  yellow `WARN: parameter list has N items with inconsistent keys …`.
- A list value always means grid expansion. There is no way to pass a literal
  list as one value.
- The legacy `- values: ["--method", "cosine"]` form still parses and warns.
- `--name` and `--output_dir` are supplied by the runtime and must not appear.
- Each combination hashes to 8 hex chars (sorted `key=value`, SHA-256); no
  parameters ⇒ the path segment `default`.

## `resources`

`cores`, `mem_mb`, `disk_mb`, `runtime` (minutes), and `gpu` — all optional
positive integers, but **at least one must be present** if the block exists.
Most-specific-wins: module, then stage, then the global default `cores=2`.
(`gpu` is a model field not listed in spec §7.2; `cores` also sets Snakemake's
`threads:`.)

## `gather[]` (api ≥ 0.7.0)

| Field | Type | Notes |
|---|---|---|
| `from` | string | output id to collect; **every** producer is a member; zero producers is an error |
| `group_by` | string | a **stage id** to partition by; optional — omitted means one global node |

All entries on one stage must share the same `group_by` (and "none" counts as
a value). See `lineage-and-gather.md`.

## `metric_collectors[]`

The pre-0.7.0 fan-in mechanism: `{id, repository, software_environment,
inputs, outputs, parameters?, resources?}`. Inputs must name declared output
ids. `{name}` in a collector's output path resolves to the collector id.
For new plans at 0.7.0, prefer a `gather` stage — it participates in the same
lineage machinery as everything else.

## Validator messages

Reproduced from the model; each was triggered against a minimal plan and the
text below is what `ob validate plan` prints (prefixed with the file and, where
the loader can locate it, a line number).

| Message | Trigger |
|---|---|
| `Stage 'X' uses `provides`, which requires api_version ≥ 0.7.0 (this benchmark declares 0.4.0).` | 0.7.0 keyword on an older plan |
| `Stage 'X' uses `gather`, which requires api_version ≥ 0.7.0 …` | same, for `gather` |
| `Module 'M' uses `provides`, which requires api_version ≥ 0.7.0 …` | same, for module-level `provides` |
| `Stage 'X' declares reserved label 'dataset' in `provides`. 'dataset' is a builtin populated by the runtime; choose another name.` | reserved label (`name`, `dataset`) |
| `Stage 'X' declares label 'Y' in `provides`, but 'Y' is also a stage id. Hint: rename the label.` | label / stage-id collision |
| `Stage 'X' declares label 'L' in `provides`, but stage 'W' already declares it. A label is owned by exactly one stage; rename one of them.` | two owners for one label |
| `Module 'M' binds label 'L' in `provides`, but stage 'S' does not declare it. Add 'L' to the stage's `provides` list or fix the key.` | module binds an undeclared label |
| `Module 'M' in initial stage 'S' declares `requires`, but an initial stage has no upstream lineage to match against.` | gate with nothing upstream |
| `Module 'M' in gather stage 'S' declares `requires`, but a gather collects members from many lineages at once … move the `requires` to the modules producing '<id>'` | gate on a gather module |
| `Stage 'X' gathers with `group_by: Y`, which is not a known stage id.` | typo in `group_by` |
| `Stage 'X' gathers with `group_by: name`, but 'name' is a reserved builtin label. Hint: rename the stage.` | grouping by a stage called `name`/`dataset` |
| `Stage 'X' has gather entries with differing group_by ['<global>', 'data'] …` | mixed grouping axes on one stage |
| `Input with id 'Z' in stage 'S' is not valid` | `inputs:` names an id no stage produces |
| `Found duplicate stage ids: …` | two stages share an id (the module-id equivalent exists in the code but cannot fire — see the caveat above) |
| `Software environment with id 'E' is not declared. It should be listed as part of the stanza software_environments …` | unknown environment reference |
| `Software environment path for 'conda' does not exist: '<path>'.` | env file missing on disk |
| `Module 'S/M' can never run: its `exclude` rules … leave no valid upstream lineage …` | over-constrained excludes |
| `id 'X' must not start with a digit — Snakemake rule names are Python identifiers and cannot begin with a number` | numeric-leading id |
| `Version 'v1.0' does not follow strict semantic versioning format. Expected x.y.z or x.y …` | non-semver `version` |
| `Invalid API version: <v>` | value outside the enum (e.g. unquoted `0.4`, which YAML reads as a float) |

Duplicate **output** ids are *not* an error — that is the shared-output-id
contract of §3.11, relied on by `gather`.

## What validation does not cover

`ob validate plan` does not fetch repositories, does not check that a commit
exists, does not run or inspect any module, and cannot tell you that a module
will write the files its stage declares. For that, read a compiled rule
(`ob run <plan> --dry`, then `out/Snakefile`) and run the stage's validators —
see `stage-contract.md`.
