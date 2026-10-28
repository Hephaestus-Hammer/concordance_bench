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
    """curves: rows with size, category, values (1 - |cos| per component).

    One line per category: the median over its pairs, with the range shaded.
    """
    fig, axes = _panels(len(sizes))
    for ax, size in zip(axes, sizes):
        sub = curves[curves["size"] == size]
        for cat in categories_in(sub["category"]):
            v = np.clip(np.stack(sub.loc[sub["category"] == cat, "values"].to_list()), EPS, None)
            x = np.arange(1, v.shape[1] + 1)
            ax.fill_between(x, v.min(0), v.max(0), color=colour(cat), alpha=0.2, lw=0)
            ax.plot(x, np.median(v, 0), color=colour(cat), lw=1.4, marker="o", ms=2,
                    label=f"{cat} ({len(v)} pairs)")
        ax.set(yscale="log", xlabel="principal component", title=size)
        if len(sub):
            ax.legend(frameon=False, fontsize=7, loc="upper left")
    axes[0].set_ylabel("1 − |cos|  (log; line = median, band = range)")
    return fig


def by_category(pairs, sizes, col, ylabel):
    """pairs: rows with size, category and a value column; one strip per category."""
    order = categories_in(pairs["category"])
    fig, axes = plt.subplots(len(sizes), 1, figsize=(max(5.0, 0.75 * len(order) + 1.5), 2.9 * len(sizes)),
                             squeeze=False, constrained_layout=True)
    axes = axes[:, 0]
    rng = np.random.default_rng(0)  # jitter only
    for ax, size in zip(axes, sizes):
        sub = pairs[pairs["size"] == size]
        for x, cat in enumerate(order):
            v = sub.loc[sub["category"] == cat, col].to_numpy(dtype=float)
            if len(v):
                ax.scatter(x + rng.uniform(-0.25, 0.25, len(v)), v, s=10, color=colour(cat),
                           edgecolor=SURFACE, linewidth=0.3, alpha=0.8, zorder=3)
                ax.hlines(np.median(v), x - 0.35, x + 0.35, color=INK, lw=1.4, zorder=4)
        ax.set_xticks(range(len(order)), order if ax is axes[-1] else [""] * len(order),
                      rotation=30, ha="right")
        ax.set(xlim=(-0.6, len(order) - 0.4), title=size)
        ax.grid(axis="x", visible=False)
    fig.supylabel(ylabel, fontsize=9)
    return fig


def truth_ari(truth, sizes):
    """truth: rows with size, pipeline (seeds merged), column, ari; one point per run."""
    pipelines = sorted(truth["pipeline"].unique())
    cols = sorted(truth["column"].unique())
    markers = ["o", "s", "^", "D"]
    fig, axes = _panels(len(sizes), width=5.2, height=0.3 * len(pipelines) + 1.6)
    y_of = {p: i for i, p in enumerate(pipelines)}
    for ax, size in zip(axes, sizes):
        sub = truth[truth["size"] == size]
        for j, col in enumerate(cols):
            s = sub[sub["column"] == col]
            off = (j - (len(cols) - 1) / 2) * 0.22
            ax.scatter(s["ari"], s["pipeline"].map(y_of) + off, marker=markers[j % 4], s=12,
                       color=INK_2 if j else "#2a78d6", alpha=0.7, label=col, zorder=3)
        ax.set_yticks(range(len(pipelines)), pipelines, fontsize=6.5)
        ax.set(xlabel="ARI against annotation (one point per run)", title=size)
        ax.grid(axis="y", visible=False)
    axes[-1].legend(frameon=False, fontsize=7, loc="lower right", title="label column", title_fontsize=7)
    return fig


def scaling(pairs, knn, n_cells):
    """Median agreement per category against the number of cells."""
    fig, axes = _panels(2, width=5.2)
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
        ax.legend(frameon=False, fontsize=7, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    return fig


def _category_legend(fig, order):
    handles = [plt.Line2D([], [], marker="o", ls="", color=colour(c)) for c in order]
    fig.legend(handles, order, frameon=False, fontsize=7, loc="outside lower center",
               ncol=min(len(order), 5), title="what differs", title_fontsize=7)
