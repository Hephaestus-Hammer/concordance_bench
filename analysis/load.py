"""Find runs in the ob output tree (out/): stage, module, parameters, seed.

Reads only; never writes into out/.

ob nests every node's directory inside its parent's, so a file's path is its
whole lineage:

    out/<stage>/<module>/.<hash>/<stage>/<module>/.<hash>/.../<file>

Each node directory holds the parameters.json that ob writes for that node.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# output id (as in benchmark.yaml) -> filename suffix
OUTPUTS = {
    "embedding_tsv": "_embedding.tsv",
    "neighbors_h5": "_neighbors.h5",
    "clusters_tsv": "_clusters.tsv",
    "rawdata_clusters_truth": ".clusters_truth.tsv",
}

# Parameters that only choose a seed or a replicate. Two runs that differ only in
# these have the same settings, so their disagreement is seed noise.
SEED_PARAMS = {"random_seed", "seed", "replicate"}


@dataclass(frozen=True)
class Node:
    stage: str
    module: str
    params: tuple  # sorted (key, value) pairs, seeds included

    @property
    def settings(self):
        return tuple((k, v) for k, v in self.params if k not in SEED_PARAMS)

    @property
    def seeds(self):
        return tuple((k, v) for k, v in self.params if k in SEED_PARAMS)


def _read_params(node_dir):
    f = node_dir / "parameters.json"
    if not f.exists():
        return ()
    p = json.loads(f.read_text())
    if isinstance(p, dict) and isinstance(p.get("parameters"), dict):
        p = p["parameters"]
    if not isinstance(p, dict):
        return ()
    # values may be lists or numbers; keep them hashable and printable
    return tuple(sorted((k, v if isinstance(v, (str, int, float, bool)) else json.dumps(v))
                        for k, v in p.items()))


def _is_node_dir(d):
    return d.name.startswith(".") or (d / "parameters.json").exists()


def lineage(path):
    """Nodes from the dataset down to the node that wrote `path`."""
    nodes = []
    d = Path(path).absolute().parent
    while _is_node_dir(d) and d.parent != d:
        module, stage = d.parent, d.parent.parent
        nodes.append(Node(stage.name, module.name, _read_params(d)))
        d = stage.parent
        if (d / "Snakefile").exists() or (d / ".metadata").exists():
            break
    if not nodes:
        raise ValueError(f"not inside an ob output tree: {path}")
    return tuple(reversed(nodes))


def find(out_dir):
    """{output id: [paths]} for every output under out_dir."""
    out_dir = Path(out_dir)
    skip = {".modules", ".snakemake", ".envs", ".logs", ".metadata"}
    return {oid: sorted(p for p in out_dir.rglob(f"*{suffix}") if not skip & set(p.parts))
            for oid, suffix in OUTPUTS.items()}


def index(files):
    """One row per output file: output id, size (dataset module), lineage, label.

    `files` is {output id: [paths]}, as from find() or a gather invocation.
    """
    rows = []
    for oid, paths in files.items():
        for p in paths or []:
            nodes = lineage(p)
            rows.append({"output": oid, "path": str(p), "size": nodes[0].module, "nodes": nodes})
    df = pd.DataFrame(rows, columns=["output", "path", "size", "nodes"])
    df["label"] = _labels(df["nodes"].tolist())
    return df


def _labels(all_nodes):
    """Short pipeline labels from PCA on, e.g. 'pc-scanpy > nn-rapids > cl-baseline'.

    A module is followed by its settings only if it ran with more than one, and by
    its seeds only if seeds vary in this run.
    """
    variants, seeds = {}, {}
    for nodes in all_nodes:
        for n in nodes[1:]:
            variants.setdefault((n.stage, n.module), set()).add(n.settings)
            seeds.setdefault((n.stage, n.module), set()).add(n.seeds)
    labels = []
    for nodes in all_nodes:
        parts = []
        for n in nodes[1:]:
            if n.stage == "input" and len(nodes) > 2:
                continue  # the input conversion is shared by everything after it
            s = n.module
            if len(variants[(n.stage, n.module)]) > 1:
                s += "(" + ",".join(f"{k}={v}" for k, v in n.settings) + ")"
            if len(seeds[(n.stage, n.module)]) > 1:
                s += "[" + ",".join(f"{k}={v}" for k, v in n.seeds) + "]"
            parts.append(s)
        labels.append(" > ".join(parts) or nodes[-1].module)
    return labels


def pair_category(a, b):
    """What differs between two lineages of the same size and depth.

    Returns the '+'-joined stages whose module or settings differ ('knn',
    'pca+knn', ...). If only seeds differ: 'seed: <stages>' with the stages whose
    seed differs ('seed: pca', 'seed: cluster', ...), the noise floor of those
    stages; 'replicate' if only the input replicate differs.
    """
    differ, seeded, seed_keys = [], [], set()
    for x, y in zip(a[1:], b[1:]):
        if x.module != y.module or x.settings != y.settings:
            differ.append(x.stage)
        elif x.seeds != y.seeds:
            keys = {k for (k, v1), (_, v2) in zip(x.seeds, y.seeds) if v1 != v2}
            seed_keys |= keys
            if keys - {"replicate"}:
                seeded.append(x.stage)
    if differ:
        return "+".join(differ)
    if seeded:
        return "seed: " + "+".join(seeded)
    return "replicate" if seed_keys else "identical"


def seed_variants(df):
    """{(stage, module, settings): set of seeds seen} over every lineage in df."""
    out = {}
    for nodes in df["nodes"]:
        for n in nodes:
            out.setdefault((n.stage, n.module, n.settings), set()).add(n.seeds)
    return out


def comparable(a, b, variants):
    """Whether two lineages make a like-for-like pair.

    Seed pairs: same settings everywhere, seed differs at exactly one stage
    (one stage's noise floor). Settings pairs: wherever the settings are the same,
    the seeds are the same too; where the settings differ, the seeds match as well
    if both modules ran several seeds (a matched sample, not every cross-seed
    combination). Anything else mixes a settings difference with seed noise.
    """
    differ, seed_differ, unmatched = 0, 0, False
    for x, y in zip(a[1:], b[1:]):
        if x.module != y.module or x.settings != y.settings:
            differ += 1
            if x.seeds != y.seeds and min(len(variants[(x.stage, x.module, x.settings)]),
                                          len(variants[(y.stage, y.module, y.settings)])) > 1:
                unmatched = True
        elif x.seeds != y.seeds:
            seed_differ += 1
    if differ:
        return seed_differ == 0 and not unmatched
    return seed_differ == 1 or (seed_differ == 0 and a != b)


def _at_base_seed(nodes, base):
    return all(n.seeds == base[(n.stage, n.module, n.settings)] for n in nodes)


def pair_group(a, b):
    """pair_category, split by module where exactly one stage differs.

    'knn' becomes 'knn: nn-baseline vs nn-rapids' (module ids in alphabetical order),
    so library against library at one stage can be read off directly; the same
    module with different settings becomes 'knn: nn-scanpy settings'. Seed,
    replicate and multi-stage groups ('pca+knn', ...) are unchanged.
    """
    cat = pair_category(a, b)
    if "+" in cat or cat.startswith("seed") or cat in ("replicate", "identical"):
        return cat
    x, y = next((x, y) for x, y in zip(a[1:], b[1:]) if x.stage == cat)
    if x.module == y.module:
        return f"{cat}: {x.module} settings"
    m1, m2 = sorted((x.module, y.module))
    return f"{cat}: {m1} vs {m2}"


def missing(df, output):
    """Combinations that should exist for `output` but don't, per size.

    Checked on the base grid only (every module at its first seed, normally 0):
    expected = every parent lineage found there x every (module, parameters) found
    at this stage. Extra seeds are run one stage at a time through filters, so their
    gaps are deliberate and not reported. A failed base job shows up here instead of
    silently shrinking the grid.
    """
    base = {k: min(v, key=lambda s: tuple(str(x) for x in s)) for k, v in seed_variants(df).items()}
    rows = []
    sub = df[df["output"] == output]
    for size, g in sub.groupby("size"):
        have = {n for n in g["nodes"] if _at_base_seed(n, base)}
        parents = {n[:-1] for n in have}
        own = {n[-1] for n in have}
        for p in sorted(parents, key=str):
            for o in sorted(own, key=str):
                if p + (o,) not in have:
                    rows.append({"size": size, "parent": " > ".join(n.module for n in p[1:]),
                                 "module": o.module, "params": dict(o.params)})
    return pd.DataFrame(rows, columns=["size", "parent", "module", "params"])
