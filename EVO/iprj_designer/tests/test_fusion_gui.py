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


def _fused_layer(svg: str) -> str:
    """The fused markers alone: the fused view (2026-07-14 round) prepends the
    raw points as a 20 %-opacity underlay group — strip it before counting."""
    assert svg.startswith('<g opacity="0.2">')
    return svg.split("</g>", 1)[1]


@needs_us95
def test_ensure_fusion_caches_by_recording_and_calibration(viewer):
    """ensure_fusion runs once per (recording, calibrated?) and reuses the
    cache — the render tick never re-fuses. A calibration change re-runs it.

    Since the 2026-07-14 calibrated-eval round an *uncalibrated* recording
    self-calibrates on the way in (model.replay.autocalibrate): on this
    fixture the solve trusts sensor 1, so the fused view comes back
    ``calibrated`` (tight cross-sensor gate, not low-confidence) even though
    the loaded recording itself stays uncalibrated."""
    v = viewer
    res1 = v.ensure_fusion()
    assert res1 is not None and res1.calibrated  # via the autocalibrate pre-pass
    assert not res1.low_confidence
    assert not v.replay.alignment.calib  # the raw overlay is untouched
    assert v.ensure_fusion() is res1  # cached, same object
    assert len(v._fusion_frames) == len(v.replay.frames)

    # an explicitly calibrated overlay is a different cache key -> fresh run
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
    fused = _fused_layer(v.replay_marker_svg())
    assert _n_circles(fused) >= 1
    assert _n_circles(fused) <= _n_circles(raw)
    # one marker per fused id in this frame (the dict keys are the ids)
    v.ensure_fusion()
    markers = v._fusion_frames[v.replay_frame]
    assert _n_circles(fused) + fused.count("<polygon") == len(markers)


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


# --- 2026-07-14 round: raw underlay + review labeling seams ---------------------


@needs_us95
def test_fused_view_ghosts_raw_points_underneath(viewer):
    """The fused view keeps the underlying objects visible: the raw per-sensor
    markers render first, wrapped at 20 % opacity, with the fused markers on
    top — and the underlay hides its id labels unless review is armed."""
    v = viewer
    v.fused_view = True
    svg = v.replay_marker_svg()
    assert svg.startswith('<g opacity="0.2">')
    under = svg.split("</g>", 1)[0]
    assert _n_circles(under) + under.count("<polygon") \
        == len(v.replay.frames[v.replay_frame].points)
    assert "<text" not in under  # raw ids only while reviewing
    v.review_active = True
    under = v.replay_marker_svg().split("</g>", 1)[0]
    assert "<text" in under


@needs_us95
def test_review_hit_and_selection_rings(viewer):
    """A click on a marker's canvas position resolves to its raw (sensor, oid);
    the selection ring renders cyan at full opacity, and a committed group's
    members switch to the dashed labeled ring."""
    v = viewer
    v.review_active = True
    pt = v.replay.frames[v.replay_frame].points[0]
    cx, cy = v.replay_point_to_canvas(pt.x_ft, pt.y_ft)
    assert v.review_hit((cx + 1, cy + 1)) == (pt.sensor, pt.oid)
    assert v.review_hit((cx + 10_000, cy)) is None

    assert v.review.toggle((pt.sensor, pt.oid))
    svg = v.replay_marker_svg()
    assert 'stroke="#00e5ff"' in svg  # selected ring
    # commit -> the ring turns into the dashed "already labeled" marker
    v.review.toggle((pt.sensor, pt.oid + 10))  # a second member for the pair
    v.review.commit("persistence")
    svg = v.replay_marker_svg()
    assert 'stroke="#4caf50"' in svg
    # rings render at full opacity even in the fused view (on top of the
    # 20 % underlay, before the fused markers)
    v.fused_view = True
    assert 'stroke="#4caf50"' in v.replay_marker_svg()
    v.review_active = False
    assert 'stroke="#4caf50"' not in v.replay_marker_svg()


# --- Item 47: traceable labels, bad_pair fused-marker click, gap-fill layer ------


@needs_us95
def test_fused_marker_labels_are_traceable_codes(viewer):
    """The fused label is the members' traceable code (fused_label), not the
    raw integer fused_id — a multi-member track shows a hyphenated 2-digit
    label, and it is what renders on the marker."""
    v = viewer
    v.fused_view = True
    v.replay_labels = True
    v.ensure_fusion()
    multi = next(t for t in v._fusion.tracks if len(t.members) >= 2)
    label = v._fusion_labels[multi.fused_id]
    assert "-" in label  # >= 2 members joined
    v.replay_frame = next(i for i, m in enumerate(v._fusion_frames)
                          if multi.fused_id in m)
    assert f">{label}<" in v.replay_marker_svg()


@needs_us95
def test_fused_hit_returns_the_marker_member_set(viewer):
    """A click on a fused marker resolves to that FusedTrack's members (the
    bad_pair authoring seam); a click far from any marker resolves to None."""
    v = viewer
    v.fused_view = True
    v.ensure_fusion()
    markers = v._fusion_frames[v.replay_frame]
    fid, (fx, fy) = next(iter(markers.items()))
    cx, cy = v.replay_point_to_canvas(fx, fy)
    expected = next(t.members for t in v._fusion.tracks if t.fused_id == fid)
    assert v.fused_hit((cx + 1, cy + 1)) == expected
    assert v.fused_hit((cx + 10_000, cy)) is None


@needs_us95
def test_synthetic_gap_fill_layer_is_populated_and_styled(viewer):
    """ensure_fusion builds a per-frame synthetic layer aligned to the frames;
    a synthetic marker renders as a hollow dashed ring with no label so it
    reads as interpolated, not observed."""
    v = viewer
    v.fused_view = True
    v.ensure_fusion()
    assert len(v._fusion_synth_frames) == len(v.replay.frames)
    svg = v._synth_marker_svg({7: (0.0, 0.0)})
    assert 'fill="none"' in svg and "stroke-dasharray" in svg
    assert "<text" not in svg  # interpolated points carry no id label
    # if the fixture has a real drop gap, its fill renders in the fused view
    gap_frames = [i for i, m in enumerate(v._fusion_synth_frames) if m]
    if gap_frames:
        v.replay_frame = gap_frames[0]
        assert 'fill="none"' in v.replay_marker_svg()
