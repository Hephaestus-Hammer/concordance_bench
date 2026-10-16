# The validation layer in detail

Read from `omnibenchmark/cli/validate.py`, `omnibenchmark/core/metadata.py`,
`omnibenchmark/core/repository_utils.py`, `omnibenchmark/model/validation.py`
and `omnibenchmark/model/benchmark.py` in `omnibenchmark/omnibenchmark`, and
confirmed by running the commands. Omnibenchmark is alpha; re-read the source
if behaviour here disagrees with what you observe.

## `ob validate plan`: the call path

```
BenchmarkModel.from_yaml(path)          # YAML + Pydantic + model structure
benchmark_model.validate_execution_context(path.parent)
```

Every failure mode maps to one exit-1 message:

| raised | printed as |
| --- | --- |
| `FileNotFoundError` | `Error: Benchmark YAML file not found.` |
| `yaml.YAMLError` | `Error: YAML file format error: …` |
| Pydantic `ValidationError` | `Validation failed:` then one line per field: `Missing required field: 'stages -> 0 -> id'` or `Field 'x': <msg>` |
| `BenchmarkParseError` / `ValueError` | `Error: Failed to parse YAML as a valid OmniBenchmark: …` |
| model `ValidationError` | `Error: <joined error list>` |

The Pydantic field path is `loc` joined with ` -> `, so `stages -> 3 -> modules
-> 1 -> repository -> url` reads as the 4th stage, 2nd module. Count from zero.

### Messages from the model layer

These come from `BenchmarkValidator.validate_model_structure()` and are the
ones you will actually meet:

```
Found duplicate stage ids: …
Found duplicate module ids: …
Found duplicate output ids: …
Output path for file <id> is empty
Output path for file <id> must be relative, not absolute: <path>
Input with id '<id>' in stage '<stage>' is not valid
Module '<stage>/<module>' can never run: its `exclude` rules …
Software environment with id '<id>' is not declared. It should be listed as part of
  the stanza software_environments within the benchmarking YAML header.
Software environment with id '<id>' for metric collector '<id>' is not declared.
Input with id '<id>' for metric collector '<id>' is not valid.
```

`Input with id '…' is not valid` means no upstream stage declares an output
with that id — check the producing stage's `outputs:` ids, not the file paths.

### api_version gates

```
Stage '<id>' uses `provides`, which requires api_version ≥ 0.7.0
  (this benchmark declares 0.4.0).
Stage '<id>' uses `gather`, which requires api_version ≥ 0.7.0 …
Module '<id>' uses `provides`, which requires api_version ≥ 0.7.0 …
Stage '<id>' declares reserved label '<name>' in `provides`. '<name>' is a
  builtin populated by the runtime; choose another name.
```

The reserved set is `{name, dataset}`: the runtime populates `name` (current
module id) and `dataset` (root dataset identity) on every node, so advertising
either would clobber the user's value.

The api comparison is numeric, not lexicographic (`0.10.0` would sort after
`0.6.0`). `APIVersion.latest()` is `0.7.0`, and an absent `api_version:` key
defaults to `0.4.0` — silently.

### Execution context

- below api 0.7.0, `detect_diamond_input_joins()` rejects fan-in input joins,
  because the resolver would linearise them and one branch would silently drop;
  from 0.7.0 the join is legal and resolved;
- `detect_unsatisfiable_excludes()` runs at every api version;
- for `conda`, `docker`, `apptainer` and `envmodules` backends the environment
  entry is checked — for file-backed backends, that the path exists relative to
  the plan's own directory; for `envmodules`, only that the `envmodule` field is
  present (no module system is consulted). `host` backend skips this entirely.

Note the source carries an explicit `ARCHITECTURAL WARNING` on
`validate_execution_context`: filesystem checks in the model layer are marked
for removal to an execution layer. Do not build tooling that depends on where
this check lives.

## `ob validate module`: the check inventory

Only these paths are read (`RepositoryManager.get_repository_files`):
`CITATION.cff`, `LICENSE`, `omnibenchmark.yaml`. Presence — not content — is
additionally recorded for `LICENSE.txt`, `LICENSE.md`, `COPYING`,
`COPYING.txt`, `config.cfg`.

| internal issue type | severity | trigger |
| --- | --- | --- |
| `omnibenchmark_yaml_missing` | error in **both** modes | no `omnibenchmark.yaml` (and no legacy `config.cfg`) |
| `omnibenchmark_legacy_config` | warning | `config.cfg` present instead |
| `citation_missing` | error | file absent or empty |
| `citation_invalid_yaml`, `citation_not_object` | error | unparseable / not a mapping |
| `citation_missing_required_field` | error | one of `cff-version`, `message`, `title`, `authors` |
| `citation_unsupported_version` | error | `cff-version` not in 1.0.3 / 1.1.0 / 1.2.0 |
| `citation_author_missing_given_name` | warning | author entry without a given name |
| `no_license_file` | warning | no licence file **and** no `license:` in CITATION.cff |
| `license_file_empty` | error | `LICENSE` exists but is blank |
| `license_file_no_license_language` | warning | none of *license, copyright, permission, warranty, liability* appears in it |
| `license_in_file_but_not_citation` | warning | LICENSE present, CITATION has no `license:` |
| `license_content_mismatch` | warning | detected licence ≠ the CITATION's SPDX id |
| `omnibenchmark_yaml_invalid_yaml`, `..._not_object` | warning | it does not even parse |
| `omnibenchmark_yaml_missing_entrypoints`, `..._invalid_entrypoints`, `..._missing_default_entrypoint` | warning | no `entrypoints:`, not a mapping, or no `default:` key |
| `omnibenchmark_yaml_invalid_version_format` | warning | `version:` is not a string |

`license:` in CITATION.cff with no LICENSE file is explicitly **not** warned
about — the code comments it as "that's OK". This is why a scaffold passes.

### Two detection quirks

- The structure check looks for `LICENCE`, `LICENCE.txt`, `LICENCE.md` (British
  spelling) among the presence flags, but the presence map never populates
  those keys — a module whose only licence file is `LICENCE` is treated as
  having none. `COPYING` is the mirror image: recorded, never consulted.
- Content checks (empty file, licence language, consistency with the CITATION
  SPDX id) read the path `LICENSE` only. A `LICENSE.md` satisfies the presence
  check and is otherwise unread.

Neither quirk is worth working around: ship a plain `LICENSE`.

### Strict mode

`--strict` does two things. It selects the strict strategy inside the core
validator, which fails fast on the first natural error, and it makes the CLI
count every warning as an error, so the process exits 1. Note that some
warnings are constructed directly with `WARNING` severity and bypass the
strategy — they are still escalated by the CLI layer, which is why the
missing-`default`-entrypoint warning fails a strict run.

Measured behaviour, same binary, same day:

| target | plain | `--strict` |
| --- | --- | --- |
| fresh `ob create module` scaffold (no LICENSE) | exit 0, `✅ Module validation passed` | exit 0 |
| production module, named entrypoints, no `default:` | exit 0, one warning printed | **exit 1** |

## Where artifact validation is going

Design doc `002-module-artifact-validation.md` (Draft) proposes a
benchmark-level `validation.yaml` with a mini-DSL and format-aware loaders, so
that output contracts — non-empty, expected dimensions, required columns, not
all-NA — become a core, machine-parseable check able to disqualify a module's
outputs from a round. Until it lands, output checking is the plan's own
`validators/` convention plus whatever the module asserts about its own work.
