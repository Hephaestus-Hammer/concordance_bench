---
name: omnibenchmark-cli
description: "Ground truth for the `ob` (Omnibenchmark) command-line interface: how to discover the installed version's commands and flags instead of guessing them. Load this before running any `ob` command — `ob create benchmark`, `ob create module`, `ob validate plan`, `ob validate module`, `ob run`, `ob storage`, `ob software` — and whenever a command fails with an unknown-option or unknown-command error. Omnibenchmark is alpha software whose CLI changes between releases."
---

# The `ob` CLI

Omnibenchmark is alpha software. Its CLI surface changes between releases, and a
flag recalled from memory or copied from a blog post is more likely to be wrong
than right. **Resolve every command against the installed binary before you run it.**

## Freshness protocol

Run this at the start of any session that will invoke `ob`:

```bash
ob --version
python scripts/refresh_cli_reference.py --check
```

`--check` compares the installed version against the stamp at the top of
`references/cli.md` and exits non-zero on drift. On drift, or if
`references/cli.md` is absent:

```bash
python scripts/refresh_cli_reference.py
```

This walks every subcommand's `--help` and rewrites `references/cli.md` from the
installed binary. Commit the regenerated file — it is a cache, not a source.

That applies only inside a checkout of the skill pack. When the skill is loaded
from an installed plugin (a path under `~/.claude/plugins/`), do not rewrite
the cached copy — the next plugin update overwrites it anyway. Write the
reference somewhere disposable and read that instead:

```bash
python scripts/refresh_cli_reference.py --out "$TMPDIR/ob-cli.md"
```

and tell the user the shipped reference is stale, naming both versions from
the `--check` output. If you skip regenerating, treat `references/cli.md` as
orientation only and take every flag from `ob <command> --help`.

If `ob` is not installed, say so and stop; do not reason about the CLI from
documentation alone. Installation is from PyPI, and a conda software backend
additionally requires running `ob` from inside a conda environment manager
(miniforge is the project's recommendation).

## Using the reference

- Broad orientation, or "which command does X": read `references/cli.md`.
- Exact flags for one command you are about to run: `ob <command> --help`.
  This is authoritative and costs nothing.
- Never pass a flag that does not appear in one of those two places.

## Online documentation

`https://docs.omnibenchmark.org/latest/` publishes a CLI reference per release
and for `main`. Use it for prose and rationale; use the installed binary for
syntax. When the two disagree, the binary wins.

## References

- `references/cli.md` — generated command reference, version-stamped
