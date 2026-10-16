#!/usr/bin/env python3
"""Compare two result trees file by file, pairing files by relative path.

    compare_runs.py A B [--include GLOB ...] [--rtol 1e-9] [--atol 1e-12]

A and B are two `ob run --out-dir` trees (replicates), or two parameter-hash
directories inside one tree (seed 1 vs seed 2). Per file it prints one of:

    IDENTICAL   same bytes (after gunzip, so a gzip mtime header does not count)
    CLOSE       text tables differing only by numbers within rtol/atol
    DIFFERENT   anything else; tables report the largest abs/rel difference
    MISSING     present on one side only

Exit status: 0 all IDENTICAL, 3 worst is CLOSE, 1 any DIFFERENT or MISSING
(2 is argparse's usage error).
Stdlib only, so it runs outside the module's environment.
"""
import argparse
import csv
import fnmatch
import gzip
import hashlib
import math
import pathlib
import sys

TABLE_SUFFIXES = {".tsv", ".csv", ".txt"}


def read_bytes(path):
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


def table_suffix(path):
    return path.with_suffix("").suffix if path.suffix == ".gz" else path.suffix


def as_float(cell):
    try:
        return float(cell)
    except ValueError:
        return None


def compare_tables(a, b, delim, rtol, atol):
    """Return (status, detail). Non-numeric cells must match exactly."""
    ra = list(csv.reader(a.decode().splitlines(), delimiter=delim))
    rb = list(csv.reader(b.decode().splitlines(), delimiter=delim))
    if len(ra) != len(rb) or any(len(x) != len(y) for x, y in zip(ra, rb)):
        return "DIFFERENT", f"shape {len(ra)} rows vs {len(rb)} rows"
    max_abs = max_rel = 0.0
    close = True
    for i, (row_a, row_b) in enumerate(zip(ra, rb)):
        for j, (x, y) in enumerate(zip(row_a, row_b)):
            if x == y:
                continue
            fx, fy = as_float(x), as_float(y)
            if fx is None or fy is None:
                return "DIFFERENT", f"row {i} col {j}: {x!r} vs {y!r}"
            if math.isnan(fx) and math.isnan(fy):
                continue
            d = abs(fx - fy)
            max_abs = max(max_abs, d)
            if d:
                max_rel = max(max_rel, d / max(abs(fx), abs(fy)))
            close = close and math.isclose(fx, fy, rel_tol=rtol, abs_tol=atol)
    detail = f"max_abs={max_abs:.3g} max_rel={max_rel:.3g}"
    return ("CLOSE" if close else "DIFFERENT"), detail


def compare_file(a, b, rtol, atol):
    da, db = read_bytes(a), read_bytes(b)
    if da == db:
        return "IDENTICAL", hashlib.sha256(da).hexdigest()[:12]
    suffix = table_suffix(a)
    if suffix in TABLE_SUFFIXES:
        return compare_tables(da, db, "," if suffix == ".csv" else "\t", rtol, atol)
    return "DIFFERENT", "binary; compare contents with a format-aware tool"


def files(root, include):
    out = {}
    for p in root.rglob("*"):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and (not include or any(fnmatch.fnmatch(rel, g) for g in include)):
            out[rel] = p
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("a", type=pathlib.Path)
    ap.add_argument("b", type=pathlib.Path)
    ap.add_argument("--include", action="append", default=[],
                    help="glob on the relative path; repeatable; default: every file")
    ap.add_argument("--rtol", type=float, default=1e-9)
    ap.add_argument("--atol", type=float, default=1e-12)
    args = ap.parse_args(argv)

    fa, fb = files(args.a, args.include), files(args.b, args.include)
    if not fa and not fb:
        print("no files matched", file=sys.stderr)
        return 1
    seen = set()
    for rel in sorted(fa.keys() | fb.keys()):
        if rel not in fa or rel not in fb:
            status, detail = "MISSING", f"only in {'A' if rel in fa else 'B'}"
        else:
            status, detail = compare_file(fa[rel], fb[rel], args.rtol, args.atol)
        print(f"{status:<10} {rel}  {detail}")
        seen.add(status)
    if seen & {"DIFFERENT", "MISSING"}:
        return 1
    return 3 if "CLOSE" in seen else 0


def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        a, b = pathlib.Path(t, "a"), pathlib.Path(t, "b")
        a.mkdir(), b.mkdir()
        (a / "x.tsv").write_text("id\tPC1\nc1\t0.5\nc2\t0\n")
        (b / "x.tsv").write_text("id\tPC1\nc1\t0.5\nc2\t0\n")
        assert main([str(a), str(b)]) == 0
        (b / "x.tsv").write_text("id\tPC1\nc1\t0.5000000000001\nc2\t0.0\n")
        assert main([str(a), str(b)]) == 3
        (b / "x.tsv").write_text("id\tPC1\nc1\t-0.5\nc2\t0\n")
        assert main([str(a), str(b)]) == 1
        (b / "x.tsv").write_text("id\tPC1\nc1\t0.5\nc2\t0\n")
        (a / "y.gz").write_bytes(gzip.compress(b"z", mtime=1)), (b / "y.gz").write_bytes(gzip.compress(b"z", mtime=2))
        assert main([str(a), str(b)]) == 0
        (a / "only_a").write_text("")
        assert main([str(a), str(b)]) == 1
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
        sys.exit(0)
    sys.exit(main())
