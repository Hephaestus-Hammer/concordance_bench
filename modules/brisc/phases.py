"""Phase boundary helper around obkit.logger, the wire format of the scanpy fork's and the
rapids-singlecell module's src/phases.py (obkit 0.0.3 has emit and init_logger, not phase).

    init_logger(output_dir)
    with phase("load") as attrs:
        ...
        attrs["n_cells"] = n
"""

from contextlib import contextmanager

from obkit.logger import emit, init_logger  # noqa: F401  (re-exported for the stage scripts)


@contextmanager
def phase(name):
    attrs = {}
    emit(name, "start")
    try:
        yield attrs
    finally:
        emit(name, "end", attrs=attrs or None)
