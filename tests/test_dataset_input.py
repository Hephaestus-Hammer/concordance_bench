"""modules/dataset_input.py: nesting, label proportions, labels dropped, layout."""

import subprocess
import sys
from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))
from dataset_input import prepare, stratified_order  # noqa: E402


def _dataset(n=2000, g=300, seed=0):
    rng = np.random.default_rng(seed)
    labels = rng.choice(["T", "B", "NK", "Mono", "DC"], size=n, p=[0.5, 0.2, 0.15, 0.1, 0.05]).astype(object)
    labels[:7] = None            # unlabelled cells are dropped
    labels[7:10] = ""
    X = sp.random(n, g, density=0.1, random_state=seed, format="csr", data_rvs=lambda k: rng.poisson(3, k) + 1)
    a = ad.AnnData(X=X.astype(np.float32), obs=pd.DataFrame({"cell_type": labels}, index=[f"c{i}" for i in range(n)]))
    a.var_names = [f"g{i}" for i in range(g)]
    return a


def test_prefixes_keep_label_proportions():
    labels = np.random.default_rng(1).choice(list("abcde"), size=5000, p=[.5, .2, .15, .1, .05])
    order = stratified_order(labels, seed=0)
    total = pd.Series(labels).value_counts()
    for n in (50, 333, 1000, 4999):
        got = pd.Series(labels[order[:n]]).value_counts().reindex(total.index, fill_value=0)
        assert (abs(got - total * n / len(labels)) <= 1.0 + 1e-9).all(), n


def test_subsamples_are_nested_and_drop_unlabelled():
    a = _dataset()
    sizes = (200, 500, 1000)
    cells = [set(prepare(a, "cell_type", n)[2]) for n in sizes]
    assert cells[0] <= cells[1] <= cells[2]
    assert all(len(c) == n for c, n in zip(cells, sizes))
    everyone = set(prepare(a, "cell_type", 0)[2])
    assert len(everyone) == a.n_obs - 10 and not ({f"c{i}" for i in range(10)} & everyone)


def test_same_genes_at_every_size_with_hvg():
    pytest.importorskip("scanpy")
    a = _dataset()
    g_small = prepare(a, "cell_type", 300, normalize="log1p_cp10k", n_hvg=50)[1]
    g_big = prepare(a, "cell_type", 1500, normalize="log1p_cp10k", n_hvg=50)[1]
    # HVGs are chosen on the whole dataset; only genes empty in a subsample may drop out
    assert set(g_small) <= set(g_big) and len(g_big) == 50


def test_too_many_cells_is_an_error():
    with pytest.raises(SystemExit, match="exclude this dataset"):
        prepare(_dataset(n=300), "cell_type", 1000)


def test_cli_writes_the_omni_layout(tmp_path):
    a = _dataset()
    a.write_h5ad(tmp_path / "d.h5ad")
    subprocess.run([sys.executable, ROOT / "modules" / "dataset_input.py", "--output_dir", tmp_path / "o",
                    "--name", "t", "--data_h5ad", tmp_path / "d.h5ad", "--label_key", "cell_type",
                    "--n_cells", "400"], check=True)
    with h5py.File(tmp_path / "o" / "t_normalized_selected.h5") as h5:
        g, c = h5["matrix/shape"][:]
        assert c == 400 and len(h5["matrix/barcodes"]) == 400 and len(h5["matrix/genes"]) == g
    truth = pd.read_csv(tmp_path / "o" / "t.clusters_truth.tsv", sep="\t")
    assert list(truth.columns) == ["cell_id", "truths"] and len(truth) == 400


def test_publish_then_input_round_trip(tmp_path):
    """publish_dataset.py's output is what dataset_input.py reads with the plan's defaults."""
    pytest.importorskip("scanpy")
    _dataset().write_h5ad(tmp_path / "raw.h5ad")
    subprocess.run([sys.executable, ROOT / "scripts" / "publish_dataset.py", tmp_path / "raw.h5ad",
                    tmp_path / "pub.h5ad", "--label_key", "cell_type", "--n_hvg", "100"], check=True)
    pub = ad.read_h5ad(tmp_path / "pub.h5ad")
    assert pub.n_vars <= 100 and "label" in pub.obs and pub.n_obs == 1990
    subprocess.run([sys.executable, ROOT / "modules" / "dataset_input.py", "--output_dir", tmp_path / "o",
                    "--name", "t", "--data_h5ad", tmp_path / "pub.h5ad", "--n_cells", "500"], check=True)
    assert len(pd.read_csv(tmp_path / "o" / "t.clusters_truth.tsv", sep="\t")) == 500
