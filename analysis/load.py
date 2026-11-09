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
# these have the same settings, so their disagreement is seed noise. "run" is not an
# ob parameter: index_runs() adds it to tell output folders (same-seed replicates) apart.
SEED_PARAMS = {"random_seed", "seed", "replicate", "run"}
REPLICATE_KEYS = {"replicate", "run"}


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


def index_runs(out_dirs):
    """index() over one or several ob output trees.

    Several trees are same-seed replicates of each other (the same plan run again into
    another --out-dir): each run is tagged with its folder's name, as a "run" seed on
    its input node and as "@<folder>" on its label. Two runs with the same parameters
    from different folders then pair up as `replicate` (run-to-run noise at a fixed
    seed), and every other pair is formed within one folder only. One tree: exactly
    index(find(tree)).
    """
    out_dirs = [Path(d) for d in out_dirs]
    if len(out_dirs) == 1:
        return index(find(out_dirs[0]))
    tags, rows = [], []
    for d in out_dirs:
        tag = d.resolve().name
        while tag in tags:
            tag += "+"
        tags.append(tag)
        for oid, paths in find(d).items():
            for p in paths:
                nodes = _tag(lineage(p), tag)
                rows.append({"output": oid, "path": str(p), "size": nodes[0].module, "nodes": nodes, "run": tag})
    df = pd.DataFrame(rows, columns=["output", "path", "size", "nodes", "run"])
    df["label"] = [f"{lab} @{run}" for lab, run in zip(_labels(df["nodes"].tolist()), df["run"])]
    return df


def _tag(nodes, tag):
    """The lineage with ("run", tag) added to its input node (the first after the data)."""
    if len(nodes) < 2:
        return nodes
    n = nodes[1]
    return (nodes[0], Node(n.stage, n.module, tuple(sorted(n.params + (("run", tag),)))), *nodes[2:])


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
            if keys - REPLICATE_KEYS:
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
    (one stage's noise floor). Module pairs at one stage: everything else is the
    same, seeds included, and at the stage being compared every seed of one module
    pairs with every seed of the other: seed 3 of one Leiden implementation and seed 3
    of another are unrelated draws, so each cross pair samples "A against B" as
    validly as the matched one. The same module with other settings keeps matched
    seeds (there a seed means the same thing), as do pairs differing at several stages
    wherever both sides ran several (a matched sample, not every cross-seed
    combination). Anything else mixes a settings difference with seed noise.
    """
    differ, seed_differ, unmatched, other_module = 0, 0, False, False
    for x, y in zip(a[1:], b[1:]):
        if x.module != y.module or x.settings != y.settings:
            differ += 1
            other_module = x.module != y.module
            if x.seeds != y.seeds and min(len(variants[(x.stage, x.module, x.settings)]),
                                          len(variants[(y.stage, y.module, y.settings)])) > 1:
                unmatched = True
        elif x.seeds != y.seeds:
            seed_differ += 1
    if differ == 1 and other_module:
        return seed_differ == 0
    if differ:
        return seed_differ == 0 and not unmatched
    return seed_differ == 1 or (seed_differ == 0 and a != b)


def _at_base_seed(nodes, base):
    return all(n.seeds == base[(n.stage, n.module, n.settings)] for n in nodes)


def pair_group(a, b):
    """pair_category, split by module where exactly one stage differs.

    'knn' becomes 'knn: nn-baseline vs nn-rapids' (module ids in alphabetical order),
    so library against library at one stage can be read off directly; the same
    module with different settings becomes 'knn: nn-scanpy settings'. A one-stage
    seed group names the module whose seed varies, 'seed: cluster (cl-rapids)', so
    each module has its own noise floor rather than one pooled over implementations;
    a replicate group names the module that wrote the output, 'replicate (cl-rapids)'.
    Multi-stage groups ('pca+knn', 'seed: pca+knn', ...) are unchanged.
    """
    cat = pair_category(a, b)
    if cat == "replicate":
        return f"replicate ({a[-1].module})"
    if "+" in cat or cat == "identical":
        return cat
    if cat.startswith("seed: "):
        stage = cat[len("seed: "):]
        x = next(x for x, y in zip(a[1:], b[1:]) if x.stage == stage and x.seeds != y.seeds)
        return f"{cat} ({x.module})"
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
