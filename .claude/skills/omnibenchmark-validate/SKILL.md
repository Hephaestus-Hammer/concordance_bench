---
name: omnibenchmark-validate
description: "What `ob validate plan` and `ob validate module` actually check — and, more usefully, what they do not. Use when a validation command passes or fails and you need to know what that means, when reading a Pydantic or model-layer error from a benchmark plan (duplicate ids, unknown input, undeclared software environment, `provides`/`gather` requiring api_version 0.7.0), when deciding whether `--strict` is safe to turn on in CI, or when someone offers a green `ob validate` as evidence that a module or plan is correct. Also use to order local checks before pushing to CI."
---

# `ob validate` — a structure gate, not a correctness gate

Both subcommands answer one question: *is this file shaped like a plan / is
this directory shaped like a module?* Neither runs your code, and neither looks
at a single output file. Say that out loud whenever a green validate is offered
as evidence of anything else.

```bash
ob validate plan benchmark.yaml
ob validate module [PATH] [--strict]      # PATH defaults to .
```

## `ob validate plan`

Loads the YAML into the Pydantic `Benchmark` model and then validates the
execution context against the directory the plan file lives in. Exit 0 with
`✅ Benchmark YAML plan validation passed.`, or exit 1 with one error block.

It checks, in order:

1. **YAML syntax**, then **Pydantic structure** — required fields, types,
   enum values. Missing fields are reported as
   `Missing required field: '<path>'`, other problems as `Field '<path>': <msg>`.
2. **Model consistency** — duplicate stage / module / output ids; an output
   `path` that is empty or absolute; an `inputs:` id no upstream stage
   produces; a module whose `exclude` rules make it unreachable; a
   `software_environment` id that is not declared in the header.
3. **api_version gates** — `Stage.provides`, `Stage.gather` and
   `Module.provides` each raise below 0.7.0, naming the offending stage or
   module; a `provides` label may not be one of the reserved runtime labels
   `name` / `dataset`.
4. **Execution context** — below api 0.7.0, fan-in (diamond) input joins are
   rejected up front; then, for every non-`host` backend, the environment file
   named in `software_environments` must actually exist relative to the plan's
   directory.

It does **not**:

- fetch or inspect any module repository (a bogus `url:`, an unreachable
  `commit:`, an `entrypoint:` that exists in no module — all pass);
- verify that a module's `omnibenchmark.yaml` declares the entrypoint the plan
  binds;
- resolve or solve the conda environments it just confirmed the paths of;
- execute, dry-run, or generate a Snakefile (that is `ob run --dry`);
- look at outputs.

**The silent one:** a plan with no `api_version:` key parses as `0.4.0`, the
legacy contract — and validates cleanly. `ob create benchmark` emits exactly
such a plan. Absence of an error here is not evidence of a current plan; grep
for the key.

Deprecation warnings are reformatted and printed but never fail: an unquoted
version-like scalar (`Field 'x' should be quoted in YAML`), the old `entries:`
form inside `inputs`, and the old `values:` parameter format. They carry a line
number when one is available. Treat them as migration work, not noise.

## `ob validate module`

Reads exactly three files from the module directory — `CITATION.cff`,
`LICENSE`, `omnibenchmark.yaml` — plus a presence check for a few alternative
names. Everything else in the repository is invisible to it.

| checked | how it is reported |
| --- | --- |
| `omnibenchmark.yaml` missing | **error**, always, even in default mode |
| `CITATION.cff` missing, empty, unparseable, not a mapping | error |
| `CITATION.cff` missing `cff-version` / `message` / `title` / `authors`, or an unsupported `cff-version` | error |
| `LICENSE` file absent **and** no `license:` in CITATION.cff | warning |
| `LICENSE` present but empty | error; present with no licence-like wording | warning |
| `license:` in CITATION.cff disagrees with the detected LICENSE text | warning |
| `entrypoints:` missing, not a mapping, or **missing the `default` key** | warning |
| `version:` in omnibenchmark.yaml not a string | warning |

Default mode prints warnings and exits 0. `--strict` turns every warning into a
failure, exit 1. `✅ Module validation passed` appears only when there were
neither errors nor warnings.

Three consequences that matter in practice:

- **A fresh `ob create module` scaffold passes, plain and `--strict`, exit 0 —
  with no LICENSE file.** The LICENSE warning is suppressed because the
  generated `CITATION.cff` carries `license: MIT`. Validation being green on a
  scaffold is the clearest possible statement of what it measures.
- **Any module with named entrypoints and no `default:` fails `--strict`** with
  `omnibenchmark.yaml 'entrypoints' is missing required 'default' key` (exit 1;
  measured on `scanpy`, `5-pca-irlba-r` and `metrics`). The house answer is to
  keep a `default:` alias pointing at the primary entrypoint — adding one takes
  the same module to exit 0 (verified), which is the only thing that makes
  `--strict` viable in CI today. Treat a module without the alias as a defect to
  fix, not a reason to run CI non-strict.
- The validator never checks that an entrypoint's script exists, is
  executable, or accepts the stage's flags.

## Local, then CI

Run the cheap-and-informative checks before the cheap-and-uninformative one:

1. the entrypoint on one small input — does it produce the declared file?
2. the contract assertions in the module (`omnibenchmark-module` §6);
3. `ob run <plan> -m <module-id> --dirty` — the module under the real plan;
4. the plan's output validators over `out/`;
5. `ob validate plan` and `ob validate module` — seconds, and the only two
   steps CI will repeat;
6. push. CI (the `validate-module` action, omni-scrna house style) re-runs
   step 5 on a clean checkout, nothing more.

A plan repository's own CI mirrors this: a `validate-plan` job on push and
pull request, wrapping `ob validate plan`.

## Reporting a validation result

Say which command ran, what it covers, and what remains unchecked. "Metadata
validation passes; the module has not been executed against the stage" is an
honest sentence. "The module is valid" is not.

## References

- `references/checks-in-detail.md` — the check inventory with the internal
  issue types and severities, the exact strings the model layer emits, the
  quirks of licence-file detection, and how to read a Pydantic error path.
- `omnibenchmark-cli` for flags; `omnibenchmark-module` for the module side;
  `omnibenchmark-plan` for fixing plan errors.
