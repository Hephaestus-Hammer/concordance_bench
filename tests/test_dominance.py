"""analysis/dominance.py: the deck's relation (almost-stochastic dominance on accuracy, box
dominance on stability and log cost), its transitivity check and Hasse diagram."""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analysis"))
import dominance as dm  # noqa: E402


def test_eps_first_order_and_complement():
    lo, hi = [0.1, 0.2, 0.3], [0.4, 0.5, 0.6]
    assert dm.eps(hi, lo) == 0.0 and dm.eps(lo, hi) == 1.0
    a, b = [0.1, 0.5, 0.9], [0.3, 0.4, 0.6]  # crossing ECDFs
    assert 0 < dm.eps(a, b) < 1 and dm.eps(a, b) + dm.eps(b, a) == pytest.approx(1.0)
    assert dm.eps(a, a) == 0.0


def test_box_rules_on_stability_and_log_cost():
    A = dict(acc=[0.5, 0.6], stab=0.905, cost=100.0)
    B = dict(acc=[0.5, 0.6], stab=0.901, cost=101.0)  # same stability box, same log-1.25 cost box
    assert dm.dominates(A, B) and dm.dominates(B, A)  # a tie, not an order
    C = dict(acc=[0.5, 0.6], stab=0.905, cost=100.0 * 1.25 ** 2)  # two cost boxes worse
    assert dm.dominates(A, C) and not dm.dominates(C, A)
    D = dict(acc=[0.5, 0.6], stab=0.88, cost=10.0)  # cheaper, less stable: incomparable with A
    assert not dm.dominates(A, D) and not dm.dominates(D, A)


def test_relation_strict_part_transitivity_hasse_front():
    arms = {"a": dict(acc=[0.8, 0.9], stab=0.95, cost=10.0),
            "b": dict(acc=[0.6, 0.7], stab=0.95, cost=10.0),
            "c": dict(acc=[0.4, 0.5], stab=0.95, cost=10.0),
            "d": dict(acc=[0.9, 0.95], stab=0.50, cost=1.0)}
    rel = dm.relation(arms)
    assert ("a", "b") in rel and ("b", "c") in rel and ("a", "c") in rel
    assert not dm.intransitive(rel)
    assert dm.hasse(rel) == {("a", "b"), ("b", "c")}
    assert set(dm.front(list(arms), rel)) == {"a", "d"}
    assert dm.levels(list(arms), dm.hasse(rel)) == {"a": 0, "b": 1, "c": 2, "d": 0}


def test_intransitive_relation_is_reported():
    rel = {("a", "b"), ("b", "c")}
    assert dm.intransitive(rel) == [("a", "b", "c")]
