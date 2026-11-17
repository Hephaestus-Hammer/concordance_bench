"""analysis/precision.py on fake float64 and float32 trees (tests/fake_phase2_tree.py, dtype):
in float32 only pc-randomized changes (another last component, so other neighbours and other
Leiden draws downstream) and every PCA job takes half the time."""

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "tests"))
import fake_phase2_tree  # noqa: E402
import precision  # noqa: E402


@pytest.fixture(scope="module")
def t(tmp_path_factory):
    d = tmp_path_factory.mktemp("prec")
    f64 = [fake_phase2_tree.build(d / f"out-phase2_float64_rep{r}", r, dtype="float64") for r in (1, 2)]
    f32 = [fake_phase2_tree.build(d / f"out-phase2_float32_rep{r}", r, dtype="float32") for r in (1, 2)]
    return precision.compare(f64, f32)


def _agree(t, level, group, measure, ds="dsA", sub="in-all", res=None):
    a = t["agreement"]
    a = a[(a["level"] == level) & (a["group"] == group) & (a["measure"] == measure) & (a["dataset"] == ds)
          & (a["subsample"] == sub)]
    if res is not None:
        a = a[a["resolution"] == res]
    assert len(a) >= 1
    return a


def test_pairs_are_cross_and_floor_only(t):
    p = t["pairs"]
    assert set(p["kind"]) == {"cross", "floor float64", "floor float32"}
    # pc-baseline: 2 folders per precision -> 4 cross pairs and one floor pair per precision
    g = p[(p["level"] == "pca") & (p["group"] == "pc-baseline") & (p["dataset"] == "dsA") & (p["subsample"] == "in-all")]
    assert (g["kind"] == "cross").sum() == 4 and (g["kind"] == "floor float64").sum() == 1


def test_exact_pca_is_unchanged_by_precision(t):
    a = _agree(t, "pca", "pc-baseline", "pca_agreement").iloc[0]
    assert a["cross_median"] == pytest.approx(1.0) and a["beyond_noise"] == False  # noqa: E712


def test_changed_pca_is_flagged(t):
    a = _agree(t, "pca", "pc-randomized", "pca_agreement")
    assert (a["cross_median"] < 1).all() and np.allclose(a["floor_median"], 1.0)
    assert (a["gap"] > 0).all()
    strict = precision.agreement(t["pairs"], tol=0)
    s = strict[(strict["level"] == "pca") & (strict["group"] == "pc-randomized")]
    assert (s["beyond_noise"] == True).all()  # noqa: E712


def test_knn_follows_its_pca(t):
    on_exact = _agree(t, "knn", "nn-baseline", "knn_shared").iloc[0]
    assert on_exact["cross_median"] == pytest.approx(1.0) and on_exact["beyond_noise"] == False  # noqa: E712
    # nn-scanpy-mt is not reproducible: its floor is below 1, and precision adds nothing on exact PCA
    on_rand = _agree(t, "knn", "pc-randomized > nn-baseline", "knn_shared")
    assert (on_rand["cross_median"] < 1).all()


def test_clusters_change_only_downstream_of_the_changed_pca(t):
    base = _agree(t, "cluster", "baseline", "ari")
    assert np.allclose(base["cross_median"], 1.0) and (base["beyond_noise"] == False).all()  # noqa: E712
    tuned = _agree(t, "cluster", "tuned-cpu", "jaccard")
    assert (tuned["beyond_noise"] == True).all() and (tuned["gap"] > 0.05).all()  # noqa: E712
    # all-gpu: cl-rapids is not reproducible, so its floor is low; float32 changes nothing upstream
    gpu = _agree(t, "cluster", "all-gpu", "ari")
    assert (gpu["floor_median"] < 1).all() and (gpu["beyond_noise"] == False).all()  # noqa: E712


def test_accuracy_delta(t):
    a = t["accuracy"]
    b = a[(a["group"] == "baseline") & (a["res_key"] == "oracle")]
    assert len(b) == 4 and (b["ari_delta"].abs() < 1e-12).all() and (b["ari_beyond_noise"] == False).all()  # noqa: E712
    assert set(a["res_key"]) == {"oracle", "0.5", "1", "2"}


def test_pca_cost_halves_and_nothing_else_moves(t):
    c = t["cost"]
    pca = c[c["stage"] == "pca"]
    assert np.allclose(pca["wall_s_ratio"], 0.5)
    assert (pca["wall_s_beyond_noise"] == True).all()  # noqa: E712
    rest = c[c["stage"] != "pca"]
    assert np.allclose(rest["wall_s_ratio"], 1.0) and (rest["wall_s_beyond_noise"] == False).all()  # noqa: E712


def test_folder_tags_match_index_runs(tmp_path):
    a, b = tmp_path / "x" / "out", tmp_path / "y" / "out"
    assert precision.folder_tags([a, b]) == ["out", "out+"]
