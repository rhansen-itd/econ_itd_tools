"""Interactive alignment mode — Viewer wiring (ROADMAP Item 40).

The GUI action closures (Auto-calibrate, group drag/rotate, commit) live inside
``build_ui`` and are exercised by hand; what is headless-testable is the seam
they all drive: the ``Viewer`` methods that compose the authored transform and
render the overlay through it. These tests confirm the composition matches the
model layer exactly and that a group edit re-seats the markers — the marker-
layer-only re-render the drag ticks depend on (plan §6).
"""

import math
from pathlib import Path

import pytest

from gui.app import Viewer
from model.calibration import (AlignmentTransform, RigidDelta, build_alignment,
                               calibrate, rotated_about, translated)
from model.iprj_io import load_iprj
from model.replay import load_recording

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
    rec = load_recording(proj, US95_REC, max_frames=None)
    v.replay = rec
    v.replay_frame = next(
        i for i, f in enumerate(rec.frames) if {p.sensor for p in f.points} >= {0, 1})
    return v


@needs_us95
def test_current_alignment_composes_calib_and_placement(viewer):
    """current_alignment() rebuilds the exact AlignmentTransform the model
    layer would, and align_source_frame() returns the live replay frame."""
    v = viewer
    cal = calibrate(v.replay.frames)
    tr = build_alignment(v.project, v.replay.zones, cal)
    v.align_placement = tr.placement
    v.align_calib = dict(tr.calib)
    v.align_calibration = cal

    frame = v.align_source_frame()
    assert frame is v.replay.frames[v.replay_frame]

    got = v.current_alignment()
    for p in frame.points:
        assert got.apply(p.sensor, p.x_raw_m, p.y_raw_m) == pytest.approx(
            tr.apply(p.sensor, p.x_raw_m, p.y_raw_m))


@needs_us95
def test_align_marker_svg_reseats_on_group_move(viewer):
    """A locked group drag/rotate re-renders the markers through the composed
    transform (the plan-§6 real-time re-seat) — so the SVG changes when the
    placement does, and is empty when nothing is authored yet."""
    v = viewer
    assert v.align_marker_svg() == ""  # no placement seeded yet

    tr = build_alignment(v.project, v.replay.zones, None)
    v.align_placement = tr.placement
    before = v.align_marker_svg()
    assert "<circle" in before

    v.align_placement = translated(
        rotated_about(v.align_placement, (900.0, 900.0), 5.0), 40.0, -25.0)
    after = v.align_marker_svg()
    assert "<circle" in after
    assert after != before  # the group move visibly re-seated the markers


@needs_us95
def test_align_uses_raw_meters_not_precomputed_feet(viewer):
    """Align markers re-align from each point's raw EVO meters through the
    live transform, *not* the frame's precomputed x_ft/y_ft — that is what lets
    a drag move them without re-aligning the whole recording."""
    v = viewer
    delta = RigidDelta.make(0.0, (5.0, -3.0))  # shift sensor 1 by a known map
    tr = build_alignment(v.project, v.replay.zones, None)
    v.align_placement = tr.placement
    v.align_calib = {1: delta}

    frame = v.align_source_frame()
    align = v.current_alignment()
    p = next(pt for pt in frame.points if pt.sensor == 1)
    # the rendered feet come from apply(sensor, raw_m), which differs from the
    # frame's stored x_ft (that was the un-calibrated zone fit)
    fx, fy = align.apply(p.sensor, p.x_raw_m, p.y_raw_m)
    assert (fx, fy) != pytest.approx((p.x_ft, p.y_ft))
    assert (fx, fy) == pytest.approx(tr.placement.apply_m(*delta.apply_m(p.x_raw_m, p.y_raw_m)))


@needs_us95
def test_live_source_precedence_and_staleness(viewer):
    """align_source_frame prefers a fresh live slot over the recording, and
    treats a stale live slot as absent (the LIVE_STALE_TIMEOUT rule)."""
    import time as _time

    from gui.app import LIVE_STALE_TIMEOUT

    v = viewer
    frame = v.replay.frames[v.replay_frame]
    # no live session -> the replay frame
    assert v.align_source_frame() is frame
    # a running live session with a fresh slot -> the live frame
    v.live_session = object()  # truthy sentinel; align_source_frame only checks presence
    live_frame = v.replay.frames[0]
    v.live_frame = (live_frame, _time.monotonic())
    assert v.align_source_frame() is live_frame
    # a stale slot -> None (overlay clears rather than freezing)
    v.live_frame = (live_frame, _time.monotonic() - LIVE_STALE_TIMEOUT - 1.0)
    assert v.align_source_frame() is None
