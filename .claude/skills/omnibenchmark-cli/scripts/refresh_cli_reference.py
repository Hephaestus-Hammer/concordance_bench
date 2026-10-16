#!/usr/bin/env python3
"""Regenerate references/cli.md from the installed `ob` binary.

The reference is a cache of `ob --help` output, not a hand-written document:
Omnibenchmark's CLI moves between alpha releases, so the only trustworthy source
is the binary on this machine.

    python refresh_cli_reference.py           # rewrite the reference
    python refresh_cli_reference.py --check   # exit 1 if it is stale
"""
import argparse
import pathlib
import re
import subprocess
import sys

STAMP = "<!-- ob-version: "
MAX_DEPTH = 3


def run(args):
    return subprocess.run(
        args, capture_output=True, text=True, timeout=60,
    )


def installed_version():
    proc = run(["ob", "--version"])
    if proc.returncode != 0:
        raise SystemExit(f"`ob --version` failed (exit {proc.returncode}):\n{proc.stderr.strip()}")
    return proc.stdout.strip() or "unknown"


def stamped_version(path):
    if not path.exists():
        return None
    first = path.read_text().splitlines()[0] if path.read_text() else ""
    if first.startswith(STAMP):
        return first[len(STAMP):].rstrip(" ->")
    return None


def subcommands(help_text):
    """Pull subcommand names out of a click/typer 'Commands:' section."""
    out = []
    in_section = False
    for line in help_text.splitlines():
        stripped = line.strip()
        # plain click ("Commands:") and rich/typer boxed ("╭─ Commands ─╮")
        if re.match(r"^(Commands:|[╭┌].*\bCommands\b.*)$", stripped):
            in_section = True
            continue
        if in_section:
            if not stripped or re.match(r"^[╰└]", stripped):
                if out:
                    break
                continue
            if re.match(r"^(Options:|Usage:|[╭┌])", stripped):
                break
            body = stripped.lstrip("│ ").rstrip("│ ")
            m = re.match(r"^([A-Za-z][\w-]*)(\s{2,}|$)", body)
            if m:
                out.append(m.group(1))
    return out


def walk(path=(), depth=0, seen=None):
    """Yield (command_path, help_text) breadth-first."""
    seen = seen if seen is not None else set()
    proc = run(["ob", *path, "--help"])
    if proc.returncode != 0:
        return
    text = proc.stdout or proc.stderr
    yield path, text
    if depth >= MAX_DEPTH:
        return
    for name in subcommands(text):
        child = (*path, name)
        if child in seen:
            continue
        seen.add(child)
        yield from walk(child, depth + 1, seen)


def render(version, entries):
    lines = [f"{STAMP}{version} -->", "", "# `ob` command reference", "",
             f"Generated from the installed binary (`ob --version` → `{version}`) by",
             "`scripts/refresh_cli_reference.py`. Do not edit by hand.", "", "## Commands", ""]
    for path, _ in entries:
        label = " ".join(("ob", *path))
        anchor = "-".join(("ob", *path)).lower()
        lines.append(f"- [`{label}`](#{anchor})")
    lines.append("")
    for path, text in entries:
        label = " ".join(("ob", *path))
        lines += [f"## `{label}`", "", "```text", text.rstrip(), "```", ""]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the reference is missing or stale; write nothing")
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path(__file__).resolve().parent.parent / "references" / "cli.md")
    ap.add_argument("--version-label", default=None,
                    help="stamp this string instead of `ob --version`; use when running "
                         "from a source checkout, where importlib.metadata reports 0.0.0 "
                         "(e.g. --version-label \"$(git describe --tags)\")")
    args = ap.parse_args()

    version = args.version_label or installed_version()
    if args.check:
        stamped = stamped_version(args.out)
        if stamped is None:
            print(f"STALE: {args.out} missing or unstamped (installed: {version})")
            return 1
        if stamped != version:
            print(f"STALE: reference is for {stamped!r}, installed is {version!r}")
            return 1
        print(f"fresh: {version}")
        return 0

    entries = list(walk())
    if not entries:
        raise SystemExit("`ob --help` produced nothing; is `ob` on PATH?")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(version, entries))
    print(f"wrote {args.out} — {len(entries)} command(s), ob {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
