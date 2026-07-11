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
def test_ghost_sensors_track_the_group_move(viewer):
    """The 2026-07-11 reframing: ghost sensor copies sit exactly on the real
    sensors at the automatic fit and translate with a group drag — the visible
    'how much have the sensors moved' the owner asked for."""
    v = viewer
    base = build_alignment(v.project, v.replay.zones, None)
    v.align_base = base
    v.align_placement = base.placement
    fpp = v.ft_per_px()

    ghosts = v.align_ghosts()
    assert {si for si, *_ in ghosts} == {0, 1}  # both mapped sensors
    for _si, real, ghost, daz in ghosts:
        assert ghost == pytest.approx(real, abs=1e-6)  # nothing authored yet
        assert daz == pytest.approx(0.0, abs=1e-9)
    assert not v.align_dirty()

    v.align_placement = translated(base.placement, 20.0, -8.0)
    for _si, real, ghost, daz in v.align_ghosts():
        moved = ((ghost[0] - real[0]) * fpp, (ghost[1] - real[1]) * fpp)
        assert moved == pytest.approx((20.0, -8.0), abs=1e-6)
        assert daz == pytest.approx(0.0, abs=1e-6)
    assert v.align_dirty()

    svg = v.align_marker_svg()
    assert "S1&#8242;" in svg and "S2&#8242;" in svg  # ghost labels rendered
    assert "<line" in svg  # displacement leader from real sensor to ghost


@needs_us95
def test_rotate_preview_swings_the_overlay_before_commit(viewer):
    """The Align 2-click rotate previews live (2026-07-11 fix): while aiming,
    align_render_alignment() applies rotated_about to the placement so markers
    and ghosts swing with the cursor before the second click commits."""
    v = viewer
    base = build_alignment(v.project, v.replay.zones, None)
    v.align_base = base
    v.align_placement = base.placement
    before = v.align_marker_svg()

    v.align_rotate_armed = True
    v.rotate_pivot = (900.0, 900.0)  # world px, as the click handler stores it
    v.rotate_angle = 10.0
    preview = v.align_marker_svg()
    assert preview != before

    fpp = v.ft_per_px()
    expected = rotated_about(base.placement, (900.0 * fpp, 900.0 * fpp), 10.0)
    got = v.align_render_alignment().placement
    assert (got.a_re, got.a_im, got.t_x, got.t_y) == pytest.approx(
        (expected.a_re, expected.a_im, expected.t_x, expected.t_y))
    # the authored placement itself is untouched until the commit click
    assert v.align_placement == base.placement


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


def test_marker_source_routing():
    """marker_source() (Item 40, owner fix 2026-07-11): the Overlay sub-modes
    keep their own painter, Record stays blank, and every non-overlay mode
    persists a running overlay source — live winning over a loaded recording —
    instead of clearing. This is the headless check for the relaxed
    read-only-canvas invariant refresh_marker_layer dispatches on."""
    from gui.app import marker_source

    # overlay sub-modes: painter follows the mode, sources irrelevant
    assert marker_source("Replay", False, False) == "replay"
    assert marker_source("Live", False, False) == "live"
    assert marker_source("Align", True, True) == "align"
    assert marker_source("Record", True, True) == ""

    # non-overlay modes: whatever source is running persists
    for mode in ("Draw", "Edit", "Sensor", "Centerline", "Background"):
        assert marker_source(mode, False, False) == ""
        assert marker_source(mode, True, False) == "replay"
        assert marker_source(mode, False, True) == "live"
        assert marker_source(mode, True, True) == "live"  # live wins
