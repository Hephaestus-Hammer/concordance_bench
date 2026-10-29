"""Concordance report: every metric and figure from one run of the plan, in one HTML file.

The page has tabs per stage and filters for dataset size and for figures, tables
and descriptions, so only what is selected is shown.

By hand, on the ob output tree:

    pixi run report                         # = python analysis/report.py --from_out out

As an ob gather stage later: the flags below are exactly what ob passes, one per
gathered output id, each with every file:

    report.py --output_dir <dir> --name <module> \\
        --embedding_tsv a.tsv b.tsv ... --neighbors_h5 ... --clusters_tsv ... \\
        --rawdata_clusters_truth ...

Files are identified by their path in the output tree (their lineage), never by
their position in a list. Writes {name}_report.html plus one TSV per table;
never writes into out/.
"""

import argparse
import base64
import html
import io
import itertools
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import concordance as cc
import figures as fg
import resources as rs
from load import OUTPUTS, comparable, find, index, missing, pair_group, seed_variants

DESCRIPTIONS = {
    "runs": """What the report was built from: the number of output files per stage and
        dataset size. <b>Missing combinations</b> lists every combination that should exist
        (each upstream lineage found &times; each module and parameter set found at that stage)
        but has no output, usually a failed job. Everything below is computed only from the
        files that exist.""",
    "labels": """Pipelines are named by their module ids from PCA on
        (<code>pc-… &gt; nn-… &gt; cl-…</code>). A pair of runs is grouped by <b>what differs</b>
        between them: the stages whose module or settings differ (<code>pca</code>,
        <code>knn</code>, <code>pca+knn</code>, …); where exactly one stage differs, the group also names
        the two modules (<code>knn: nn-baseline vs nn-rapids</code>), so one library can be compared with
        another at one stage; <code>seed: &lt;stage&gt;</code> if only that
        stage's random seed differs, which is that stage's noise floor; or <code>replicate</code>
        if only the input replicate differs. Noise-floor groups are grey; colours are the same
        in every figure. Only like-for-like pairs are compared: seed pairs differ in exactly one
        stage's seed, and pairs that differ in a stage's settings have the same seeds everywhere
        else (and at that stage too, when both modules ran several seeds), so a settings
        difference is never mixed with seed noise.""",
    "pca": """One line per group of pairs of PCA runs on the same cells: the median over the
        pairs, with their range shaded. The y-axis is 1&nbsp;&minus;&nbsp;|cos|
        between the cell scores of matching components, on a log scale (zero is drawn at
        10<sup>&minus;16</sup>). |cos| ignores sign, which is arbitrary in PCA. Values near
        10<sup>&minus;16</sup> mean identical up to round-off; values near 1 mean the component
        points somewhere else. Late components with nearly equal variance can swap or mix
        without changing the subspace, so the table also gives the largest principal angle
        between the spans of the first <i>k</i> components, which is insensitive to that.""",
    "knn": """Each point is a pair of kNN graphs on the same cells. The y-axis is the mean over
        cells of the shared-neighbour fraction: of each cell's <i>k</i> nearest neighbours (the cell
        itself not counted), the share found in both graphs. Modules store different numbers of
        neighbours (scanpy keeps 14 on its exact path but 15 on its approximate one for
        <code>n_neighbors=15</code>), so <i>k</i> is the smaller of the two; the table shows both. <code>knn: …</code> pairs
        share their PCA input, so they show the kNN step's own effect, one pair of kNN modules per
        row; <code>pca: …</code> pairs use the same kNN module on different PCA outputs, so they show
        what PCA differences carry into the graph. The table gives min, median and max per group, plus the share of cells whose neighbour
        sets are identical; every pair is in the TSV.""",
    "ari": """Each point is one pair of Leiden clusterings of the same cells, measured by the
        adjusted Rand index (ARI; 1 = identical partitions, about 0 = chance), grouped by what
        differs between the two pipelines. The line is the median. A stage whose pairs fall
        inside the spread of the <code>seed: …</code> pairs changes the clustering no more than
        re-running with another seed. A seed varied upstream (<code>seed: pca</code>) shows how
        that stage's noise carries through to the clusters.""",
    "truth": """ARI of each pipeline's clustering against the annotated cell types: one row per
        pipeline with all its seeds together, one point per run, one marker per annotation column
        in the truth file. The number of clusters at a fixed resolution
        usually differs from the number of annotated types, which keeps the ARI below 1 for
        every pipeline: compare pipelines with each other, not with 1. The table gives the
        number of runs and the median number of clusters and ARI per size; NMI and every run
        are in the TSV.""",
    "runtime": """How long each job took, how many cores it kept busy and how much memory it used.
        Where a job ran under denet (the <code>stage</code> entrypoint) the numbers come from
        its trace, sampled every 0.1&ndash;1&nbsp;s: wall time, mean cores used (CPU time / wall time),
        peak cores used (the busiest sample), peak memory, peak threads and, for GPU modules, GPU
        utilisation and the job's GPU memory. Jobs without a trace fall back to Snakemake's benchmark
        file, which samples every 30&nbsp;s after the first 15&nbsp;s, so their CPU time and memory are lower
        bounds and they have no peak cores; the table says which source each row uses. All of it covers
        the whole module call, including Python start-up, imports and reading and writing files;
        every job is a fresh process, so one-off costs such as numba compiling pynndescent (around
        10&nbsp;s) are in every scanpy kNN job. GPU memory is the job's own where NVML reports it,
        otherwise the whole device's. The dashed line
        is the cores the stage gets in <code>benchmark.yaml</code>: a mean well below it with a peak near it
        means short multi-threaded bursts; a peak above it means the module starts more threads than it
        was given. The traces below show cores over time, one line per job, so runs that finish early
        (e.g. a kNN search that converges quickly) stand out. Jobs that ran side by side on one node
        compete for cores and memory bandwidth, so compare timings from the same kind of run.""",
    "scaling": """Median agreement per group against the number of cells: kNN shared-neighbour
        fraction (left) and ARI between clusterings (right). Shows whether disagreement grows
        with dataset size.""",
}


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--output_dir", type=Path, default=Path("results/report"))
    p.add_argument("--name", default="concordance")
    p.add_argument("--from_out", type=Path, help="find every output under this ob output tree")
    p.add_argument("--plan", type=Path, default=Path("benchmark.yaml"),
                   help="plan to read each stage's allocated cores from (optional)")
    for oid in OUTPUTS:
        p.add_argument(f"--{oid}", type=Path, nargs="+", default=[])
    return p.parse_args()


# ---- compute -------------------------------------------------------------------

def compute(df):
    """All summary tables, one dataset size at a time to keep memory bounded."""
    t = {k: [] for k in ("pca_curves", "pca_angles", "knn", "ari", "truth")}
    n_cells = {}
    variants = seed_variants(df)

    def pairs(rows):
        for i, j in itertools.combinations(range(len(rows)), 2):
            a, b = rows.iloc[i], rows.iloc[j]
            if comparable(a["nodes"], b["nodes"], variants):
                yield i, j, a, b

    for size, g in df.groupby("size"):
        order = _cell_order(g)
        n_cells[size] = len(order)
        by = {oid: g[g["output"] == oid].reset_index(drop=True) for oid in OUTPUTS}

        emb = [cc.read_embedding(p).reindex(order) for p in by["embedding_tsv"]["path"]]
        _check_complete(emb, by["embedding_tsv"])
        basis = {}  # (embedding, k) -> orthonormal basis, computed once

        def q(i, k):
            if (i, k) not in basis:
                basis[(i, k)] = cc.pca_basis(emb[i], k)
            return basis[(i, k)]

        for i, j, a, b in pairs(by["embedding_tsv"]):
            pair, cat = f"{a['label']}  vs  {b['label']}", pair_group(a["nodes"], b["nodes"])
            t["pca_curves"].append({"size": size, "pair": pair, "category": cat,
                                    "values": cc.pca_one_minus_abs_cos(emb[i], emb[j])})
            row = {"size": size, "pair": pair, "category": cat}
            for k in (10, 20, 50):
                if k <= min(emb[i].shape[1], emb[j].shape[1]):
                    row[f"max angle, first {k} PCs (deg)"] = cc.pca_max_angle(None, None, qa=q(i, k), qb=q(j, k))
            t["pca_angles"].append(row)
        del emb, basis

        graphs = []
        for p in by["neighbors_h5"]["path"]:
            d, cells = cc.read_neighbors(p)
            graphs.append(cc.align_graph(d, cells, order))
        stored = [cc.neighbours_per_cell(d) for d in graphs]
        near = {}  # (graph, k) -> its k nearest neighbours, computed once

        def nn(i, k):
            if (i, k) not in near:
                near[(i, k)] = cc.nearest(graphs[i], k)
            return near[(i, k)]

        for i, j, a, b in pairs(by["neighbors_h5"]):
            ka, kb = stored[i], stored[j]
            k = min(ka, kb)
            frac = cc.knn_shared_fraction(graphs[i], graphs[j], k=k, n1=nn(i, k), n2=nn(j, k))
            t["knn"].append({"size": size, "pair": f"{a['label']}  vs  {b['label']}",
                             "category": pair_group(a["nodes"], b["nodes"]),
                             "neighbours stored": f"{ka} / {kb}", "k compared": min(ka, kb),
                             "mean_shared": float(frac.mean()),
                             "cells_identical": float((frac == 1).mean())})
        del graphs, near

        labels = [cc.read_clusters(p).reindex(order) for p in by["clusters_tsv"]["path"]]
        _check_complete(labels, by["clusters_tsv"])
        n_clusters = [lab.nunique() for lab in labels]
        labels = [cc.codes(lab) for lab in labels]  # integer codes: fast ARI
        for i, j, a, b in pairs(by["clusters_tsv"]):
            t["ari"].append({"size": size, "a": a["label"], "b": b["label"],
                             "category": pair_group(a["nodes"], b["nodes"]),
                             "ari": cc.ari(labels[i], labels[j])})
        if len(by["rawdata_clusters_truth"]):
            truth = cc.read_truth(by["rawdata_clusters_truth"]["path"].iloc[0]).reindex(order)
            truth_codes = {col: cc.codes(truth[col]) for col in truth.columns}
            for lab, nclu, (_, r) in zip(labels, n_clusters, by["clusters_tsv"].iterrows()):
                for col in truth.columns:
                    t["truth"].append({"size": size, "pipeline": _no_seed(r["label"]), "run": r["label"],
                                       "column": col,
                                       "ari": cc.ari(truth_codes[col], lab), "nmi": cc.nmi(truth_codes[col], lab),
                                       "clusters": nclu, "annotated types": truth[col].nunique()})

    tables = {k: pd.DataFrame(v) for k, v in t.items()}
    for k in ("knn", "ari", "pca_angles"):
        if len(tables[k]) == 0:
            tables[k] = pd.DataFrame(columns=["size", "category"])
    return tables, n_cells


def _no_seed(label):
    """Pipeline label without its [seed] tags: all seeds of one pipeline together."""
    return re.sub(r"\[[^\]]*\]", "", label)


def summarise(table, value_cols, extra=None):
    """Per size and category: number of pairs and min / median / max of each value."""
    if not len(table) or "category" not in table:
        return table
    agg = {"pairs": (value_cols[0], "count")}
    for c in value_cols:
        agg.update({f"{c} min": (c, "min"), f"{c} median": (c, "median"), f"{c} max": (c, "max")})
    for name, (col, fn) in (extra or {}).items():
        agg[name] = (col, fn)
    return table.groupby(["size", "category"]).agg(**agg).reset_index()


def _cell_order(g):
    """One cell order per size: the truth file's, else the first embedding's."""
    for oid, reader in (("rawdata_clusters_truth", cc.read_truth), ("embedding_tsv", cc.read_embedding),
                        ("clusters_tsv", cc.read_clusters)):
        paths = g.loc[g["output"] == oid, "path"]
        if len(paths):
            return reader(paths.iloc[0]).index
    _, cells = cc.read_neighbors(g["path"].iloc[0])
    return cells


def _check_complete(objs, rows):
    for o, (_, r) in zip(objs, rows.iterrows()):
        if o.isna().to_numpy().any():
            raise ValueError(f"cells missing from {r['path']} relative to the truth file")


# ---- render --------------------------------------------------------------------

def fig_html(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    fg.plt.close(fig)
    return f'<img alt="" src="data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}">'


def table_html(df, floatfmt="{:.4g}", fold_above=20, summary="Table"):
    """A table; folded away behind a click when it is long."""
    if df is None or len(df) == 0:
        return "<p class='note'>None.</p>"
    t = df.to_html(index=False, border=0, classes="t", float_format=floatfmt.format, escape=True, na_rep="–")
    if len(df) > fold_above:
        return f"<details><summary>{summary} ({len(df)} rows; also in the TSV)</summary>{t}</details>"
    return t


def truth_wide(truth, sizes):
    """One row per pipeline (all its seeds together): runs, median clusters and median ARI
    per annotation column, per size."""
    w = truth.pivot_table(index="pipeline", columns=["size", "column"], values="ari", aggfunc="median")
    k = truth.pivot_table(index="pipeline", columns="size", values="clusters", aggfunc="median")
    n = truth.pivot_table(index="pipeline", columns="size", values="run", aggfunc="nunique")
    cols = {}
    for s in sizes:
        if s in n:
            cols[f"{s}: runs"] = n[s]
        if s in k:
            cols[f"{s}: clusters (median)"] = k[s]
        for c in sorted(truth["column"].unique()):
            if (s, c) in w:
                cols[f"{s}: ARI {c} (median)"] = w[(s, c)]
    return pd.DataFrame(cols).reset_index()


STAGES = [  # (id, tab label, title)
    ("overview", "Overview", "Runs found and how pairs are labelled"),
    ("pca", "PCA", "PCA: component agreement"),
    ("knn", "kNN", "kNN: neighbour agreement"),
    ("ari", "Leiden", "Leiden: agreement between runs"),
    ("truth", "Annotation", "Leiden: agreement with the annotation"),
    ("scaling", "Scaling", "Scaling with dataset size"),
    ("runtime", "Runtime", "Runtime and cores used per job"),
]


def _block(kind, body, size=None):
    s = f' data-size="{html.escape(size)}"' if size else ""
    return f'<div class="blk" data-kind="{kind}"{s}>{body}</div>'


def _per_size(sizes, n_cells, make_fig, make_table):
    """One figure and one table per dataset size, each tagged for the size filter."""
    out = []
    for size in sizes:
        fig, tab = make_fig(size), make_table(size)
        out.append(f'<div class="size" data-size="{html.escape(size)}">'
                   f'<h3>{html.escape(size)} <span class="cells">{n_cells[size]:,} cells</span></h3>'
                   + (_block("figure", fig_html(fig)) if fig is not None else "")
                   + _block("table", table_html(tab)) + "</div>")
    return "".join(out)


def render(df, tables, n_cells, source, rt=None, series=None):
    sizes = sorted(n_cells, key=n_cells.get)
    counts = (df.assign(stage=df["output"]).pivot_table(index="size", columns="stage", values="path",
                                                         aggfunc="count", fill_value=0)
              .reindex(sizes).rename_axis(columns=None).reset_index())
    counts.insert(1, "cells", counts["size"].map(n_cells))
    miss = pd.concat([missing(df, oid) for oid in OUTPUTS], ignore_index=True)
    has_floor = (tables["ari"]["category"].str.startswith("seed")
                 | (tables["ari"]["category"] == "replicate")).any()
    floor_note = None if has_floor else (
        "No seed or replicate pairs in this run, so there is no noise floor yet: "
        "differences cannot be compared with seed noise.")

    def at(t, size):
        return t[t["size"] == size] if len(t) and "size" in t else t

    body = {"overview": _block("desc", f"<p class='desc'>{DESCRIPTIONS['runs']}</p>")
            + _block("table", table_html(counts) + "<h3>Missing combinations</h3>" + table_html(miss))
            + _block("desc", f"<h3>How pairs are labelled</h3><p class='desc'>{DESCRIPTIONS['labels']}</p>")}
    notes = {}

    if len(tables["pca_curves"]):
        angles = [c for c in tables["pca_angles"] if "angle" in c]
        body["pca"] = _per_size(
            sizes, n_cells,
            lambda s: fg.pca_components(at(tables["pca_curves"], s), [s]) if len(at(tables["pca_curves"], s)) else None,
            lambda s: summarise(at(tables["pca_angles"], s), angles))
    if len(tables["knn"]) and "pair" in tables["knn"]:
        stored = {"neighbours stored": ("neighbours stored", lambda x: ", ".join(sorted(set(x))))}
        body["knn"] = _per_size(
            sizes, n_cells,
            lambda s: fg.by_category(at(tables["knn"], s), [s], "mean_shared",
                                     "mean shared-neighbour fraction (line = median)") if len(at(tables["knn"], s)) else None,
            lambda s: summarise(at(tables["knn"], s), ["mean_shared", "cells_identical"], stored))
        notes["knn"] = floor_note
    if len(tables["ari"]) and "ari" in tables["ari"]:
        body["ari"] = _per_size(
            sizes, n_cells,
            lambda s: fg.by_category(at(tables["ari"], s), [s], "ari",
                                     "ARI between runs (1 = identical; line = median)") if len(at(tables["ari"], s)) else None,
            lambda s: summarise(at(tables["ari"], s), ["ari"]))
        notes["ari"] = floor_note
    if len(tables["truth"]):
        body["truth"] = _per_size(
            sizes, n_cells,
            lambda s: fg.truth_ari(at(tables["truth"], s), [s]) if len(at(tables["truth"], s)) else None,
            lambda s: truth_wide(at(tables["truth"], s), [s]))
    if len(sizes) > 1 and (len(tables["ari"]) or len(tables["knn"])):
        body["scaling"] = (_block("figure", fig_html(fg.scaling(tables["ari"], tables["knn"], n_cells)))
                           + "<p class='note'>This figure always shows every dataset size.</p>")

    if rt is not None and len(rt):
        body["runtime"] = _per_size(sizes, n_cells, lambda s: fg.runtime(rt, s),
                                    lambda s: rs.summarise(rt[rt["size"] == s]))
        if series:
            body["runtime"] += "<h3>Cores used over time</h3>" + "".join(
                f'<div class="size" data-size="{html.escape(s)}"><h3>{html.escape(s)}</h3>'
                + _block("figure", fig_html(f)) + "</div>"
                for s in sizes if (f := fg.runtime_traces(series, rt, s)) is not None)
    stages = [s for s in STAGES if s[0] in body]
    tabs = "".join(f'<button type="button" class="tab" data-stage="{sid}" aria-pressed="false">{lab}</button>'
                   for sid, lab, _ in stages)
    size_boxes = "".join(f'<label class="pill"><input type="checkbox" name="size" value="{html.escape(s)}" checked> '
                         f'{html.escape(s)}</label>' for s in sizes)
    kind_boxes = "".join(f'<label class="pill"><input type="checkbox" name="kind" value="{k}" checked> {lab}</label>'
                         for k, lab in (("figure", "Figures"), ("table", "Tables"), ("desc", "Descriptions")))
    sections = []
    for sid, _, title in stages:
        desc = "" if sid == "overview" else _block("desc", f"<p class='desc'>{DESCRIPTIONS[sid]}</p>")
        note = f"<p class='note'>{html.escape(notes[sid])}</p>" if notes.get(sid) else ""
        sections.append(f'<section class="stage" data-stage="{sid}"><h2>{title}</h2>{desc}{note}{body[sid]}'
                        f'<p class="empty note" hidden>No dataset selected.</p></section>')

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Concordance report</title>
<style>
  :root {{ --ink:#0b0b0b; --ink2:#52514e; --line:#e4e3df; --bg:#fcfcfb; --note:#fff4e5; --acc:#2a78d6; }}
  body {{ background:var(--bg); color:var(--ink); font:15px/1.5 system-ui,-apple-system,sans-serif;
         max-width:1100px; margin:0 auto; padding:24px 16px 64px; }}
  h1 {{ font-size:1.6rem; margin:0 0 4px; }} h2 {{ font-size:1.2rem; margin:24px 0 6px; }}
  h3 {{ font-size:1rem; margin:24px 0 4px; }} .cells {{ color:var(--ink2); font-weight:400; font-size:.85rem; }}
  .meta {{ color:var(--ink2); font-size:.9rem; margin:0 0 12px; }} .desc {{ max-width:75ch; }}
  .note {{ background:var(--note); padding:6px 10px; border-radius:4px; max-width:75ch; font-size:.9rem; }}
  .bar {{ position:sticky; top:0; z-index:2; background:var(--bg); border-bottom:1px solid var(--line);
         padding:10px 0; display:flex; flex-direction:column; gap:8px; }}
  .row {{ display:flex; flex-wrap:wrap; gap:6px; align-items:center; }}
  .row > span {{ color:var(--ink2); font-size:.8rem; width:5.5em; }}
  .tab {{ font:inherit; font-size:.9rem; padding:4px 12px; border:1px solid var(--line); border-radius:6px;
         background:#fff; color:var(--ink); cursor:pointer; }}
  .tab[aria-pressed="true"] {{ background:var(--acc); border-color:var(--acc); color:#fff; }}
  .pill {{ font-size:.85rem; padding:2px 10px; border:1px solid var(--line); border-radius:999px;
          background:#fff; cursor:pointer; user-select:none; }}
  .pill input {{ margin:0 4px 0 0; vertical-align:-1px; }}
  img {{ max-width:100%; height:auto; display:block; margin:8px 0; }}
  table.t {{ border-collapse:collapse; font-size:.8rem; margin:8px 0; display:block; overflow-x:auto; }}
  table.t th, table.t td {{ padding:3px 8px; border-bottom:1px solid var(--line); text-align:left; }}
  table.t td:first-child, table.t td:nth-child(2) {{ white-space:nowrap; }}
  code {{ font-size:.85em; }} summary {{ cursor:pointer; color:var(--ink2); font-size:.9rem; margin:8px 0; }}
  [hidden] {{ display:none !important; }}
</style></head><body>
<h1>Concordance report</h1>
<p class="meta">Generated {stamp} from {html.escape(source)}: {len(df)} output files, {len(sizes)} dataset size(s).</p>
<div class="bar">
  <div class="row"><span>Stage</span>{tabs}</div>
  <div class="row"><span>Datasets</span>{size_boxes}</div>
  <div class="row"><span>Show</span>{kind_boxes}</div>
</div>
{''.join(sections)}
<script>
(function () {{
  const KEY = "concordance-report-view";
  const tabs = [...document.querySelectorAll(".tab")];
  const boxes = name => [...document.querySelectorAll(`input[name="${{name}}"]`)];
  let state = {{ stage: tabs.length ? tabs[0].dataset.stage : null }};
  try {{
    const saved = JSON.parse(localStorage.getItem(KEY) || "null");
    if (saved) {{
      if (tabs.some(t => t.dataset.stage === saved.stage)) state.stage = saved.stage;
      for (const name of ["size", "kind"])
        if (Array.isArray(saved[name])) boxes(name).forEach(b => b.checked = saved[name].includes(b.value));
    }}
  }} catch (e) {{}}
  function apply() {{
    const sizes = boxes("size").filter(b => b.checked).map(b => b.value);
    const kinds = boxes("kind").filter(b => b.checked).map(b => b.value);
    tabs.forEach(t => t.setAttribute("aria-pressed", String(t.dataset.stage === state.stage)));
    document.querySelectorAll("section.stage").forEach(sec => {{
      sec.hidden = sec.dataset.stage !== state.stage;
      const perSize = sec.querySelectorAll(".size");
      perSize.forEach(d => d.hidden = !sizes.includes(d.dataset.size));
      sec.querySelector(".empty").hidden = !(perSize.length && sizes.length === 0);
    }});
    document.querySelectorAll(".blk").forEach(b => b.hidden = !kinds.includes(b.dataset.kind));
    try {{ localStorage.setItem(KEY, JSON.stringify({{ stage: state.stage, size: sizes, kind: kinds }})); }} catch (e) {{}}
  }}
  tabs.forEach(t => t.addEventListener("click", () => {{ state.stage = t.dataset.stage; apply(); }}));
  document.querySelectorAll(".bar input").forEach(b => b.addEventListener("change", apply));
  apply();
}})();
</script>
</body></html>"""


def main():
    args = parse_args()
    files = find(args.from_out) if args.from_out else {oid: getattr(args, oid) for oid in OUTPUTS}
    if not any(files.values()):
        raise SystemExit("no outputs found: give --from_out or the per-output flags")
    df = index(files)
    tables, n_cells = compute(df)
    rt, series = rs.runtimes(df)
    rt = rs.add_cores(rt, rs.allocated_cores(args.plan))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    source = str(args.from_out) if args.from_out else "gathered files"
    out = args.output_dir / f"{args.name}_report.html"
    out.write_text(render(df, tables, n_cells, source, rt, series))
    if len(rt):
        rt.to_csv(args.output_dir / f"{args.name}_runtime.tsv", sep="\t", index=False)
    for k, t in tables.items():
        if k != "pca_curves" and len(t):
            t.to_csv(args.output_dir / f"{args.name}_{k}.tsv", sep="\t", index=False)
    if len(tables["pca_curves"]):
        curves = tables["pca_curves"]
        long = pd.DataFrame([{"size": r["size"], "pair": r["pair"], "component": c + 1, "one_minus_abs_cos": v}
                             for _, r in curves.iterrows() for c, v in enumerate(r["values"])])
        long.to_csv(args.output_dir / f"{args.name}_pca_components.tsv", sep="\t", index=False)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
