"""modules/brisc/brisc_io.py: the conversions that do not need brisc itself."""

import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "modules" / "brisc"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "modules"))
import brisc_io as io  # noqa: E402


def test_neighbors_from_distances_nearest_first_uint32():
    d = sp.csr_matrix(np.array([[0, 3.0, 1.0, 2.0], [1.0, 0, 5.0, 2.0], [4.0, 1.0, 0, 3.0], [1.0, 2.0, 3.0, 0]]))
    nb = io.neighbors_from_distances(d)
    assert nb.dtype == np.uint32 and nb.flags["C_CONTIGUOUS"]
    assert nb.tolist() == [[2, 3, 1], [0, 3, 2], [1, 3, 0], [0, 1, 2]]


def test_neighbors_from_distances_pads_short_rows():
    """Row 1 lost a neighbour (a duplicate cell, distance 0, not stored); row 2 has none."""
    d = sp.csr_matrix((np.array([1.0, 2.0, 0.5]), (np.array([0, 0, 1]), np.array([1, 2, 0]))), shape=(3, 3))
    nb = io.neighbors_from_distances(d)
    assert nb.tolist() == [[1, 2], [0, 0], [2, 2]]


def test_neighbors_round_trip(tmp_path):
    cells = np.array(["a", "b", "c"])
    d = sp.csr_matrix(np.array([[0, 1.0, 2.0], [1.5, 0, 0.5], [2.0, 0.5, 0]]))
    c = sp.csr_matrix(np.array([[1, 0.3, 0], [0.3, 1, 0.2], [0, 0.2, 1.0]]))
    io.write_neighbors(tmp_path / "x.h5", cells, d, c)
    got_cells, got_d, got_c = io.read_neighbors(tmp_path / "x.h5")
    assert got_cells.tolist() == cells.tolist()
    assert (got_d != d).nnz == 0 and (got_c != c).nnz == 0


def test_read_matrix_omni_float32(tmp_path):
    from matrix_formats import write_matrix
    X = sp.random(30, 8, density=0.3, random_state=0, format="csr")
    write_matrix(X, [f"g{i}" for i in range(8)], [f"c{i}" for i in range(30)], tmp_path / "m.h5", "omni")
    Y, genes, cells = io.read_matrix(tmp_path / "m.h5")
    assert Y.dtype == np.float32 and Y.shape == (30, 8)
    assert np.allclose(Y.toarray(), X.toarray(), atol=1e-6)
    assert genes[0] == "g0" and cells[-1] == "c29"
