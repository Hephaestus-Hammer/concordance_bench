"""analysis/phase2.py on a fake Phase 2 tree with known effects (tests/fake_phase2_tree.py)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "tests"))
import fake_phase2_tree  # noqa: E402
import phase2  # noqa: E402
from load import index_runs  # noqa: E402

@pytest.fixture(scope="module")
def t(tmp_path_factory):
    d = tmp_path_factory.mktemp("p2")
    df = index_runs([fake_phase2_tree.build(d / "out", 0), fake_phase2_tree.build(d / "out-rep1", 1)])
    runs = phase2.clustering_table(df)
    runs, bounds = phase2.accuracy(df, runs)
    stab, repro = phase2.stability(runs), phase2.reproducibility(runs)
    rt = phase2.rs.runtimes(df)[0]
    cold = phase2.cold_starts(rt)
    pca, pca_pairs = phase2.pca_stage(df)
    knn, knn_pairs = phase2.knn_stage(df)
    pca, knn = phase2.add_cost(pca, rt, cold), phase2.add_cost(knn, rt, cold)
    ans = phase2.answers(runs, rt, cold)
    stages = phase2.stages_summary(runs, bounds, pca, pca_pairs, knn, knn_pairs, rt, cold)
    pipes, pipe_runs = phase2.pipelines_summary(phase2.named_pipeline_runs(runs), bounds, stab, repro, ans)
    return dict(df=df, runs=runs, bounds=bounds, stab=stab, repro=repro, pca=pca, knn=knn,
                stages=stages, ans=ans, pipes=pipes, pipe_runs=pipe_runs)


def _stage(t, stage, module, ds="dsA", sub="in-small"):
    s = t["stages"]
    s = s[(s["stage"] == stage) & (s["module"] == module) & (s["dataset"] == ds) & (s["subsample"] == sub)]
    assert len(s) == 1
    return s.iloc[0]


def _pipe(t, name, ds="dsA", sub="in-small"):
    p = t["pipes"]
    p = p[(p["pipeline"] == name) & (p["dataset"] == ds) & (p["subsample"] == sub)]
    assert len(p) == 1
    return p.iloc[0]


def test_bounds(t):
    b = t["bounds"]
    assert len(b) == 4 and (b["chance"] == 0).all() and (b["oracle"] > 0.95).all()


def test_pca_fidelity_is_the_missed_components_variance_share(t):
    # pc-randomized replaces the exact PCA's last component: it loses exactly that share
    emb = t["pca"]
    row = _stage(t, "pca", "pc-randomized")
    base = emb[(emb["module"] == "pc-baseline") & (emb["dataset"] == "dsA") & (emb["subsample"] == "in-small")]
    assert base["fidelity"].iloc[0] == pytest.approx(1.0)
    assert 0.95 < row["fidelity"] < 1.0
    assert _stage(t, "pca", "pc-rapids")["fidelity"] == pytest.approx(1.0, abs=1e-6)
    assert 0.95 < row["stage_stability"] < 1.0 and row["stage_reproducibility"] == pytest.approx(1.0)


def test_knn_fidelity_is_recall(t):
    assert 0.95 < _stage(t, "knn", "nn-scanpy")["fidelity"] < 0.99      # 3% of neighbours replaced
    assert _stage(t, "knn", "nn-rapids")["fidelity"] == pytest.approx(1.0)


def test_stage_tabs_vary_only_their_own_seed(t):
    # deterministic modules have no seed to vary: no stability, not Leiden's borrowed
    for stage, module in (("pca", "pc-baseline"), ("pca", "pc-rapids"), ("knn", "nn-baseline")):
        assert np.isnan(_stage(t, stage, module)["downstream_stability"])
    assert np.isfinite(_stage(t, "pca", "pc-randomized")["downstream_stability"])
    assert (t["stages"].query("stage != 'cluster'")["resolution_rule"] == "baseline oracle").all()


def test_clustering_stage(t):
    base, gpu = _stage(t, "cluster", "cl-baseline"), _stage(t, "cluster", "cl-rapids")
    assert base["resolution"] == gpu["resolution"] == 1.0
    assert gpu["accuracy_ari"] < base["accuracy_ari"] - 0.05
    assert base["stage_reproducibility"] == pytest.approx(1.0) and gpu["stage_reproducibility"] < 0.95
    assert base["cost_s"] == 2 and gpu["cost_s"] == 0.5


def test_named_pipelines_matched_seeds_and_cost(t):
    assert set(t["pipes"]["pipeline"]) == {"baseline", "tuned-cpu", "all-gpu", "hybrid"}
    tuned = _pipe(t, "tuned-cpu")
    assert tuned["runs"] == 2 * 4  # 4 matched seeds x 2 folders, not every seed combination
    assert _pipe(t, "baseline")["cost_s"] == pytest.approx(10 + 8 + 3 * 2)  # PCA + kNN + 3 Leiden
    assert _pipe(t, "hybrid")["cost_s"] == pytest.approx(1 + 0.5 + 3 * 2)
    assert _pipe(t, "all-gpu")["log10_cost_vs_fastest"] == 0
    assert _pipe(t, "all-gpu")["reproducibility"] < 0.95 and _pipe(t, "hybrid")["reproducibility"] == pytest.approx(1.0)
    assert len(t["pipe_runs"]) == t["pipes"]["runs"].sum()


def test_cold_start_is_first_rapids_job_per_folder():
    rt = pd.DataFrame({"dir": ["/x/out/data/a/1", "/x/out/data/a/2", "/x/out-rep1/data/a/3", "/x/out/data/a/4"],
                       "module": ["cl-rapids", "cl-rapids", "cl-rapids", "cl-baseline"],
                       "t0_ms": [200.0, 100.0, 300.0, 50.0]})
    assert phase2.cold_starts(rt) == {"/x/out/data/a/2", "/x/out-rep1/data/a/3"}


def test_concordance_compares_implementations_at_equal_swept_settings_only():
    """Resolutions must match (a swept setting); flavor-like settings may differ (they define
    the implementation), as in Phase 1 where cl-baseline and cl-scanpy differ in flavor."""
    import significance as sg
    from load import Node
    rng = np.random.default_rng(0)
    up = (Node("data", "d", ()), Node("input", "i", ()), Node("pca", "p", ()), Node("knn", "k", ()))
    runs = []
    for mod, extra in (("cl-a", (("flavor", "x"),)), ("cl-b", (("flavor", "y"),))):
        for res in (0.5, 1.0):
            for seed in range(3):
                node = Node("cluster", mod, tuple(sorted(extra + (("random_seed", seed), ("resolution", res)))))
                runs.append((up + (node,), rng.integers(0, 4, 200)))
    t = sg.stage_tests(runs, n_perm=99)
    assert len(t) == 2
    assert set(zip(t["A"], t["B"])) == {("cl-a resolution=0.5", "cl-b resolution=0.5"),
                                         ("cl-a resolution=1.0", "cl-b resolution=1.0")}


def test_pca_fidelity_weights_misses_by_variance():
    import concordance as cc
    rng = np.random.default_rng(0)
    v, _ = np.linalg.qr(rng.normal(size=(200, 10)))
    lam = np.array([50, 20, 10, 5, 4, 3, 2, 1, 0.5, 0.1])
    other = np.linalg.qr(np.c_[v, rng.normal(size=200)])[0][:, -1]
    for i in (0, 9):  # miss PC1 (half the variance) or PC10 (almost none)
        w = v.copy()
        w[:, i] = other
        assert cc.pca_fidelity(v, lam, w) == pytest.approx(1 - lam[i] / lam.sum())
    r = v.copy()
    c, s = np.cos(0.7), np.sin(0.7)
    r[:, [3, 4]] = v[:, [3, 4]] @ np.array([[c, -s], [s, c]])
    r[:, 2] *= -1  # a rotation inside the subspace and a sign flip cost nothing
    assert cc.pca_fidelity(v, lam, r) == pytest.approx(1.0)
    assert cc.pca_agreement(v, lam, r, lam) == pytest.approx(1.0)


def test_stage_concordance_on_the_stages_own_measure(t):
    k = phase2.knn_concordance(t["knn"], n_perm=99)
    row = k[(k["A"] == "nn-baseline") & (k["B"] == "nn-scanpy") & (k["dataset"] == "dsA") & (k["subsample"] == "in-small")].iloc[0]
    # approximate kNN agrees with the exact graph more than its seeds agree with each other
    assert row["gap B"] < 0 and np.isnan(row["within A median"]) and np.isnan(row["p B"])
    p = phase2.pca_concordance(t["pca"], n_perm=99)
    row = p[(p["A"] == "pc-baseline") & (p["B"] == "pc-rapids")].iloc[0]
    assert row["between median"] == pytest.approx(1.0, abs=1e-6)
