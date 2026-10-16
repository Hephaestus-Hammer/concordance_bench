---
name: omnibenchmark-module
description: "Take an Omnibenchmark module from the `ob create module` scaffold to something that actually runs under a benchmark plan: scaffolding against a stage so the entrypoint's CLI is generated for you, replacing the single `default` entrypoint with named ones, adding envs/ + pixi.toml + LICENSE, fixing the CITATION.cff CHANGE_ME placeholders, writing the stage-contract invariants down as checks, running the module locally with `ob run -m`, and wiring GitHub CI. Use when asked to create a new module, add a stage or entrypoint to an existing one, make a scaffolded module runnable, or work out why a module fails under `ob run`. Also use to find an existing, reusable module in the obcommons registry before writing one, and before writing any module code, to decide with the author which stage, language and outputs are in scope."
---

# From scaffold to a module that runs

A module is a small repository that implements one or more **stages** of a plan.
Its whole job: accept the flags the stage declares, call the tool, write the
declared output files. A good wrapper module is a few dozen lines. If your draft
is growing past that, the design is wrong — stop and say so instead of writing
more.

You are an aide to the module author, not a code generator. Teach the commands
with their flags; never hide `ob` or `pixi` behind a wrapper script. If you
cannot explain in one sentence why a line exists, delete the line.

## 0. Ask before you generate

**First, check whether the module already exists.** obcommons
(`https://omnibenchmark.github.io/obcommons/`) is the community registry of
reusable modules: one YAML entry per module, and the whole registry as JSON at
`https://omnibenchmark.github.io/obcommons/modules.json`. Query that, not the
HTML page:

```bash
curl -s https://omnibenchmark.github.io/obcommons/modules.json \
  | jq '.[] | select(.stage == "data" or (.tags | index("clustering")))
            | {id, stage, category, requires, repository, inputs, outputs}'
```

Each entry has `name`, `description`, `repository.{url,commit}`, `stage`,
`tags`, `category` (`generic` = usable in any benchmark, e.g. downloaders and
report renderers; `biofx` = domain-specific), `authors`, `license`, and
optionally `requires` (minimum omnibenchmark version), `benchmarks`,
`inputs`, `outputs`, `environments`. Source and schema:
`github.com/omnibenchmark/obcommons` (`src/content.config.ts`).

What an entry does **not** tell you:

- **Whether it fits your stage.** `stage` is a free string and `inputs` /
  `outputs` are the ids of the benchmark it was written for. Compare them with
  your stage's contract (see `omnibenchmark-plan`) before reusing it.
- **The entrypoint name.** Read `omnibenchmark.yaml` in the repository at the
  listed commit; the plan's `repository.entrypoint` must match a key there.
- **That it runs.** Registry CI only checks the URL and commit resolve.
  Check `requires` against `ob --version`, then run it (§9).

A match means you add the module to the plan with the listed `url` and
`commit` and skip the rest of this skill. A near match is worth raising with
the author before writing a new one. If the author then writes a reusable
module, suggest adding it to the registry: a pull request adding
`modules/<id>.yaml` (the filename is the id).

Then, these answers change the scaffold command itself, so get them first. Ask as
either/or, not open-ended:

1. **Which plan and which stage?** You need the plan YAML (path or URL) and the
   stage `id` exactly as it appears under `stages:`. Without them the scaffold
   cannot generate the CLI.
2. **Which language?** `run.py`, `run.R` or `run.sh` — that is the whole choice
   list. Pick the language the upstream tool is written in.
3. **One stage or several?** Land the first one before adding a second (§5).
4. **Which upstream function is "the method"?** Name it. A wrapper that calls
   two functions is usually two modules.
5. **Which knobs become plan `parameters` and which are hard-coded?** Anything
   the benchmark is comparing is a parameter; everything else is a constant in
   the code with a comment saying why.
6. **What exactly goes in each declared output file?** Columns, row order, index
   column, dtype. This is the contract, and it is what §6 asserts.
7. **What should happen on degenerate input** (zero cells after filtering,
   fewer features than requested components)? Fail loudly, or emit an empty
   file? There is no default worth guessing.

## 1. Scaffold against the stage — never bare

```bash
ob create module pca-mytool \
  --benchmark ../split-stages-plan/benchmark_conda.yaml \
  --for-stage PCA \
  --non-interactive \
  --name pca-mytool \
  --author-name "Jane Doe" \
  --author-email jane@example.org \
  --description "PCA via mytool" \
  --license MIT \
  --entrypoint run.py
```

| flag | why you care |
| --- | --- |
| `PATH` (first argument) | directory to create; `ob` git-inits it and makes an initial commit |
| `--benchmark` | plan YAML, path or URL. **Must** be given together with `--for-stage` — either one alone exits 1 |
| `--for-stage` | stage `id` from the plan. This is what generates one CLI flag per stage input |
| `--non-interactive` | skip the copier prompts; then `--name`, `--author-name`, `--author-email` are all required |
| `--license` | one of `MIT`, `Apache-2.0`, `GPL-3.0-or-later`, `BSD-3-Clause`, `CC0-1.0`. Writes the SPDX id into `CITATION.cff` — **not** a LICENSE file (§3) |
| `--entrypoint` | `run.py` \| `run.R` \| `run.sh` |

Scaffolding **without** `--benchmark/--for-stage` is the common mistake: you get
a placeholder comment where the stage inputs should be, and you then hand-write
flags that drift from the plan. Always pass the stage.

`ob create module` also prints, when `--benchmark` is a local file, a YAML
snippet to paste under that stage's `modules:`. It does not edit the plan (§8).

## 2. The generated CLI *is* the stage contract

For a stage declaring `inputs: [normalized_selected_h5]`, the generated `run.py`
contains exactly this — nothing else about it is interesting:

```python
    # Required by OmniBenchmark
    parser.add_argument('--output_dir', type=str, required=True, ...)
    parser.add_argument('--name', type=str, required=True, ...)
    # Stage-specific inputs
    parser.add_argument('--normalized_selected_h5', nargs='+', dest='normalized_selected_h5',
                        required=True, help='Input: normalized_selected_h5')
```

Four things to know, and they bite in this order:

- `--output_dir` and `--name` are always passed by Omnibenchmark and must not
  be declared as plan parameters. Per spec §3.5, **`--name` is the module id of
  the current execution**. Write your files into `--output_dir` with the
  filenames the stage's output `path:` template resolves to — so
  `path: "{name}_embedding.tsv"` means `f"{args.name}_embedding.tsv"`, and a
  `{dataset}_…` template means the *initial* stage's module id, which `--name`
  does **not** give you outside the initial stage. (Under api ≤ 0.4 the backend
  passes the dataset as `--name` as a documented workaround, which is why the
  legacy exemplars write `{name}_…` against `{dataset}_…` templates. That
  workaround is marked for removal.) If a plan's template and the filename your
  module writes disagree, the run fails on a missing output — settle this with
  the plan author before writing the writer.
- **Every input flag is `nargs='+'`, so `args.x` is a list even for one file.**
  A single-file input arrives as `['path']`. Index it (`args.x[0]`) or iterate;
  passing the list to a reader is the most common first-run crash.
- Input ids containing dots keep the dot in the flag and get underscores in the
  destination: `data.raw` → `--data.raw`, `args.data_raw`.
- The flag names come from the plan's `inputs:` ids. If the plan changes them,
  re-run `ob create module` into a scratch directory and diff the parser rather
  than editing flags by hand.

R and shell scaffolds carry the same contract (`argparse` `ArgumentParser` with
`nargs="+"`; bash arrays with uppercased variable names).

## 3. Close the gaps the scaffold leaves

The scaffold is not a production module. These are the differences, all of them
verified against a freshly generated module:

| gap | what to do |
| --- | --- |
| `env/` (singular, empty) — and the emitted `.gitignore` ignores `env/`, so even its `.gitkeep` is never committed | delete it; use `envs/<name>.yml` (§4) |
| no `LICENSE` file, though the help text claims a LICENSE check | add the full license text matching the SPDX id in `CITATION.cff` |
| no `pixi.toml` | see §4 |
| `.gitignore` has no `.pixi/`, so the first `pixi install` puts the whole environment in `git status` | append `.pixi/` (keep `pixi.lock` tracked) |
| `entrypoints: {default: run.py}` | replace with named entrypoints, one per stage served (§7) |
| `CITATION.cff` has `https://github.com/CHANGE_ME/<module>` in `url` and `repository-code`; a one-word `--author-name` yields `family-names: "Ben"`, `given-names: ""` | fix both by hand before the first push |
| no CI workflow | §9 |

**`ob validate module` passes on the untouched scaffold — plain and with
`--strict`, exit 0 both times.** It is a metadata check, not evidence that the
module is right. Treat a green validate as "nothing structural is missing", and
see the `omnibenchmark-validate` skill for what it does and does not look at.

## 4. Environment: one line here, detail elsewhere

A module needs a `pixi.toml` and an exported `envs/<name>.yml` — the conda YAML
is what a plan's `software_environments` entry ultimately consumes. Generate it
with `pixi run export-env`; never hand-edit the export.

Authoring the `pixi.toml`, pinning, and harmonising dependency constraints
across modules belong to the **`omnibenchmark-packaging`** skill. Do not
re-derive them here.

## 5. One increment at a time

Small, complete, reviewable increments beat a long branch:

- **Land one working entrypoint before adding the second.** A module that serves
  one stage correctly is mergeable; a half-finished module serving four is not.
- Keep each diff small enough that a biologist can review it in one sitting.
- Say what the *next* increment will be rather than doing it in the same change.
- Prefer editing the generated scaffold in place over replacing it — the diff is
  the unit of review.

## 6. Write the invariants down

Two different checks, both cheap, both worth it:

**Environment check** — the `check` task in the exemplar modules is an import
smoke test and nothing more (`python check.py` imports the runtime packages and
prints `OK`; `Rscript check.R` loads the libraries and prints `OK`). Run it
after `pixi install` to confirm the environment resolved.

**Contract invariants** — the assertions that earn their place encode the stage
contract, because they are what a reviewer cannot check by eye:

```python
emb = ...                                   # cells x components
assert emb.shape[0] == adata.n_obs, (emb.shape, adata.n_obs)   # no cells lost
assert emb.shape[1] == args.n_components                        # requested width
assert list(cell_ids) == list(adata.obs_names)                  # identifiers survive
```

```r
stopifnot(nrow(embedding) == ncol(m))          # one row per cell
stopifnot(!anyNA(embedding))
```

Put them next to the code they guard, or in `check.{py,R}` when they need the
written file. Degenerate cases the author named in §0 get one assertion each.

This is not a licence to generate a test suite nobody asked for. A test that
encodes an invariant the author named is documentation; a test asserting that a
function returns what it just returned is noise. No defensive `try/except`
blankets, no logging framework, no docstrings on trivial functions.

## 7. Name the entrypoints

The plan binds a module by entrypoint name:

```yaml
        repository:
          url: https://github.com/<org>/<module>
          commit: b41bf43
          entrypoint: pca
```

so `omnibenchmark.yaml` must have that key:

```yaml
entrypoints:
  default: pca.py   # keep this: alias for the primary entrypoint
  pca: pca.py
  knn: knn.py
```

An entrypoint value may carry a prefix command (the exemplars use
`pca-prof: prof.sh pca.py` for a profiled variant).

**Check the file name against the standard library before using it.** Naming
the script after its stage or step is the convention, but a Python script's
directory goes first on `sys.path`, so `select.py`, `random.py`, `types.py`,
`signal.py` or `io.py` shadows the stdlib module and breaks imports
deep inside numpy or anndata with an error that never names your file. Prefix
it instead — `scanpy` uses `feat-select.py` for exactly this step. Check with
`python -c "import sys; print('<name>' in sys.stdlib_module_names)"`.

**Always keep a `default:` alias pointing at the module's primary entrypoint.**
Without it `ob validate module` warns `omnibenchmark.yaml 'entrypoints' is
missing required 'default' key`, and `--strict` turns that warning into a
failure — exit 1, measured on `scanpy`, `5-pca-irlba-r` and `metrics`. Adding
the alias takes the same module to exit 0 (verified), which is what makes
`--strict` usable in CI at all. It costs one duplicated line and buys a CI
signal that would otherwise have to stay off.

This is a workaround for a validator that assumes every module has one
entrypoint, not a design statement: the alias duplicates whichever named
entrypoint you consider primary. Revisit it if the upstream check learns about
named entrypoints.

## 8. Register the module in the plan

Paste the snippet `ob create module` printed under the stage's `modules:`, then
fix what it guessed:

```yaml
  - id: pca-mytool
    name: PCA via mytool
    software_environment: scanpy      # inferred from sibling modules — check it
    repository:
      url: /local/path/to/pca-mytool  # replace with the public URL
      commit: ""                      # pin a commit before merging
      entrypoint: pca                 # add this: the snippet omits it
```

The snippet is emitted only for a local plan file, `software_environment` is
inferred from the other modules in that stage (it says so when it has to guess),
and `commit: ""` plus a local `url:` only work with `ob run --dirty`. Plan-side
editing is the `omnibenchmark-plan` skill's territory.

## 9. Run it, three ways, in this order

```bash
# 1. Directly — fastest loop, and it teaches the author the contract
pixi run python pca.py --output_dir out --name smoke \
  --normalized_selected_h5 /path/to/input.h5 --n_components 10 --random_seed 42

# 2. Under the plan, module-scoped dev run
ob run ../split-stages-plan/benchmark_conda.yaml -m pca-mytool --dirty --cores 4
```

`-m/--module` prunes every stage after the target module's stage and keeps only
the first upstream input × parameter expansion, so it is a fast smoke test, not
a benchmark. `--dirty` allows local-path module references with uncommitted
changes (development only); `--unpinned` does the same for branch refs on remote
repos; `-d/--dry` generates the Snakefile without executing; `--out-dir` moves
the default `out/`.

Third: run the plan's own output validators against what you produced, before
you push. See `references/ci-and-plan-validators.md`.

## Pitfalls

- Treating a green `ob validate module` as correctness. It is metadata only.
- Forgetting `nargs='+'` and handing a one-element list to a file reader.
- Keeping `entrypoints: default:` *and* adding named ones, then wondering which
  the plan used — the plan uses the name in `repository.entrypoint`.
- Writing an output filename that does not match the stage's `path:` template
  (see §2) — the job fails on a missing output, not on anything your code did.
- Copying a module's plan-facing metadata from the omni-scrna exemplars: those
  repos are on `api_version: "0.4.0"` (§ exemplars below).

## References

- `references/scaffold-reference.md` — exactly what `ob create module` emits,
  the generated parser for all three languages, flag derivation, the plan
  snippet, and the CITATION.cff placeholders.
- `references/ci-and-plan-validators.md` — GitHub CI for a module and running a
  plan's `validators/` locally. Marks what is core `ob` and what is omni-scrna
  house style.
- `references/exemplars.md` — three real modules read end to end: a minimal R
  module, a multi-entrypoint Python module, a multi-language one. Structure and
  wrapper logic only; their plan metadata is legacy.
- `omnibenchmark-cli` skill for exact flags; `omnibenchmark-packaging` for pixi;
  `omnibenchmark-validate` for what validation checks; `omnibenchmark-plan` for
  the plan side; `omnibenchmark-wrapping` for adapting an upstream tool.
