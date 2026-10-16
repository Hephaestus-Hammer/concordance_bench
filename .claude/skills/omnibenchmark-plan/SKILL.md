---
name: omnibenchmark-plan
description: "Read, write, validate and migrate an Omnibenchmark benchmark plan (the benchmark YAML) at api_version 0.7.0. Load this when you open or edit a benchmark.yaml, when `ob create benchmark` has just scaffolded one, when deciding what is a stage versus a parameter, when wiring stage inputs/outputs or output path templates, when adding `provides`/`requires` lineage labels, `requires_capabilities` or a `gather` fan-in, when `ob validate plan` fails, when a plan declares api_version 0.4.0 (or none at all) and has to be migrated, or when an author needs to stay on the legacy 0.4.0 contract deliberately. Covers the document structure, software environments, module repository pinning, parameter grids, the wildcard vocabulary, and the stage contract a module must satisfy."
---

# The benchmark plan

The plan is one YAML file. It declares *what* the benchmark computes — stages,
the modules that implement them, the files they exchange — and nothing about
*how* any module works. `ob` compiles it into a Snakemake workflow.

Authority for everything here is the spec, `docs/design/004-yaml-specification.md`
in `omnibenchmark/omnibenchmark` (Accepted, v7), and the Pydantic model that
enforces it, `omnibenchmark/model/benchmark.py`. Where this skill says
"verified", it was checked against that model. Do not invent a key: if it is not
in 004 and not a field on the model, it does not exist.

## First move on any plan: check `api_version`

```bash
grep -n '^api_version' benchmark.yaml
```

**A plan with no `api_version` key silently parses as `0.4.0`** (the model's
field default; verified). `ob create benchmark` emits a plan with **no
`api_version` key at all**, so a freshly scaffolded plan lands on the legacy
contract without saying so.

The convention for this pack is **0.7.0 everywhere, migrate on sight**. So:

1. If the key is missing or below `"0.7.0"`, say so and offer the bump.
2. `api_version: "0.7.0"` — quoted; it is a string, and an unquoted `0.7.0` is
   fine but `0.4` would be a different (unsupported) value.
3. Re-validate, then read `references/migration-0.4-to-0.7.md` before telling
   the author the migration is done. One behavioural change bites silently: at
   `api_version <= 0.4.0` the runtime passes the **dataset** id as `--name`,
   and from `0.5.0` it passes the **module's own** id. A module that builds its
   output filename from `--name` writes a different filename after the bump.

### Legacy 0.4.0 compatibility — opt-in, never the default

Sometimes staying on the legacy contract is the right call: collaborators pinned
to an older `ob`, a plan mid-review, or a fleet of modules that still build
filenames from `--name` and cannot all be fixed in one change. That is a
decision for the benchmark author, so **offer it, never assume it**.

The rule is asymmetric on purpose:

- **Default:** propose `0.7.0` on every plan you touch, and say what the bump
  changes.
- **On request:** if the author says they need 0.4.0 compatibility, keep
  `api_version: "0.4.0"` — written explicitly, not left absent — and say in one
  line why it is pinned and what unpins it. An absent key and a deliberate
  `"0.4.0"` behave identically to the parser but read very differently to the
  next person.

Working under a 0.4.0 pin means:

- `provides`, `gather` on a stage, and `provides` on a module are rejected
  outright by the model. Do not write them, and do not suggest designs that
  need them (shared output ids resolved by lineage, label-based fan-in).
- `--name` carries the **dataset** id, so `{dataset}`-shaped output templates
  and modules that write `<name>_<suffix>` agree with each other. This is the
  main reason a legacy pin is coherent rather than merely old.
- `requires_capabilities` and `Module.requires` parse at 0.4.0 — the model does
  not gate them despite §3.10 — but they are 0.7.0 features on paper. Using
  them under a pin works today and is a bet on the gate never being enforced;
  flag that trade rather than reaching for them silently.
- Say plainly that this is a holding position. Record the unpin condition
  (collaborators upgraded, modules' filename contract settled) where the author
  will see it — a comment above the key is enough.

Never migrate a pinned plan back to 0.7.0 without asking, and never leave a plan
on 0.4.0 by omission and call it a decision.

## Ask before you write

These are the author's decisions, not yours. Ask them as either/or questions,
and ask before generating YAML — a wrong guess baked into a plan propagates
into every module written against it.

- **Is this axis a stage or a parameter?** A *stage* is a step with its own
  file contract that different tools can implement (normalisation, clustering).
  A *parameter* is a knob on one implementation (`n_components`, `random_seed`).
  Two tools that read and write the same files are two modules in one stage,
  not two stages. If the candidate would have identical `inputs`/`outputs` to an
  existing stage, it is a module or a parameter.
- **Does this value belong in the plan or in the module?** In the plan if the
  benchmark varies it or a reader must see it to interpret results; in the
  module if it is an implementation detail with one right value. Anything in
  `parameters:` becomes part of the output path hash and a column in the
  results — so plan-level parameters are the axes of the study, not the tool's
  defaults.
- **What exactly is each declared output file?** Name, format, and the
  invariant that makes it comparable across modules (same row order? cell ids
  as row names? one row per sample?). That answer is the stage contract; write
  it down (`references/stage-contract.md`) before any module is written.
- **One output id or two?** Two stages may deliberately share an output id —
  that is a contract saying the files are interchangeable for any consumer
  (§3.11). Ask whether the author means "interchangeable" or "two different
  things that happen to look alike".
- **Does this arm need every dataset?** If not, the answer is `exclude:` or a
  `requires:` lineage gate, not a second plan.

## Document structure

```yaml
id: my_benchmark                    # required; identifier, must not start with a digit
name: My Benchmark                  # optional, human-readable
description: One line about it      # optional
benchmarker: "Name <email>"         # required
version: "0.1.0"                    # required; strict semver x.y or x.y.z, quoted
api_version: "0.7.0"                # optional but ALWAYS write it (default is 0.4.0)

provenance:                         # optional, informational only (§9)
  canonical_url: https://example.org/plan.yaml
  derived_from: upstream-benchmark-id
  subset_of: <summary_hash of parent>

storage:                            # optional; only needed for --use-remote-storage
  api: S3                           # MINIO is accepted but deprecated
  endpoint: https://storage.example.org
  bucket_name: my-benchmark

software_backend: "conda"           # required: apptainer | conda | docker | envmodules | host
software_environments: {...}        # required in practice (see below)
stages: [...]                       # required, >= 1
metric_collectors: [...]            # optional, legacy fan-in; prefer `gather` at 0.7.0
```

Field-by-field types, every validator and its exact error text:
`references/plan-reference.md`.

## Software environments

A mapping from environment id to a backend definition. The id is what modules
reference.

```yaml
software_backend: "conda"

software_environments:
  scanpy:
    name: scanpy multi-module        # free text
    conda: envs/scanpy.yml           # path relative to the plan file
  gpu_stack:
    description: RAPIDS image
    apptainer: docker://nvcr.io/nvidia/rapidsai:24.10
```

- The key that matters is the one matching `software_backend`: `conda:`,
  `apptainer:`, `docker:`, `envmodule:`, or nothing for `host`.
- For any backend other than `host`, `ob validate plan` **checks the file
  exists** relative to the plan directory and fails if it does not (verified).
- If the plan declares **exactly one** environment, modules may omit
  `software_environment:` and it is filled in automatically (verified). With
  two or more, an omitted or unknown reference is a validation error.
- `host` means no isolation. Use it for a smoke test, not for a published
  benchmark.

## Stages and modules

```yaml
stages:
  - id: PCA
    inputs:
      - normalized_selected_h5          # output ids produced upstream
    outputs:
      - id: pcas_tsv
        path: "{dataset}_pcas.tsv"      # filename only, no directories
    resources:                          # optional (§7): cores, mem_mb, disk_mb, runtime, gpu
      cores: 8
    modules:
      - id: pc-scanpy
        name: "scanpy PCA"              # optional, human-readable
        software_environment: scanpy
        repository:
          url: https://github.com/<org>/<module-repo>
          commit: 53eb292               # pin: commit sha, tag, or branch
          entrypoint: pca               # optional: a key from the module's omnibenchmark.yaml
        parameters:
          - n_components: 50
            random_seed: 42
            solver: arpack
```

- **Stage ordering is topological, not positional** (§3.3): dependencies come
  from `inputs`/`outputs`, so a stage may be declared before its producer.
  Declaration order only breaks ties, and the sort is stable.
- **A stage may consume any upstream stage's output**, not just its immediate
  predecessor.
- `repository.commit` should be an immutable sha for anything published. A
  branch name works only with `ob run --unpinned`, which resolves it to HEAD at
  run time — development only.
- `repository.entrypoint` names one entrypoint key from the module's own
  `omnibenchmark.yaml`; omitted, it is `default`. This is how one module repo
  serves several stages.
- Before adding a module, look for a reusable one in the obcommons registry
  (`https://omnibenchmark.github.io/obcommons/modules.json`); its entries give
  `repository.url` and `commit` ready to paste. How to query it and what an
  entry does not guarantee: `omnibenchmark-module` skill, §0.
- `id` values must not start with a digit — they become Snakemake rule names
  (verified error message in `references/plan-reference.md`).

## Parameters and grid expansion

Each list item is a dict of flags. **Any list-valued entry expands
combinatorially**:

```yaml
parameters:
  - solver: [arpack, randomized]     # 2
    n_components: [10, 50]           # x 2
    random_seed: 42                  # = 4 runs
```

Resolves to `--solver arpack --n_components 10 --random_seed 42`, and so on.
Every item in the list should carry the **same key set** — mixed key sets are a
common typo and `ob` prints a WARN naming the offending keys (verified).

Each combination gets an 8-character SHA-256 hash of its sorted `key=value`
string, which becomes a path segment; a module with no parameters gets the
literal segment `default`. `--name` and `--output_dir` are supplied by the
runtime and must never appear in `parameters:`.

## Inputs, outputs and the path vocabulary

A stage declares `outputs:` as `{id, path}`. `path` is a **filename template,
not a path** — a `/` in it triggers a deprecation warning (verified). Downstream
stages name the *id* in their `inputs:`; `ob` resolves it to the producer's
file and passes it as `--<output_id> <absolute path>`.

Placeholders available in an output template at 0.7.0 (verified against the
template engine):

| Placeholder | Resolves to |
|---|---|
| `{dataset}` | the root (initial-stage) module id, inherited down the lineage |
| `{name}` | **the current module's own id** |
| `{<label>}` | any `provides` label in the lineage; a gather's group key |
| `{module.id}`, `{module.stage}`, `{module.name}` | this node |
| `{module.parent.id}`, `{module.parent.stage}` | the anchor parent |
| `{params.<key>}` | one of this node's parameter values |

An unresolved placeholder is an error that lists the names that *were*
available — read that list rather than guessing.

Where the files land, and what the module is actually invoked with, is the
stage contract: **`references/stage-contract.md`**. Read it before writing a
plan that other people will implement modules against.

## The 0.7.0-only features

Each of these raises a `ValueError` naming the offending stage or module when
`api_version < 0.7.0` (verified), except where noted.

### `provides` / `requires` — lineage labels (§3.9, api >= 0.7.0)

A stage declares label *names*; its modules bind *values*; downstream modules
gate on them.

```yaml
  - id: DATA
    provides: [dataset_size]              # stage owns the axis
    modules:
      - id: small_set
        provides: {dataset_size: sm}      # this module's value
  - id: METHODS
    inputs: [rawdata_h5ad]
    modules:
      - id: cheap_method
        requires: {dataset_size: sm}      # runs only on sm lineages
```

Rules that bite, all parse-time errors: a label is owned by exactly one stage;
a label may not be named after a stage id (one namespace, because a gather
binds a label named after the stage it groups by); a module may only bind
labels its stage declares; `requires` on a module in an initial stage has no
lineage to match and is rejected. Unbound labels default to the module id.

**Reserved labels:** `name` and `dataset` are populated by the runtime on every
node and may not be declared in `provides` — advertising either would clobber
the builtin.

`Module.requires` is *not* api-gated in the model today (only `Stage.provides`,
`Module.provides` and `Stage.gather` are; verified) — but it is meaningless
without `provides`, so treat the whole feature as 0.7.0.

### `requires_capabilities` — host gating (§3.10, api >= 0.7.0)

```yaml
      - id: pc-gpu
        requires_capabilities: [gpu]
```

Pruned unless every listed capability is passed at run time:

```bash
ob run benchmark.yaml --with-capability gpu --with-capability large_mem
```

Capabilities are facts about the *host*, never lineage labels: they do not
propagate and cannot be gated on with `requires`. `ob run -m <module>` bypasses
the gate. (Spec §3.10 marks this 0.7.0+; the model does not currently enforce
that gate — verified. Write it in 0.7.0 plans only regardless.)

### `gather` — fan-in (§3.12, api >= 0.7.0)

```yaml
  - id: SUMMARY
    gather:
      - from: clusters_tsv          # collect EVERY producer of this output id
        group_by: DATA              # partition by ancestor module of this stage
    modules: [...]
    outputs:
      - id: summary_tsv
        path: "{DATA}_summary.tsv"  # the group value
```

`gather:` replaces `inputs:` for that stage. Omitting `group_by` collects every
producer into a single node (the global form). All entries on one stage must
share one `group_by`, and "no `group_by`" counts as one. `requires` on a gather
module is rejected — put it on the modules producing the gathered id instead.
A gather **cuts the lineage chain**: its node carries exactly one label (the
`group_by` stage id), and its outputs root at the stage id.

The other 0.7.0 change needs no keyword: a stage whose inputs come from
**divergent branches** is a join, resolved into one node with several parents.
Below 0.7.0 the same plan is rejected up front by `ob validate plan`.

Full semantics, path layout and the `lineage.json` sidecar:
`references/lineage-and-gather.md`.

## Validate — run the real command

```bash
ob validate plan benchmark.yaml
```

That is the whole invocation: one argument, the path to the plan, and no flags
but `--help` (verified against the installed binary). The file must end in
`.yaml`/`.yml`. It checks YAML syntax, required fields and types, that every
`inputs:` id is produced by some stage, that every `software_environment:`
reference resolves, that the environment files exist on disk, that `exclude:`
rules leave at least one viable lineage, and — below 0.7.0 only — that no stage
joins divergent branches.

What it does **not** check: that any repository URL or commit exists, that a
module implements the stage contract, or that an output file will be produced.
Passing `ob validate plan` means the document is well formed, not that the
benchmark runs.

Then look at what you built, before running anything:

```bash
ob describe topology benchmark.yaml --show-params --compact-params   # mermaid
ob run benchmark.yaml --dry                                          # generate out/Snakefile only
ob run benchmark.yaml --dry --until PCA                              # stop at a stage
```

`--dry` writes the fully materialised `out/Snakefile` with every wildcard
resolved. Reading one rule in it answers "what will my module actually be
called with" definitively — see `references/stage-contract.md`.

## Edit plans in place, in small increments

A plan is reviewed by biologists. Change one thing at a time, keep the diff
small enough to read in one sitting, and validate after each change:

1. Bump `api_version` and validate. Nothing else in the same commit.
2. Add one stage — with its outputs and one module — and validate.
3. Add the second module to that stage once the first runs.
4. Widen a parameter grid last, when the arm is known to work.

Say what the next increment will be rather than doing it in the same change.
Preserve the author's comments and ordering; a plan's comments are usually the
only record of why an arm exists.

## References

- `references/plan-reference.md` — every top-level and nested field, its type,
  its validator, and the exact error text when it fails.
- `references/stage-contract.md` — how a stage's declared outputs bind to the
  module CLI: the invocation, the output tree, the JSON stage schemas and the
  `validators/<stage>/<output>/validate.{R,py}` layout.
- `references/lineage-and-gather.md` — `provides`/`requires`, joins and
  `gather` in depth, with the path layout each produces.
- `references/migration-0.4-to-0.7.md` — the migration recipe and a worked
  example on a real 21-stage plan.

Companion skills: `omnibenchmark-cli` (resolve any `ob` flag against the
installed binary — do that rather than trusting a flag quoted here),
`omnibenchmark-module` (writing the module that satisfies a stage).
