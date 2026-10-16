# What `ob create module` actually emits

Everything here was produced by running the command against a real plan and
reading `omnibenchmark/cli/create.py` and `omnibenchmark/templates/module/` in
`omnibenchmark/omnibenchmark`. Re-verify with `ob create module --help` if the
installed version differs from the one the `omnibenchmark-cli` reference is
stamped with.

## The command

```
ob create module PATH [OPTIONS]
  -b, --benchmark TEXT   path or URL to a plan YAML
  --for-stage TEXT       stage id (requires --benchmark)
  --no-input | --non-interactive
  --name --author-name --author-email --description
  --license [MIT|Apache-2.0|GPL-3.0-or-later|BSD-3-Clause|CC0-1.0]
  --entrypoint [run.R|run.py|run.sh]
```

`--benchmark` and `--for-stage` are validated as a pair:

```
--for-stage requires --benchmark to be specified
--benchmark requires --for-stage to be specified
```

Either alone exits 1. With `--non-interactive` (or any of the mandatory flags),
`--name`, `--author-name` and `--author-email` must all be supplied.

## The emitted tree

```
CITATION.cff
omnibenchmark.yaml
README.md
.gitignore
run.py              # or run.R / run.sh
src/main.py         # or src/main.R / src/main.sh
docs/.gitkeep
env/.gitkeep        # never committed — see below
.git/               # git init + an initial commit, done by the CLI
```

`git ls-files` in a fresh scaffold returns `.gitignore`, `CITATION.cff`,
`README.md`, `docs/.gitkeep`, `omnibenchmark.yaml`, `run.py`, `src/main.py`.
`env/` is absent: the emitted `.gitignore` lists `env/` under "Virtual
environments", so the directory the template just created is ignored by the
repository the template just initialised (`git status --ignored` shows `!! env/`).
Production modules use `envs/<name>.yml`, which the ignore rule does not match.

`omnibenchmark.yaml` is three lines:

```yaml
# OmniBenchmark Module Configuration

entrypoints:
  default: run.py
```

## The generated CLI

With `--benchmark PLAN --for-stage PCA` on a stage declaring
`inputs: [normalized_selected_h5]`, the *only* difference from a bare scaffold
is that a placeholder comment is replaced by one flag per input:

```python
def parse_args():
    parser = argparse.ArgumentParser(description='OmniBenchmark module')

    # Required by OmniBenchmark
    parser.add_argument('--output_dir', type=str, required=True,
                       help='Output directory for results')
    parser.add_argument('--name', type=str, required=True,
                       help='Module name/identifier')
    # Stage-specific inputs
    parser.add_argument('--normalized_selected_h5', nargs='+', dest='normalized_selected_h5', required=True,
                       help='Input: normalized_selected_h5')

    return parser.parse_args()
```

Without the stage you get this instead, and you are on your own:

```python
    # Add your custom input arguments here
    # Example:
    # parser.add_argument('--input', type=str, help='Input file')
```

### Flag derivation

From `create.py`: each input id becomes `{"id": input_id, "var_name":
input_id.replace(".", "_"), "var_name_upper": <that>.upper()}`. So

| plan input id | CLI flag | Python `dest` | R `dest` | bash variable |
| --- | --- | --- | --- | --- |
| `normalized_selected_h5` | `--normalized_selected_h5` | `normalized_selected_h5` | same | `NORMALIZED_SELECTED_H5` |
| `data.raw` | `--data.raw` | `data_raw` | `data_raw` | `DATA_RAW` |

Every input flag is generated with `nargs='+'` / `nargs="+"` / a bash array, so
**values are always collections**, including single-file inputs.

### R and shell

`run.R` uses the `argparse` R package:

```r
parser$add_argument("--normalized_selected_h5", dest="normalized_selected_h5",
                   type="character", nargs="+", required=TRUE,
                   help="Input: normalized_selected_h5")
```

`run.sh` hand-rolls a `while [[ $# -gt 0 ]]` loop, collecting each input flag's
values into an uppercase array until the next `--flag`.

All three source a `src/main.{py,R,sh}` holding a `process_data` stub that
writes `<output_dir>/<name>_result.txt`. That stub is scaffolding, not a
starting point to extend — for a wrapper module it is usually shorter to write
the real work in the entrypoint and delete `src/main.*`, keeping `src/` for
code that is genuinely shared between entrypoints.

## CITATION.cff

```yaml
cff-version: 1.2.0
message: "If you use this module in your publication, please cite as below."
type: software
title: "Demo Pca"
authors:
  - family-names: "Doe"
    given-names: "Jane"
    email: "jane@example.org"
date-released: "2026-09-23"
version: "1.0.0"
license: MIT
url: "https://github.com/CHANGE_ME/demo-pca"
repository-code: "https://github.com/CHANGE_ME/demo-pca"
```

Two fixes, always:

- both `CHANGE_ME` URLs (they also recur in a `references:` block at the end of
  the file, and in `README.md`);
- the author split, which is `author_name.split()[-1]` for `family-names` and
  the rest for `given-names`. A one-word `--author-name Ben` yields
  `family-names: "Ben"`, `given-names: ""`; "Ana Maria Ruiz" yields
  `given-names: "Ana Maria"`.

`license:` here is what makes `ob validate module` stop asking for a LICENSE
file — the structural check only warns about a missing LICENSE when the
CITATION also lacks a license field. Add the real LICENSE text anyway.

## The plan snippet

When `--benchmark` points at a **local file**, the command ends by printing a
snippet to paste yourself (it never edits the plan):

```
Generating module YAML snippet for: …/benchmark_conda.yaml
Multiple software environments in use: {'scanpy', 'scrapper'}
Defaulting to 'scanpy' - please update if needed

Add the following under the 'modules:' section of the 'PCA' stage:

  - id: demo-pca
    name: Demo Pca
    software_environment: scanpy
    repository:
      url: /abs/path/to/demo-pca
      commit: ""
```

Note what it does *not* emit: `repository.entrypoint`. Add it, matching a key in
your `omnibenchmark.yaml`, or the plan will not know which script to run. Also
replace the local `url:` with the published one and pin `commit:` before the
module is used in anything but a `--dirty` development run.
