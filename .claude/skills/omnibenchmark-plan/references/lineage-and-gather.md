# Lineage labels, joins and `gather` (api ≥ 0.7.0)

The three 0.7.0 additions answer three different questions:

| Question | Mechanism |
|---|---|
| *Which lineages should this module run on?* | `provides` / `requires` (§3.9) |
| *Which machines can run it?* | `requires_capabilities` (§3.10) |
| *How does one node see many upstream nodes at once?* | joins and `gather` (§3.12) |

Specs: `docs/design/004-yaml-specification.md` §3.9–3.12 (the YAML surface),
`008-filtering.md` (gating rationale and diagnostics), `010-gather.md` (the
gather model), all in `omnibenchmark/omnibenchmark`.

## Lineage labels

A **stage** declares label names; its **modules** bind values; **downstream
modules** gate on them.

```yaml
stages:
  - id: DATA
    provides: [dataset_size, species]
    modules:
      - id: small_human
        provides: {dataset_size: sm, species: human}
      - id: big_mouse
        provides: {dataset_size: lg, species: mouse}
    outputs: [{id: rawdata_h5ad, path: "{dataset}.h5ad"}]

  - id: METHODS
    inputs: [rawdata_h5ad]
    modules:
      - id: cheap
        requires: {dataset_size: sm}        # only on small lineages
      - id: mouse_only
        requires: {species: mouse}
```

Value resolution, most specific first: the module's `provides` binding,
otherwise **the module id**. That default is the zero-config "label = module
identity" pattern — a data stage where each module *is* a dataset needs no
bindings at all, only the stage-level `provides:` list.

Matching is exact string equality and multiple keys are AND-ed. Non-matching
paths are pruned at DAG-construction time, and the run reports what it pruned
(an empty-stage warning, plus a one-line summary of combinations pruned by
`requires` / `exclude` / capability).

### Rules, all enforced at parse time

- **One owner per label.** Two stages declaring the same label is an error: the
  value would depend on where in the lineage you stand.
- **A label may not be named after a stage.** A gather binds a label named
  after its `group_by` stage, so the two namespaces are kept disjoint.
- **`name` and `dataset` are reserved.** The runtime populates them on every
  node — `dataset` = root identity, inherited; `name` = the current module's
  own id, never inherited.
- **A module may only bind labels its stage declares.** An unknown key is an
  error, not a silent fall-through to the module-id default.
- **No `requires` on an initial stage** (no `inputs:` ⇒ no upstream lineage),
  and none on a gather module.

### `requires` vs `exclude`

Both prune. Use `requires` when the axis belongs to **one stage** and you can
name it (`dataset_size`, `species`, `collection`): the intent is written down
once and reads as a scientific statement. Use `exclude` for a **pairwise
incompatibility between two module ids** that no single stage owns — it is
symmetric, transitive across non-adjacent stages, and OR-ed over the list. An
`exclude` entry that is not a module id is silently ignored, so a typo there
prunes nothing and says nothing; a mistyped `requires` value prunes everything
and warns.

Conventional label vocabularies (suggestions, not enforced): `dataset_size`
with `xs|sm|md|lg|xl`; `species: human|mouse`; `treatment: ctrl|drug`.

## Capability gating

```yaml
      - id: pc-rcppml-gpu
        requires_capabilities: [gpu]
```

```bash
ob run benchmark.yaml --with-capability gpu
```

A module is pruned unless every listed capability is declared at run time.
Capabilities describe the **host**, not the data: they do not propagate
downstream and cannot be gated on with `requires`. `ob run -m <module>`
bypasses the gate. Splitting a GPU arm into its own module id (rather than a
parameter) is what lets the same plan run on GPU-less machines — that is the
pattern in the public `omni-scrna/split-stages-plan` plan variants.

There is no negative form (`!gpu`); express "CPU arm" as a separate module.

## Joins: divergent branches meeting again

A stage whose declared inputs come from branches where neither producer is
upstream of the other resolves to **one node with several parents**, one per
compatible combination.

```yaml
  - id: COMPARE
    inputs:
      - method_a.result          # branch A
      - method_b.result          # branch B
```

- Branches pair only when their lineages agree at every stage they share, so a
  join never crosses datasets.
- The join's labels are the **union** over its parents; a downstream
  `requires:` may name a label from any branch.
- Its output directory extends its **deepest** input's and carries a digest of
  the parent set, so two joins sharing a branch cannot collide.
- Below api 0.7.0 the same plan is **rejected at validation time** — the older
  resolver linearises each stage onto one lineage and a branch would silently
  fall out.

No keyword: declaring the inputs is the whole thing.

## Shared output ids

Two stages may declare the same output `id`. That is a contract: for any
consumer of that id, the files are interchangeable.

- Producers **on parallel branches** are alternatives — the consumer expands
  once per producer.
- A producer **downstream of another** shadows it; the upstream file is still
  written, consumers bind to the nearer producer.
- A `gather` ignores shadowing and collects every producer.

Duplicate output ids are therefore *not* a validation error, while duplicate
stage ids and duplicate module ids are.

## `gather`

```yaml
  - id: SUMMARY
    gather:
      - from: clusters_tsv        # output id; every producer is a member
        group_by: DATA            # stage id; partition by ancestor module
    modules:
      - id: summarizer
        software_environment: metrics
        repository: {url: "...", commit: "..."}
    outputs:
      - id: summary_tsv
        path: "{DATA}_summary.tsv"     # the group value
```

`gather:` replaces `inputs:` for that stage.

**Grouping is structural**, over the existing chain: members are partitioned by
the ancestor **module** id of the `group_by` stage, so several parameter
expansions of one upstream module land in the same group. Per-parameter
grouping is not available yet.

**Omit `group_by`** for the global form: every producer in one node, no group
segment in the path. That is exactly what a `metric_collector` is — the two
line up field for field, and at 0.7.0 the gather form is preferable because its
outputs are registered and downstream stages can chain off them.

**Rules:** `from` must have at least one producer; all entries on a stage share
one `group_by` (and "none" counts as one value); `requires` on a gather module
is rejected — move it to the modules producing the gathered id, where it
decides which members are collected; `group_by` may not name a stage called
`name` or `dataset`.

**Membership is computed after pruning**, in this order:

```
exclude → requires → capability gates → gather membership → group_by partition
```

An empty group produces a warning and no node. If a stage has several `gather`
entries and only *some* are populated for a group, that is a plan-time error —
the module's CLI would be missing a flag.

### What the gather module is invoked with

One flag per gather entry, named after the output id, carrying **every** member
path:

```
./<entrypoint> --output_dir <dir> --name summarizer \
    --clusters_tsv /abs/a.tsv /abs/b.tsv /abs/c.tsv \
    [param flags]
```

So a gather module's parser needs `nargs='+'` on that flag — which is what
`ob create module --benchmark <plan> --for-stage <stage>` generates. Member
order is deterministic across runs but carries no meaning; identify members by
path, not position.

### The cut

A gather **cuts the lineage chain**. Its node has no parent; it carries exactly
one label — the `group_by` stage id, bound to the group value — and referencing
any other label in its output template is a plan-time error. Its outputs root
at the stage id:

```
<STAGE>/<group>/<module>/<params>/…        # grouped
<STAGE>/<module>/<params>/…                # global (no group_by)
```

Because the path no longer encodes the contributing nodes, the member list is
written to a `lineage.json` sidecar next to the outputs. Downstream stages
chain off a gather normally (scatter after gather).

## Choosing between them

- Every arm needs its own score → an ordinary stage, `inputs:`.
- One node needs *all* arms of an upstream stage at once (a ranking, a summary
  table, a report) → `gather`, grouped by whatever the summary is "per"
  (usually the dataset stage).
- One node needs *one* result from each of two branches → a join: just declare
  both inputs.
- An arm should only run on part of the grid → `requires` (or `exclude`).
- An arm needs hardware not every machine has → `requires_capabilities`.
