"""Concordance report: every metric and figure from one run of the plan, in one HTML file.

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
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import concordance as cc
import figures as fg
from load import OUTPUTS, find, index, missing, pair_category

DESCRIPTIONS = {
    "runs": """What the report was built from: the number of output files per stage and
        dataset size. <b>Missing combinations</b> lists every combination that should exist
        (each upstream lineage found &times; each module and parameter set found at that stage)
        but has no output, usually a failed job. Everything below is computed only from the
        files that exist.""",
    "labels": """Pipelines are named by their module ids from PCA on
        (<code>pc-… &gt; nn-… &gt; cl-…</code>). A pair of runs is grouped by <b>what differs</b>
        between them: the stages whose module or settings differ (<code>pca</code>,
        <code>knn</code>, <code>pca+knn</code>, …), <code>seed</code> if only random seeds differ,
        or <code>replicate</code> if only the input replicate differs. Seed and replicate pairs are
        the noise floor; colours are the same in every figure.""",
    "pca": """One line per pair of PCA runs on the same cells. The y-axis is 1&nbsp;&minus;&nbsp;|cos|
        between the cell scores of matching components, on a log scale (zero is drawn at
        10<sup>&minus;16</sup>). |cos| ignores sign, which is arbitrary in PCA. Values near
        10<sup>&minus;16</sup> mean identical up to round-off; values near 1 mean the component
        points somewhere else. Late components with nearly equal variance can swap or mix
        without changing the subspace, so the table also gives the largest principal angle
        between the spans of the first <i>k</i> components, which is insensitive to that.""",
    "knn": """Each point is a pair of kNN graphs on the same cells. The x-axis is the mean over
        cells of the shared-neighbour fraction: neighbours found in both graphs divided by the
        size of the larger neighbour set (the cell itself is not counted). <code>knn</code> pairs
        share their PCA input, so they show the kNN step's own effect; <code>pca</code> pairs use
        the same kNN module on different PCA outputs, so they show what PCA differences carry
        into the graph. The table adds the share of cells whose neighbour sets are identical.""",
    "ari": """Each point is one pair of Leiden clusterings of the same cells, measured by the
        adjusted Rand index (ARI; 1 = identical partitions, about 0 = chance), grouped by what
        differs between the two pipelines. The line is the median. A stage whose pairs fall
        inside the spread of the <code>seed</code> pairs changes the clustering no more than
        re-running with another seed.""",
    "truth": """ARI of each pipeline's clustering against the annotated cell types, one marker
        per annotation column in the truth file. The number of clusters at a fixed resolution
        usually differs from the number of annotated types, which keeps the ARI below 1 for
        every pipeline: compare pipelines with each other, not with 1. The table gives the
        number of clusters and the ARI per size; NMI is in the TSV.""",
    "scaling": """Median agreement per group against the number of cells: kNN shared-neighbour
        fraction (left) and ARI between clusterings (right). Shows whether disagreement grows
        with dataset size.""",
}


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--output_dir", type=Path, default=Path("results/report"))
    p.add_argument("--name", default="concordance")
    p.add_argument("--from_out", type=Path, help="find every output under this ob output tree")
    for oid in OUTPUTS:
        p.add_argument(f"--{oid}", type=Path, nargs="+", default=[])
    return p.parse_args()


# ---- compute -------------------------------------------------------------------

def compute(df):
    """All summary tables, one dataset size at a time to keep memory bounded."""
    t = {k: [] for k in ("pca_curves", "pca_angles", "knn", "ari", "truth")}
    n_cells = {}
    for size, g in df.groupby("size"):
        order = _cell_order(g)
        n_cells[size] = len(order)
        by = {oid: g[g["output"] == oid].reset_index(drop=True) for oid in OUTPUTS}

        emb = [cc.read_embedding(p).reindex(order) for p in by["embedding_tsv"]["path"]]
        _check_complete(emb, by["embedding_tsv"])
        for i, j in itertools.combinations(range(len(emb)), 2):
            a, b = by["embedding_tsv"].iloc[i], by["embedding_tsv"].iloc[j]
            pair, cat = f"{a['label']}  vs  {b['label']}", pair_category(a["nodes"], b["nodes"])
            t["pca_curves"].append({"size": size, "pair": pair, "category": cat,
                                    "values": cc.pca_one_minus_abs_cos(emb[i], emb[j])})
            row = {"size": size, "pair": pair, "category": cat}
            for k in (10, 20, 50):
                if k <= min(emb[i].shape[1], emb[j].shape[1]):
                    row[f"max angle, first {k} PCs (deg)"] = cc.pca_max_angle(emb[i], emb[j], k)
            t["pca_angles"].append(row)
        del emb

        graphs = []
        for p in by["neighbors_h5"]["path"]:
            d, cells = cc.read_neighbors(p)
            graphs.append(cc.align_graph(d, cells, order))
        for i, j in itertools.combinations(range(len(graphs)), 2):
            a, b = by["neighbors_h5"].iloc[i], by["neighbors_h5"].iloc[j]
            frac = cc.knn_shared_fraction(graphs[i], graphs[j])
            t["knn"].append({"size": size, "pair": f"{a['label']}  vs  {b['label']}",
                             "category": pair_category(a["nodes"], b["nodes"]),
                             "mean_shared": float(frac.mean()),
                             "cells_identical": float((frac == 1).mean())})
        del graphs

        labels = [cc.read_clusters(p).reindex(order) for p in by["clusters_tsv"]["path"]]
        _check_complete(labels, by["clusters_tsv"])
        for i, j in itertools.combinations(range(len(labels)), 2):
            a, b = by["clusters_tsv"].iloc[i], by["clusters_tsv"].iloc[j]
            t["ari"].append({"size": size, "a": a["label"], "b": b["label"],
                             "category": pair_category(a["nodes"], b["nodes"]),
                             "ari": cc.ari(labels[i], labels[j])})
        if len(by["rawdata_clusters_truth"]):
            truth = cc.read_truth(by["rawdata_clusters_truth"]["path"].iloc[0]).reindex(order)
            for lab, (_, r) in zip(labels, by["clusters_tsv"].iterrows()):
                for col in truth.columns:
                    t["truth"].append({"size": size, "pipeline": r["label"], "column": col,
                                       "ari": cc.ari(truth[col], lab), "nmi": cc.nmi(truth[col], lab),
                                       "clusters": lab.nunique(), "annotated types": truth[col].nunique()})

    tables = {k: pd.DataFrame(v) for k, v in t.items()}
    for k in ("knn", "ari", "pca_angles"):
        if len(tables[k]) == 0:
            tables[k] = pd.DataFrame(columns=["size", "category"])
    return tables, n_cells


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
    """One row per pipeline: clusters and ARI per annotation column, per size."""
    w = truth.pivot_table(index="pipeline", columns=["size", "column"], values="ari")
    k = truth.pivot_table(index="pipeline", columns="size", values="clusters")
    cols = {}
    for s in sizes:
        if s in k:
            cols[f"{s}: clusters"] = k[s]
        for c in sorted(truth["column"].unique()):
            if (s, c) in w:
                cols[f"{s}: ARI {c}"] = w[(s, c)]
    return pd.DataFrame(cols).reset_index()


def section(title, key, body, note=None):
    n = f"<p class='note'>{html.escape(note)}</p>" if note else ""
    return f"<section><h2>{title}</h2><p class='desc'>{DESCRIPTIONS[key]}</p>{n}{body}</section>"


def render(df, tables, n_cells, source):
    sizes = sorted(n_cells, key=n_cells.get)
    counts = (df.assign(stage=df["output"]).pivot_table(index="size", columns="stage", values="path",
                                                         aggfunc="count", fill_value=0)
              .reindex(sizes).rename_axis(columns=None).reset_index())
    counts.insert(1, "cells", counts["size"].map(n_cells))
    miss = pd.concat([missing(df, oid) for oid in OUTPUTS], ignore_index=True)
    has_floor = tables["ari"]["category"].isin(["seed", "replicate"]).any()
    floor_note = None if has_floor else (
        "No seed or replicate pairs in this run, so there is no noise floor yet: "
        "differences below cannot be compared with seed noise.")

    parts = [section("1. Runs found", "runs",
                     table_html(counts) + "<h3>Missing combinations</h3>" + table_html(miss)),
             f"<section><h2>2. How pairs are labelled</h2><p class='desc'>{DESCRIPTIONS['labels']}</p></section>"]

    if len(tables["pca_curves"]):
        parts.append(section("3. PCA: component agreement", "pca",
                             fig_html(fg.pca_components(tables["pca_curves"], sizes))
                             + table_html(tables["pca_angles"])))
    if len(tables["knn"]) and "pair" in tables["knn"]:
        parts.append(section("4. kNN: neighbour agreement", "knn",
                             fig_html(fg.knn_pairs(tables["knn"], sizes))
                             + table_html(tables["knn"], summary="All pairs"), floor_note))
    if len(tables["ari"]) and "ari" in tables["ari"]:
        summary = (tables["ari"].groupby(["size", "category"])["ari"]
                   .agg(pairs="count", min="min", median="median", max="max").reset_index())
        parts.append(section("5. Leiden: agreement between runs", "ari",
                             fig_html(fg.ari_by_category(tables["ari"], sizes))
                             + table_html(summary), floor_note))
    if len(tables["truth"]):
        parts.append(section("6. Leiden: agreement with the annotation", "truth",
                             fig_html(fg.truth_ari(tables["truth"], sizes))
                             + table_html(truth_wide(tables["truth"], sizes), summary="Per pipeline")))
    if len(sizes) > 1 and (len(tables["ari"]) or len(tables["knn"])):
        parts.append(section("7. Scaling with dataset size", "scaling",
                             fig_html(fg.scaling(tables["ari"], tables["knn"], n_cells))))

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Concordance report</title>
<style>
  :root {{ --ink:#0b0b0b; --ink2:#52514e; --line:#e4e3df; --bg:#fcfcfb; --note:#fff4e5; }}
  body {{ background:var(--bg); color:var(--ink); font:15px/1.5 system-ui,-apple-system,sans-serif;
         max-width:1100px; margin:0 auto; padding:24px 16px 64px; }}
  h1 {{ font-size:1.6rem; margin:0 0 4px; }} h2 {{ font-size:1.2rem; margin:40px 0 6px; }}
  h3 {{ font-size:1rem; margin:20px 0 6px; }}
  .meta {{ color:var(--ink2); font-size:.9rem; }} .desc {{ max-width:75ch; }}
  .note {{ background:var(--note); padding:6px 10px; border-radius:4px; max-width:75ch; font-size:.9rem; }}
  img {{ max-width:100%; height:auto; display:block; margin:12px 0; }}
  table.t {{ border-collapse:collapse; font-size:.8rem; margin:8px 0; display:block; overflow-x:auto; }}
  table.t th, table.t td {{ padding:3px 8px; border-bottom:1px solid var(--line); text-align:left; }}
  table.t td:first-child, table.t td:nth-child(2) {{ white-space:nowrap; }}
  code {{ font-size:.85em; }}
  summary {{ cursor:pointer; color:var(--ink2); font-size:.9rem; margin:8px 0; }}
</style></head><body>
<h1>Concordance report</h1>
<p class="meta">Generated {stamp} from {html.escape(source)}: {len(df)} output files,
{len(sizes)} dataset size(s).</p>
{''.join(parts)}
</body></html>"""


def main():
    args = parse_args()
    files = find(args.from_out) if args.from_out else {oid: getattr(args, oid) for oid in OUTPUTS}
    if not any(files.values()):
        raise SystemExit("no outputs found: give --from_out or the per-output flags")
    df = index(files)
    tables, n_cells = compute(df)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    source = str(args.from_out) if args.from_out else "gathered files"
    out = args.output_dir / f"{args.name}_report.html"
    out.write_text(render(df, tables, n_cells, source))
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
