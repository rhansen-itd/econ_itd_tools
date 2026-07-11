"""Fusion overlay wiring — Viewer render seam (ROADMAP Item 43).

The transport/toggle closures live inside ``build_ui`` and are exercised by
hand; what is headless-testable is the seam they drive: ``Viewer.ensure_fusion``
caching the Item 42 result and ``replay_marker_svg`` switching between the raw
per-sensor points and the fused (one-marker-per-vehicle) view. These tests
confirm the fused render reads the engine and dedups on screen, and that the
cache keys on the recording + calibration state (never re-fusing per tick).
"""

from pathlib import Path

import pytest

from gui.app import Viewer
from model.calibration import build_alignment, calibrate
from model.iprj_io import load_iprj
from model.replay import load_recording, realign

FIXTURES = Path(__file__).resolve().parent / "fixtures"
US95_REC = FIXTURES / "10_37_2_86_EVO_1770311735.txt"
US95_IPRJ = FIXTURES / "us95&sh8.iprj"

needs_us95 = pytest.mark.skipif(
    not US95_REC.is_file() or not US95_IPRJ.is_file(),
    reason="US95 fixtures not present")


@pytest.fixture
def viewer():
    proj = load_iprj(US95_IPRJ)
    v = Viewer(proj, US95_IPRJ)
    v.replay = load_recording(proj, US95_REC, max_frames=None)
    # park on a frame where two sensors both report — the cross-sensor case
    v.replay_frame = next(
        i for i, f in enumerate(v.replay.frames)
        if {p.sensor for p in f.points} >= {0, 1})
    return v


def _n_circles(svg: str) -> int:
    return svg.count("<circle")


@needs_us95
def test_ensure_fusion_caches_by_recording_and_calibration(viewer):
    """ensure_fusion runs once per (recording, calibrated?) and reuses the
    cache — the render tick never re-fuses. A calibration change re-runs it."""
    v = viewer
    res1 = v.ensure_fusion()
    assert res1 is not None and not res1.calibrated
    assert v.ensure_fusion() is res1  # cached, same object
    assert len(v._fusion_frames) == len(v.replay.frames)

    # a calibrated overlay is a different cache key -> a fresh, calibrated solve
    cal = calibrate(v.replay.frames)
    v.replay = realign(v.replay, build_alignment(v.project, v.replay.zones, cal))
    res2 = v.ensure_fusion()
    assert res2 is not res1
    assert res2.calibrated


@needs_us95
def test_fused_view_dedups_on_screen(viewer):
    """On a two-sensor frame the fused view shows no more markers than the raw
    view (cross-sensor coincidences collapse to one marker/vehicle), and the
    fused ids are unique per frame."""
    v = viewer
    v.fused_view = False
    raw = v.replay_marker_svg()
    v.fused_view = True
    fused = v.replay_marker_svg()
    assert _n_circles(fused) >= 1
    assert _n_circles(fused) <= _n_circles(raw)
    # one marker per fused id in this frame (the dict keys are the ids)
    v.ensure_fusion()
    markers = v._fusion_frames[v.replay_frame]
    assert _n_circles(fused) == len(markers)


@needs_us95
def test_fused_labels_toggle(viewer):
    """The id-label switch drives fused markers too (shared glyph helper)."""
    v = viewer
    v.fused_view = True
    v.replay_labels = True
    assert "<text" in v.replay_marker_svg()
    v.replay_labels = False
    assert "<text" not in v.replay_marker_svg()


@needs_us95
def test_empty_when_no_recording():
    proj = load_iprj(US95_IPRJ)
    v = Viewer(proj, US95_IPRJ)
    v.fused_view = True
    assert v.ensure_fusion() is None
    assert v.replay_marker_svg() == ""
