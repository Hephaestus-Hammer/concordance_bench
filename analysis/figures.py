"""Figures for the concordance report. Each function takes a summary table and returns a figure."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

EPS = 1e-16
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"

# What differs between the two runs of a pair. Seed and replicate are the noise
# floor, so they get neutral greys; stage differences get colours.
CATEGORY_COLOURS = {
    "replicate": "#b0afab",
    "seed: pca": "#8c8b87",
    "seed: knn": "#6b6a66",
    "seed: cluster": "#3d3c3a",
    "pca": "#2a78d6",
    "knn": "#eb6834",
    "cluster": "#1baf7a",
    "pca+knn": "#8a5cd6",
    "pca+cluster": "#c9962a",
    "knn+cluster": "#d63a7a",
    "pca+knn+cluster": "#2aa3b3",
}
_EXTRA = plt.get_cmap("tab10").colors

plt.rcParams.update({
    "font.size": 9, "axes.edgecolor": INK_2, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": INK_2, "ytick.color": INK_2, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.titlesize": 10,
    "axes.titleweight": "bold", "axes.titlelocation": "left",
})


def categories_in(values):
    known = [c for c in CATEGORY_COLOURS if c in set(values)]
    return known + sorted(set(values) - set(known))


def colour(category):
    if category in CATEGORY_COLOURS:
        return CATEGORY_COLOURS[category]
    if category.startswith("seed"):
        return "#52514e"
    return _EXTRA[hash(category) % len(_EXTRA)]


def _panels(n, width=4.2, height=3.4):
    fig, ax = plt.subplots(1, n, figsize=(width * n, height), squeeze=False, constrained_layout=True)
    return fig, ax[0]


def pca_components(curves, sizes):
    """curves: rows with size, pair, values (1 - |cos| per component)."""
    fig, axes = _panels(len(sizes))
    for ax, size in zip(axes, sizes):
        sub = curves[curves["size"] == size]
        for _, r in sub.iterrows():
            y = np.clip(r["values"], EPS, None)
            ax.plot(np.arange(1, len(y) + 1), y, lw=1.4, marker="o", ms=2, label=r["pair"])
        ax.set(yscale="log", xlabel="principal component", title=size)
        if len(sub):
            ax.legend(frameon=False, fontsize=7, loc="upper left")
    axes[0].set_ylabel("1 − |cos|  (log; lower = more similar)")
    return fig


def knn_pairs(knn, sizes):
    """knn: rows with size, pair, category, mean_shared."""
    n_rows = max([len(knn[knn["size"] == s]) for s in sizes] + [1])
    fig, axes = _panels(len(sizes), width=5.2, height=0.24 * n_rows + 1.4)
    order = categories_in(knn["category"])
    for ax, size in zip(axes, sizes):
        sub = knn[knn["size"] == size].copy()
        sub["_c"] = sub["category"].map(order.index)
        sub = sub.sort_values(["_c", "mean_shared"])
        y = np.arange(len(sub))
        ax.scatter(sub["mean_shared"], y, c=[colour(c) for c in sub["category"]], s=28, zorder=3)
        ax.set_yticks(y, sub["pair"], fontsize=6.5)
        ax.set(xlabel="mean shared-neighbour fraction", title=size)
        ax.grid(axis="y", visible=False)
    _category_legend(fig, order)
    return fig


def ari_by_category(pairs, sizes):
    """pairs: rows with size, category, ari."""
    order = categories_in(pairs["category"])
    fig, axes = _panels(len(sizes), width=max(4.2, 0.6 * len(order) + 1.5))
    rng = np.random.default_rng(0)  # jitter only
    for ax, size in zip(axes, sizes):
        sub = pairs[pairs["size"] == size]
        for x, cat in enumerate(order):
            v = sub.loc[sub["category"] == cat, "ari"].to_numpy()
            if len(v):
                ax.scatter(x + rng.uniform(-0.25, 0.25, len(v)), v, s=12, color=colour(cat),
                           edgecolor=SURFACE, linewidth=0.4, zorder=3)
                ax.hlines(np.median(v), x - 0.35, x + 0.35, color=INK, lw=1.4, zorder=4)
        ax.set_xticks(range(len(order)), order, rotation=35, ha="right")
        ax.set(xlim=(-0.6, len(order) - 0.4), title=size)
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("ARI between runs (1 = identical; line = median)")
    return fig


def truth_ari(truth, sizes):
    """truth: rows with size, pipeline, column, ari."""
    pipelines = sorted(truth["pipeline"].unique())
    cols = sorted(truth["column"].unique())
    markers = ["o", "s", "^", "D"]
    fig, axes = _panels(len(sizes), width=5.2, height=0.24 * len(pipelines) + 1.4)
    y_of = {p: i for i, p in enumerate(pipelines)}
    for ax, size in zip(axes, sizes):
        sub = truth[truth["size"] == size]
        for j, col in enumerate(cols):
            s = sub[sub["column"] == col]
            ax.scatter(s["ari"], s["pipeline"].map(y_of), marker=markers[j % 4], s=26,
                       color=INK_2 if j else "#2a78d6", label=col, zorder=3)
        ax.set_yticks(range(len(pipelines)), pipelines, fontsize=6.5)
        ax.set(xlabel="ARI against annotation", title=size)
        ax.grid(axis="y", visible=False)
    axes[-1].legend(frameon=False, fontsize=7, loc="lower right", title="label column", title_fontsize=7)
    return fig


def scaling(pairs, knn, n_cells):
    """Median agreement per category against the number of cells."""
    fig, axes = _panels(2)
    for ax, (table, col, ylabel) in zip(axes, [(knn, "mean_shared", "median shared-neighbour fraction"),
                                              (pairs, "ari", "median ARI between runs")]):
        if not len(table):
            ax.set_visible(False)
            continue
        t = table.assign(n=table["size"].map(n_cells))
        for cat in categories_in(t["category"]):
            m = t[t["category"] == cat].groupby("n")[col].median()
            ax.plot(m.index, m.values, marker="o", color=colour(cat), label=cat)
        ax.set(xscale="log", xlabel="cells", ylabel=ylabel)
        ax.legend(frameon=False, fontsize=7)
    return fig


def _category_legend(fig, order):
    handles = [plt.Line2D([], [], marker="o", ls="", color=colour(c)) for c in order]
    fig.legend(handles, order, frameon=False, fontsize=7, loc="outside lower center",
               ncol=min(len(order), 5), title="what differs", title_fontsize=7)
