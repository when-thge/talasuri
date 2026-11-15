"""Live end-to-end checks against IRSA (slow: minutes per target on a cold cache).

Run with:  pytest -m network tests/test_acceptance.py
For each target: the query returns frames, cutouts align to < 1 px (RMS of bright-star
centroids, single frames vs per-detector stacks), and a spectrum is produced.
"""
import asyncio

import pytest

from spherex_viewer.api import sessions as sessions_mod
from spherex_viewer.checks import TARGETS, check_target

pytestmark = pytest.mark.network


@pytest.mark.parametrize("name", list(TARGETS))
def test_target(name):
    sessions_mod._fetchers = None
    cfg = TARGETS[name]
    res, session = asyncio.run(check_target(name, cfg["q"], cfg["fov"]))
    assert res["n_observations"] > 0, res["message"]
    assert res["n_loaded"] >= 0.9 * res["n_observations"], res["message"]
    assert res["alignment"]["n"] >= 20, "too few reference-star measurements"
    assert res["alignment"]["rms_px"] < 1.0, res["alignment"]
    # "A spectrum is produced". Saturated targets (Barnard's Star, R Dra) legitimately
    # have no unflagged points; see docs/TESTING.md.
    assert res["spectrum"]["n_measured"] > 0
    lo, hi = res["spectrum"]["lam_range_um"]
    assert lo < 1.0 and hi > 4.5, "spectrum should span the SPHEREx band"
