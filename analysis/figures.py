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
_EXTRA = [c for i, c in enumerate(plt.get_cmap("tab10").colors) if i != 7]  # no grey: grey = noise floor

plt.rcParams.update({
    "font.size": 9, "axes.edgecolor": INK_2, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": INK_2, "ytick.color": INK_2, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.titlesize": 10,
    "axes.titleweight": "bold", "axes.titlelocation": "left",
})


STAGE_ORDER = ["pca", "knn", "cluster"]


def _category_key(c):
    """Noise floors first, then one-stage groups in stage order, then multi-stage groups."""
    head = c.split(":")[0]
    if c == "replicate":
        return (0, -1, c)
    if c.startswith("seed"):
        stage = c.split(": ", 1)[-1]
        return (0, STAGE_ORDER.index(stage) if stage in STAGE_ORDER else 9, c)
    if head in STAGE_ORDER:
        return (1, STAGE_ORDER.index(head), c)
    return (2, c.count("+"), c)


def categories_in(values):
    return sorted(set(values), key=_category_key)


_assigned = {}


def colour(category):
    """Fixed colours for the noise floors and the plain stage groups; the module-pair groups get
    palette colours in the order first drawn, so a group keeps one colour across one report."""
    if category in CATEGORY_COLOURS:
        return CATEGORY_COLOURS[category]
    if category.startswith("seed"):
        return "#52514e"
    if category not in _assigned:
        _assigned[category] = _EXTRA[len(_assigned) % len(_EXTRA)]
    return _assigned[category]


def _panels(n, width=4.2, height=3.4):
    fig, ax = plt.subplots(1, n, figsize=(width * n, height), squeeze=False, constrained_layout=True)
    return fig, ax[0]


def pca_components(curves, sizes):
    """curves: rows with size, category, values (1 - |cos| per component).

    One line per category: the median over its pairs, with the range shaded.
    """
    fig, axes = _panels(len(sizes), width=7.0 if len(sizes) == 1 else 4.2)
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


def by_category(pairs, sizes, col, xlabel):
    """pairs: rows with size, category and a value column; one horizontal strip per group,
    noise floors on top, then one-stage groups by stage, then multi-stage groups."""
    order = categories_in(pairs["category"])
    fig, axes = plt.subplots(len(sizes), 1, figsize=(7.5, (0.3 * len(order) + 1.1) * len(sizes)),
                             squeeze=False, constrained_layout=True)
    axes = axes[:, 0]
    rng = np.random.default_rng(0)  # jitter only
    for ax, size in zip(axes, sizes):
        sub = pairs[pairs["size"] == size]
        for y, cat in enumerate(order):
            v = sub.loc[sub["category"] == cat, col].to_numpy(dtype=float)
            if len(v):
                ax.scatter(v, y + rng.uniform(-0.25, 0.25, len(v)), s=10, color=colour(cat),
                           edgecolor=SURFACE, linewidth=0.3, alpha=0.8, zorder=3)
                ax.vlines(np.median(v), y - 0.38, y + 0.38, color=INK, lw=1.4, zorder=4)
        ax.set_yticks(range(len(order)), order, fontsize=7.5)
        ax.set(ylim=(len(order) - 0.5, -0.5), title=size)
        ax.grid(axis="y", visible=False)
        for y in range(1, len(order)):  # a rule between the floors, one-stage and multi-stage blocks
            if _category_key(order[y])[0] != _category_key(order[y - 1])[0]:
                ax.axhline(y - 0.5, color=INK_2, lw=0.6)
    axes[-1].set_xlabel(xlabel)
    return fig


def truth_ari(truth, sizes):
    """truth: rows with size, pipeline (seeds merged), column, ari; one point per run."""
    pipelines = sorted(truth["pipeline"].unique())
    cols = sorted(truth["column"].unique())
    markers = ["o", "s", "^", "D"]
    fig, axes = _panels(len(sizes), width=7.0 if len(sizes) == 1 else 5.2, height=0.3 * len(pipelines) + 1.6)
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


def _module_colour(m, cache={}):
    if m not in cache:
        cache[m] = _EXTRA[len(cache) % len(_EXTRA)]
    return cache[m]


def runtime(rt, size):
    """Per stage (columns): wall time, mean and peak cores used, GPU utilisation (rows, when
    measured) per module; one point per job, line = median, dashed = cores allocated."""
    sub = rt[rt["size"] == size]
    stages = [s for s in ("pca", "knn", "cluster") if s in set(sub["stage"])]
    if not stages:
        return None
    rows = [("s", "wall time (s, log)", True, False), ("cores used", "mean cores used", False, True)]
    if sub["peak_cores"].notna().any():
        rows.append(("peak_cores", "peak cores used", False, True))
    if sub["gpu_util_mean"].notna().any():
        rows.append(("gpu_util_mean", "GPU utilisation (%, mean)", False, False))
    widths = [max(1, sub.loc[sub["stage"] == s, "module"].nunique()) for s in stages]
    fig, axes = plt.subplots(len(rows), len(stages), figsize=(max(6.5, 1.3 * sum(widths) + 1.5), 2.6 * len(rows)),
                             squeeze=False, constrained_layout=True, gridspec_kw={"width_ratios": widths})
    rng = np.random.default_rng(0)  # jitter only
    for j, stage in enumerate(stages):
        s = sub[sub["stage"] == stage]
        mods = sorted(s["module"].unique())
        for i, (col, label, log, alloc_line) in enumerate(rows):
            ax = axes[i, j]
            for x, m in enumerate(mods):
                v = s.loc[s["module"] == m, col].to_numpy(dtype=float)
                v = v[~np.isnan(v)]
                if len(v):
                    ax.scatter(x + rng.uniform(-0.2, 0.2, len(v)), v, s=12, color=_module_colour(m),
                               alpha=0.8, zorder=3)
                    ax.hlines(np.median(v), x - 0.3, x + 0.3, color=INK, lw=1.4, zorder=4)
            if alloc_line:
                alloc = s["cores allocated"].dropna()
                if len(alloc):
                    ax.axhline(alloc.iloc[0], color=INK_2, ls="--", lw=1, zorder=2)
                    ax.text(len(mods) - 0.5, alloc.iloc[0], " allocated", va="bottom", ha="right",
                            fontsize=7, color=INK_2)
            if not log:
                ax.set_ylim(bottom=0)
            ax.set_xticks(range(len(mods)), mods if i == len(rows) - 1 else [""] * len(mods),
                          rotation=30, ha="right")
            ax.set(xlim=(-0.6, len(mods) - 0.4), yscale="log" if log else "linear")
            ax.grid(axis="x", visible=False)
            if i == 0:
                ax.set_title(stage)
            if j == 0:
                ax.set_ylabel(label)
    return fig


def runtime_traces(series, rt, size):
    """Cores used over time, one line per job (denet traces), one panel per stage."""
    keys = [k for k in series if k[0] == size]
    stages = [s for s in ("pca", "knn", "cluster") if any(k[1] == s for k in keys)]
    if not stages:
        return None
    module_of = {(r["stage"], r["pipeline"]): r["module"] for _, r in rt[rt["size"] == size].iterrows()}
    fig, axes = _panels(len(stages), width=4.4, height=3.2)
    for ax, stage in zip(axes, stages):
        seen = set()
        for (_, st, label) in [k for k in keys if k[1] == stage]:
            d = series[(size, st, label)]
            m = module_of.get((st, label), "?")
            ax.plot(d["t"], d["cores"], color=_module_colour(m), lw=0.8, alpha=0.5,
                    label=None if m in seen else m)
            seen.add(m)
        alloc = rt.loc[(rt["size"] == size) & (rt["stage"] == stage), "cores allocated"].dropna()
        if len(alloc):
            ax.axhline(alloc.iloc[0], color=INK_2, ls="--", lw=1)
        ax.set(title=stage, xlabel="seconds since start", ylim=(0, None))
        ax.legend(frameon=False, fontsize=7, loc="upper right")
    axes[0].set_ylabel("cores used")
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


PHASE_COLOURS = {"load": "#2a78d6", "write": "#1baf7a", "(unphased)": "#b0afab"}
_PHASE_EXTRA = ["#eb6834", "#8a5cd6", "#c9962a", "#d63a7a", "#2aa3b3"]


def _phase_colour(p, cache={}):
    if p in PHASE_COLOURS:
        return PHASE_COLOURS[p]
    if p not in cache:
        cache[p] = _PHASE_EXTRA[len(cache) % len(_PHASE_EXTRA)]
    return cache[p]


def runtime_phases(ph, size, allocated=None):
    """One row per stage and module that logged phases. Left: median wall time per phase,
    "(unphased)" first, then the phases in the order the module runs them. Right: median mean cores used per phase,
    with the stage's allocated cores as a tick."""
    sub = ph[ph["size"] == size]
    if not len(sub):
        return None
    # unphased first: most of it is start-up and imports, before the first phase; then by start
    starts = sub[sub["phase"] != "(unphased)"].groupby("phase")["start_s"].median().sort_values()
    order = ["(unphased)", *starts.index]
    stage_o = {s: i for i, s in enumerate(STAGE_ORDER)}
    rows = sorted({(s, m) for s, m in zip(sub["stage"], sub["module"])},
                  key=lambda x: (stage_o.get(x[0], 9), x[1]))
    med = sub.groupby(["stage", "module", "phase"])[["duration_s", "mean_cores"]].median()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.5, 0.45 * len(rows) + 1.4), constrained_layout=True,
                                 gridspec_kw={"width_ratios": [3, 2]}, sharey=True)
    for y, (stage, module) in enumerate(rows):
        left = 0.0
        for p in order:
            if (stage, module, p) not in med.index:
                continue
            d, c = med.loc[(stage, module, p)]
            a1.barh(y, d, left=left, color=_phase_colour(p), height=0.6, edgecolor=SURFACE, linewidth=0.5)
            left += d
            a2.scatter(c, y, color=_phase_colour(p), s=22, zorder=3, edgecolor=SURFACE, linewidth=0.3)
        if allocated and stage in allocated:
            a2.vlines(allocated[stage], y - 0.3, y + 0.3, color=INK_2, ls="--", lw=1)
    a1.set_yticks(range(len(rows)), [f"{s} · {m}" for s, m in rows], fontsize=7.5)
    a1.set(ylim=(len(rows) - 0.5, -0.5), xlabel="wall time (s, median per phase)", title=size)
    a2.set(xlabel="mean cores used (median; dashed = allocated)", xlim=(0, None))
    for a in (a1, a2):
        a.grid(axis="y", visible=False)
    handles = [plt.Line2D([], [], marker="s", ls="", color=_phase_colour(p)) for p in order]
    fig.legend(handles, order, frameon=False, fontsize=7, loc="outside lower center", ncol=len(order))
    return fig
