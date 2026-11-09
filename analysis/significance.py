"""Is a difference between two implementations bigger than each one's own seed noise?

For one stage (Leiden here), two modules A and B, and one upstream lineage they share,
take every seed of A and every seed of B (20 + 20 runs) and every ARI between them:

    within A   seed-against-seed pairs of A      (A's own noise floor)
    within B   the same for B                     (B's own noise floor)
    between    every seed of A against every seed of B

Two one-sided statistics, one per side, so each implementation is judged against its
own floor and never against a floor pooled over implementations:

    gap_A = mean(within A) - mean(between)       > 0: switching to B moves A's result
                                                     further than re-seeding A does
    gap_B = mean(within B) - mean(between)       the same from B's side

The null is that the run labels A / B are exchangeable: both modules draw partitions
from the same distribution. Pairs share runs and are not independent, so the test
permutes runs, not pairs: shuffle the A / B labels among the 40 runs, recompute the
statistic, 9,999 times. With several upstreams, labels are shuffled within each
upstream (a stratified test) and the statistic is the mean over upstreams, so an
upstream with a different noise level cannot create or hide a difference. Essentially
a one-sided PERMANOVA on 1 - ARI, read per side.

A small gap with a tiny p-value is still a small effect: report the gaps and both
floors alongside p.
"""

import numpy as np
import pandas as pd

import concordance as cc


def _ari_matrix(codes):
    n = len(codes)
    m = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            m[i, j] = m[j, i] = cc.ari(codes[i], codes[j])
    return m


def _means(m, a):
    """Mean within A, within B and between, for each row of the boolean membership a (p x n)."""
    a = a.astype(np.float64)
    b = 1.0 - a
    na, nb = a.sum(1), b.sum(1)
    wa = np.einsum("pi,ij,pj->p", a, m, a) / 2 / (na * (na - 1) / 2)
    wb = np.einsum("pi,ij,pj->p", b, m, b) / 2 / (nb * (nb - 1) / 2)
    bt = np.einsum("pi,ij,pj->p", a, m, b) / (na * nb)
    return wa, wb, bt


def own_floor_test(strata, n_perm=9999, seed=0):
    """strata: list of (codes_A, codes_B), one per shared upstream; each a list of
    integer label arrays (cc.codes), one per seed. Returns a dict of results."""
    rng = np.random.default_rng(seed)
    obs_a, obs_b, null_a, null_b = [], [], [], []
    within_a, within_b, between = [], [], []
    for codes_a, codes_b in strata:
        na, nb = len(codes_a), len(codes_b)
        m = _ari_matrix(list(codes_a) + list(codes_b))
        member = np.r_[np.ones(na, bool), np.zeros(nb, bool)]
        wa, wb, bt = _means(m, member[None, :])
        obs_a.append(wa[0] - bt[0])
        obs_b.append(wb[0] - bt[0])
        iu = np.triu_indices(na, 1)
        within_a.append(m[:na, :na][iu])
        within_b.append(m[na:, na:][np.triu_indices(nb, 1)])
        between.append(m[:na, na:].ravel())
        perm = np.argsort(rng.random((n_perm, na + nb)), axis=1) < na  # each row: a random A set of size na
        pa, pb, pt = _means(m, perm)
        null_a.append(pa - pt)
        null_b.append(pb - pt)
    obs_a, obs_b = float(np.mean(obs_a)), float(np.mean(obs_b))
    null_a, null_b = np.mean(null_a, axis=0), np.mean(null_b, axis=0)
    within_a, within_b, between = map(np.concatenate, (within_a, within_b, between))
    return {
        "upstreams": len(strata),
        "within A median": float(np.median(within_a)),
        "within B median": float(np.median(within_b)),
        "between median": float(np.median(between)),
        "gap A": obs_a, "p A": float((1 + np.sum(null_a >= obs_a)) / (n_perm + 1)),
        "gap B": obs_b, "p B": float((1 + np.sum(null_b >= obs_b)) / (n_perm + 1)),
    }


def stage_tests(runs, n_perm=9999):
    """Every pair of modules at the last stage of `runs`, tested on the upstreams they share.

    runs: list of (nodes, codes) for one dataset size, nodes as from load.lineage. A
    module takes part on an upstream only if it ran there with at least two seeds and
    the same settings; a module run with several settings counts as one implementation
    per setting. Returns one row per pair of implementations.
    """
    # Stratum = the upstream lineage. An implementation = module plus its own settings:
    # modules have different parameter sets (blas_threads on one, flavor on another), so
    # settings never match across modules and must not be part of the stratum.
    groups = {}  # upstream nodes -> (module, settings) -> [codes, one per seed]
    for nodes, codes in runs:
        last = nodes[-1]
        groups.setdefault(nodes[:-1], {}).setdefault((last.module, last.settings), []).append(codes)
    impls = sorted({k for g in groups.values() for k, c in g.items() if len(c) > 1})
    variants = {}
    for m, st in impls:
        variants.setdefault(m, set()).add(st)
    name = {(m, st): m if len(variants[m]) == 1 else f"{m} {dict(st)}" for m, st in impls}
    rows = []
    for i, ma in enumerate(impls):
        for mb in impls[i + 1:]:
            strata = [(g[ma], g[mb]) for g in groups.values()
                      if len(g.get(ma, [])) > 1 and len(g.get(mb, [])) > 1]
            if not strata:
                continue
            r = own_floor_test(strata, n_perm=n_perm)
            rows.append({"A": name[ma], "B": name[mb], "runs A": sum(len(s[0]) for s in strata),
                         "runs B": sum(len(s[1]) for s in strata), **r})
    return pd.DataFrame(rows)
