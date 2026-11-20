"""The dominance relation of Ben's deck ("Stochastic dominance, feasibility regions, ...", slides
7-10), for the Full pipeline tab. A stand-in for his almost-dominance-perf code, written from
the deck's definitions; swap in his functions once that repository is to hand.

Accuracy is a distribution over seeds, so it enters as almost-stochastic dominance
(Leshno & Levy 2002, in the form of Dror et al. 2019):

    eps(A, B) = integral (F_A(t) - F_B(t))+ dt / integral |F_A(t) - F_B(t)| dt,
    A >=acc B  iff  eps(A, B) <= tau

eps is the share of the area between the two ECDFs on the wrong side for A; eps(A, B) +
eps(B, A) = 1 whenever the curves differ. Identical distributions have no area between them:
eps = 0 both ways (each at least as good as the other).

Stability s and cost c are scalars, so they enter as box dominance (a partial order by
construction):

    floor(s_A / ds) >= floor(s_B / ds)   and   floor(log c_A / dc) <= floor(log c_B / dc)

A > B iff all three hold. The deck's defaults: tau = 0.01, ds = 0.01, dc = log 1.25. Cost is
the deck's: peak GB x wall time of one answer, the whole resolution sweep at the oracle
resolution. Almost-stochastic dominance is not transitive by construction, so the relation is
checked before it is drawn: an intransitive relation is not an order and has no Hasse diagram.
"""

import itertools
import math

import numpy as np

TAU, DELTA_S, DELTA_C = 0.01, 0.01, math.log(1.25)


def eps(a, b):
    """Almost-stochastic dominance violation of A over B: the share of the area between the
    ECDFs where A's is above B's (A worse). 0 = first-order dominance; 0 also when equal."""
    a, b = np.sort(np.asarray(a, float)), np.sort(np.asarray(b, float))
    t = np.unique(np.concatenate([a, b]))
    if len(t) < 2:
        return 0.0
    fa = np.searchsorted(a, t[:-1], side="right") / len(a)
    fb = np.searchsorted(b, t[:-1], side="right") / len(b)
    w, d = np.diff(t), fa - fb
    den = float(np.sum(np.abs(d) * w))
    return 0.0 if den == 0 else float(np.sum(np.clip(d, 0, None) * w) / den)


def dominates(A, B, tau=TAU, ds=DELTA_S, dc=DELTA_C):
    """A > B on accuracy (samples), stability and cost (scalars): dicts with acc, stab, cost."""
    if eps(A["acc"], B["acc"]) > tau:
        return False
    if not (np.isfinite(A["stab"]) and np.isfinite(B["stab"]) and A["cost"] > 0 and B["cost"] > 0):
        return False
    return (math.floor(A["stab"] / ds) >= math.floor(B["stab"] / ds)
            and math.floor(math.log(A["cost"]) / dc) <= math.floor(math.log(B["cost"]) / dc))


def relation(arms, **kw):
    """{(a, b): a dominates b} over named arms ({name: dict(acc, stab, cost)}), a != b."""
    return {(a, b) for a, b in itertools.permutations(arms, 2) if dominates(arms[a], arms[b], **kw)}


def strict(rel):
    """The strict part: a over b and not b over a (mutual dominance is a tie, not an order)."""
    return {(a, b) for a, b in rel if (b, a) not in rel}


def intransitive(rel):
    """Triples (a, b, c) with a > b and b > c but not a > c: empty iff the relation is transitive."""
    out = []
    for a, b in rel:
        for b2, c in rel:
            if b2 == b and a != c and (a, c) not in rel:
                out.append((a, b, c))
    return out


def hasse(rel):
    """Covering edges of a transitive strict relation: a > b with nothing strictly between."""
    s = strict(rel)
    nodes = {x for e in s for x in e}
    return {(a, b) for a, b in s if not any((a, c) in s and (c, b) in s for c in nodes - {a, b})}


def front(names, rel):
    """Arms no other arm strictly dominates."""
    s = strict(rel)
    return [n for n in names if not any((m, n) in s for m in names if m != n)]


def levels(names, cover):
    """Layer of each arm for drawing: 0 for the undominated, else 1 + the deepest arm above it."""
    lev = {}

    def depth(n):
        if n not in lev:
            above = [a for a, b in cover if b == n]
            lev[n] = 0 if not above else 1 + max(depth(a) for a in above)
        return lev[n]

    for n in names:
        depth(n)
    return lev
