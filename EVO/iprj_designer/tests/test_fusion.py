"""Fusion engine tests (ROADMAP Item 42, FUSION_PLAN.md §6).

Two gates, per the plan: deterministic synthetic cases pin every bridge/fuse
rule and — above all — the refuse-don't-guess adversarial behavior (two
distinct vehicles must never merge); the hand-labeled acceptance set on the
real ``86_US95&SH8`` recording (tests/fixtures/fusion_labels_86_us95_sh8.json,
verified by trajectory inspection) gates the whole engine on real radar
data, calibrated and uncalibrated.
"""

import json
import math
from pathlib import Path

import pytest

from model.calibration import build_alignment, calibrate
from model.fusion import (
    DEFAULT_PARAMS,
    FusionParams,
    fold_tracks,
    frame_times_s,
    fuse,
    fused_frame_markers,
    parse_time_s,
)
from model.iprj_io import load_iprj
from model.replay import Frame, TrackPoint, load_recording, realign

FIXTURES = Path(__file__).resolve().parent / "fixtures"
US95_REC = FIXTURES / "10_37_2_86_EVO_1770311735.txt"
US95_IPRJ = FIXTURES / "us95&sh8.iprj"
US95_LABELS = FIXTURES / "fusion_labels_86_us95_sh8.json"

needs_us95 = pytest.mark.skipif(
    not (US95_REC.exists() and US95_IPRJ.exists()),
    reason="US95 fixtures not present")


# --- synthetic frame builder --------------------------------------------------


def _t(s: float) -> str:
    """Seconds-past-9am -> the recorder's HH:MM:SS.mmm stamp."""
    total = 9 * 3600 + s
    h, rem = divmod(total, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{sec:06.3f}"


def _pt(oid: int, x: float, y: float, cls: int = 30) -> TrackPoint:
    return TrackPoint(oid=oid, sensor=oid % 10, cls=cls, x_ft=x, y_ft=y,
                      heading=None, x_raw_m=0.0, y_raw_m=0.0)


def _frames(*tracks, dt: float = 0.1) -> list[Frame]:
    """Build a frame stream from track specs.

    Each spec is ``(oid, cls, t_start_s, (x0, y0), (vx, vy), n)``: *n* samples
    every *dt* seconds from the start point at constant velocity. Specs merge
    onto one timeline; points sharing a rounded time share a Frame.
    """
    by_time: dict[int, list[TrackPoint]] = {}
    for oid, cls, t0, (x0, y0), (vx, vy), n in tracks:
        for i in range(n):
            key = round((t0 + i * dt) / dt)
            by_time.setdefault(key, []).append(
                _pt(oid, x0 + vx * i * dt, y0 + vy * i * dt, cls))
    return [Frame(t=_t(k * dt), points=tuple(pts))
            for k, pts in sorted(by_time.items())]


# --- time seam & fold ----------------------------------------------------------


def test_parse_time_s():
    assert parse_time_s("09:15:35.078") == pytest.approx(33335.078)
    assert parse_time_s("00:00:00.000") == 0.0
    with pytest.raises(ValueError):
        parse_time_s("not a time")


def test_fold_groups_by_sensor_and_oid_in_time_order():
    frames = _frames(
        (10, 30, 0.0, (0, 0), (10, 0), 5),
        (21, 30, 0.2, (50, 50), (0, 10), 5),
    )
    tracks = fold_tracks(frames)
    assert [t.key for t in tracks] == [(0, 10), (1, 21)]
    a = tracks[0]
    assert a.cls == 30
    assert [p[0] for p in a.points] == sorted(p[0] for p in a.points)
    assert a.points[0][1:] == (0.0, 0.0)
    assert a.points[-1][1] == pytest.approx(4.0)


def test_fold_unwraps_midnight():
    frames = [
        Frame(t="23:59:59.900", points=(_pt(10, 0, 0),)),
        Frame(t="00:00:00.100", points=(_pt(10, 1, 0),)),
    ]
    (track,) = fold_tracks(frames)
    assert track.points[1][0] - track.points[0][0] == pytest.approx(0.2)


def test_fold_skips_unparseable_stamp():
    frames = [
        Frame(t="09:00:00.000", points=(_pt(10, 0, 0),)),
        Frame(t="garbage", points=(_pt(10, 99, 99),)),
        Frame(t="09:00:00.100", points=(_pt(10, 1, 0),)),
    ]
    (track,) = fold_tracks(frames)
    assert len(track.points) == 2


def test_empty_stream_yields_empty_result():
    res = fuse([], calibrated=True)
    assert res.tracks == ()
    assert dict(res.id_of) == {}
    assert not res.low_confidence


# --- §3 within-sensor stitching -------------------------------------------------


def test_stop_drop_resume_stitches():
    """The headline case: a vehicle brakes to a stop, drops for 12 s, resumes
    from (nearly) the same spot -> one stitched track."""
    frames = _frames(
        # decelerating to a stop at x=100 (last second is nearly stationary)
        (10, 30, 0.0, (80.0, 0), (20, 0), 11),   # 80 -> 100 over 1 s... fast
        (10, 30, 1.1, (100.0, 0), (0.5, 0), 20),  # crawling: ends ~stopped
        (20, 30, 15.0, (103.0, 0), (15, 0), 20),  # resumes 12 s later, 3 ft on
    )
    res = fuse(frames, calibrated=True)
    (track,) = [t for t in res.tracks if t.kind != "single"]
    assert track.kind == "stitched"
    assert set(track.members) == {(0, 10), (0, 20)}
    assert res.id_of[(0, 10)] == res.id_of[(0, 20)]


def test_moving_gap_bridges_within_window():
    frames = _frames(
        (10, 30, 0.0, (0, 0), (30, 0), 20),    # ends x=57 at t=1.9, 30 ft/s
        (20, 30, 3.9, (117.0, 0), (30, 0), 20),  # 2 s gap, 60 ft on, same dir
    )
    res = fuse(frames, calibrated=True)
    (track,) = res.tracks
    assert track.kind == "stitched"


def test_moving_gap_beyond_time_window_stays_split():
    frames = _frames(
        (10, 30, 0.0, (0, 0), (30, 0), 20),
        (20, 30, 9.0, (90.0, 0), (30, 0), 20),  # 7.1 s gap > 5 s moving window
    )
    res = fuse(frames, calibrated=True)
    assert all(t.kind == "single" for t in res.tracks)


def test_two_vehicles_through_same_point_at_different_times_stay_split():
    """Plan §6 adversarial: crossing the same location later is not identity."""
    frames = _frames(
        (10, 30, 0.0, (0, 0), (40, 0), 20),      # through x=0..76
        (20, 30, 8.0, (40.0, 0), (40, 0), 20),   # same lane, 6.1 s later
    )
    res = fuse(frames, calibrated=True)
    assert all(t.kind == "single" for t in res.tracks)


def test_opposing_direction_resume_stays_split():
    """Plan §6 adversarial (and a real-fixture regression): the successor's
    own motion must lie in the forward cone, not just its start point."""
    frames = _frames(
        (10, 30, 0.0, (0, 0), (30, 0), 20),        # eastbound, ends x=57
        (20, 30, 2.9, (87.0, 0), (-30, 0), 20),    # ahead of A but WESTbound
    )
    res = fuse(frames, calibrated=True)
    assert all(t.kind == "single" for t in res.tracks)


def test_ambiguous_successors_refuse_to_bridge():
    """Two comparably-plausible successors -> leave the track split (§3)."""
    frames = _frames(
        (10, 30, 0.0, (0, 0), (30, 0), 20),
        (20, 30, 2.9, (87.0, 0), (30, 0), 20),   # both: 1 s gap, 30 ft on,
        (30, 30, 2.9, (87.0, 5), (30, 0), 20),   # near-identical scores
    )
    res = fuse(frames, calibrated=True)
    assert all(t.kind == "single" for t in res.tracks)


def test_pedestrian_never_bridges_to_vehicle():
    """Class gate (§3): a ped fragment on a car's path stays separate."""
    frames = _frames(
        (10, 10, 0.0, (0, 0), (5, 0), 20),       # pedestrian, ends x=9.5
        (20, 30, 2.9, (12.0, 0), (5, 0), 20),    # "car" resuming just ahead
    )
    res = fuse(frames, calibrated=True)
    assert all(t.kind == "single" for t in res.tracks)


def test_chain_stitches_transitively():
    """A->B->C forms via re-runs, each step individually gated (§3)."""
    frames = _frames(
        (10, 30, 0.0, (0, 0), (30, 0), 20),
        (20, 30, 3.9, (117.0, 0), (30, 0), 20),
        (30, 30, 7.8, (234.0, 0), (30, 0), 20),
    )
    res = fuse(frames, calibrated=True)
    (track,) = res.tracks
    assert track.members == ((0, 10), (0, 20), (0, 30))
    ts = [p.t_s for p in track.points]
    assert ts == sorted(ts)


# --- §4 cross-sensor fusion ------------------------------------------------------


def _handoff_frames(sep_ft: float = 2.0):
    """One vehicle eastbound: sensor 0 sees t=0..5, sensor 1 t=3..8 riding
    *sep_ft* north of the sensor-0 report (the inter-sensor disagreement)."""
    return _frames(
        (10, 30, 0.0, (0.0, 0.0), (30, 0), 51),
        (21, 30, 3.0, (90.0, sep_ft), (30, 0), 51),
    )


def test_cross_sensor_handoff_fuses_and_dedups():
    res = fuse(_handoff_frames(), calibrated=True)
    (track,) = res.tracks
    assert track.kind == "fused"
    assert set(track.members) == {(0, 10), (1, 21)}
    assert not res.low_confidence
    # continuous, time-ordered, deduped: blended points carry both sources
    ts = [p.t_s for p in track.points]
    assert ts == sorted(ts)
    blended = [p for p in track.points if len(p.src) > 1]
    assert len(blended) >= DEFAULT_PARAMS.min_overlap_samples
    # the fused polyline hands off smoothly: x strictly increases throughout
    xs = [p.x_ft for p in track.points]
    assert all(b > a for a, b in zip(xs, xs[1:]))
    # and covers the whole life, entry (S0 only) to exit (S1 only)
    assert track.points[0].src == ((0, 10),)
    assert track.points[-1].src == ((1, 21),)


def test_parallel_vehicles_in_adjacent_lanes_stay_separate():
    """Plan §6 adversarial: sustained 25 ft separation is two vehicles, not
    one — beyond d_fine when calibrated."""
    frames = _frames(
        (10, 30, 0.0, (0.0, 0.0), (30, 0), 51),
        (21, 30, 0.0, (0.0, 25.0), (30, 0), 51),
    )
    res = fuse(frames, calibrated=True)
    assert all(t.kind == "single" for t in res.tracks)


def test_pedestrian_beside_car_stays_separate():
    """Plan §6 adversarial: class gate beats spatial coincidence (§4a)."""
    frames = _frames(
        (10, 30, 0.0, (0.0, 0.0), (6, 0), 51),
        (21, 15, 0.0, (0.0, 4.0), (6, 0), 51),  # bike/ped 4 ft alongside
    )
    res = fuse(frames, calibrated=True)
    assert all(t.kind == "single" for t in res.tracks)


def test_opposing_traffic_through_one_location_stays_separate():
    """Plan §6 adversarial: opposite headings meeting mid-block only coincide
    for an instant — under min_overlap-at-d_fine, so no fuse."""
    frames = _frames(
        (10, 30, 0.0, (0.0, 0.0), (30, 0), 51),
        (21, 30, 0.0, (150.0, 2.0), (-30, 0), 51),
    )
    res = fuse(frames, calibrated=True)
    assert all(t.kind == "single" for t in res.tracks)


def test_uncalibrated_widens_gate_and_flags_low_confidence():
    """§4b: a same-vehicle pair riding a 30 ft systematic offset fuses only
    through the widened uncalibrated gate, and doing so flags the result."""
    frames = _handoff_frames(sep_ft=30.0)
    strict = fuse(frames, calibrated=True)
    assert all(t.kind == "single" for t in strict.tracks)
    assert not strict.low_confidence

    loose = fuse(frames, calibrated=False)
    (track,) = loose.tracks
    assert track.kind == "fused"
    assert loose.low_confidence


def test_uncalibrated_without_cross_merges_is_not_flagged():
    frames = _frames((10, 30, 0.0, (0, 0), (30, 0), 20))
    res = fuse(frames, calibrated=False)
    assert not res.low_confidence


def test_three_source_vehicle_fuses_via_reruns():
    frames = _frames(
        (10, 30, 0.0, (0.0, 0.0), (30, 0), 51),
        (21, 30, 1.0, (30.0, 2.0), (30, 0), 51),
        (25, 0, 2.0, (60.0, -2.0), (30, 0), 51),  # secondary slot, cls 0
    )
    res = fuse(frames, calibrated=True)
    (track,) = res.tracks
    assert track.kind == "fused"
    assert set(track.members) == {(0, 10), (1, 21), (5, 25)}


def test_id_of_covers_every_raw_track():
    frames = _handoff_frames()
    res = fuse(frames, calibrated=True)
    assert set(res.id_of) == {r.key for r in fold_tracks(frames)}
    for t in res.tracks:
        for m in t.members:
            assert res.id_of[m] == t.fused_id


def test_fuse_is_deterministic():
    frames = _frames(
        (10, 30, 0.0, (0.0, 0.0), (30, 0), 51),
        (21, 30, 3.0, (90.0, 2.0), (30, 0), 51),
        (30, 30, 0.0, (0.0, 40.0), (25, 0), 40),
        (20, 30, 8.2, (200.0, 40.0), (25, 0), 40),
    )
    assert fuse(frames, calibrated=True) == fuse(frames, calibrated=True)


def test_params_are_overridable():
    """The tuning seam (§6 open item): gates live in FusionParams, not code."""
    frames = _frames(
        (10, 30, 0.0, (0, 0), (30, 0), 20),
        (20, 30, 9.0, (117.0, 0), (30, 0), 20),  # 7.1 s gap, 60 ft on
    )
    wide = FusionParams(t_max_moving_s=10.0)
    assert any(t.kind == "stitched"
               for t in fuse(frames, calibrated=True, params=wide).tracks)


# --- the real-recording acceptance gate (plan §6) --------------------------------


@pytest.fixture(scope="module")
def us95():
    proj = load_iprj(US95_IPRJ)
    rec = load_recording(proj, US95_REC, max_frames=None)
    return proj, rec


@pytest.fixture(scope="module")
def us95_fused(us95):
    """(calibrated FusionResult, uncalibrated FusionResult, labels)."""
    proj, rec = us95
    cal = calibrate(rec.frames)
    rec_cal = realign(rec, build_alignment(proj, rec.zones, cal))
    labels = json.loads(US95_LABELS.read_text())["labels"]
    return (fuse(rec_cal.frames, calibrated=True),
            fuse(rec.frames, calibrated=False), labels)


@needs_us95
def test_us95_labeled_acceptance_calibrated(us95_fused):
    """Every hand-labeled group comes out as exactly one fused track with
    exactly those members; the 'single' controls stay unmerged."""
    res, _, labels = us95_fused
    by_members = {frozenset(t.members): t for t in res.tracks}
    for lab in labels:
        members = frozenset((s, o) for s, o in lab["members"])
        track = by_members.get(members)
        assert track is not None, f"labeled group not produced: {lab}"
        assert track.kind == lab["expect"]
        assert len({res.id_of[m] for m in members}) == 1


@needs_us95
def test_us95_uncalibrated_degrades_gracefully(us95_fused):
    """§4b: without calibration fusion still runs, flags itself, and the
    stitched/single labels (calibration-independent) still hold."""
    _, res, labels = us95_fused
    assert res.low_confidence  # cross-sensor merges through the widened gate
    by_members = {frozenset(t.members): t for t in res.tracks}
    for lab in labels:
        if lab["expect"] == "fused":
            continue  # cross-sensor pairings may legitimately differ
        members = frozenset((s, o) for s, o in lab["members"])
        assert by_members.get(members) is not None, f"lost without cal: {lab}"


@needs_us95
def test_us95_calibration_tightens_labeled_overlaps(us95, us95_fused):
    """Fusion *improves* with the calibrated overlay (§6): over the labeled
    S0<->S1 fused pairs, the mean in-overlap separation shrinks once the
    Items 38-40 calibration is applied."""
    proj, rec = us95
    cal = calibrate(rec.frames)
    rec_cal = realign(rec, build_alignment(proj, rec.zones, cal))
    _, _, labels = us95_fused

    def mean_sep(frames, key_a, key_b):
        tracks = {r.key: r for r in fold_tracks(frames)}
        a, b = tracks[key_a].points, tracks[key_b].points
        bt = [q[0] for q in b]
        dists = []
        for t, x, y in a:
            j = min(range(len(bt)), key=lambda i: abs(bt[i] - t))
            if abs(bt[j] - t) <= DEFAULT_PARAMS.dt_match_s:
                dists.append(math.hypot(x - b[j][1], y - b[j][2]))
        assert dists
        return sum(dists) / len(dists)

    checked = 0
    for lab in labels:
        if lab["expect"] != "fused":
            continue
        pairs = [((s1, o1), (s2, o2))
                 for i, (s1, o1) in enumerate(lab["members"])
                 for (s2, o2) in lab["members"][i + 1:]
                 if {s1, s2} == {0, 1}]  # only the calibrated sensor pair
        for ka, kb in pairs:
            before = mean_sep(rec.frames, ka, kb)
            after = mean_sep(rec_cal.frames, ka, kb)
            assert after < before
            checked += 1
    assert checked >= 3


@needs_us95
def test_us95_no_class_divide_violations(us95, us95_fused):
    """No fused track anywhere mixes motorized and non-motorized members —
    the §3/§4 class gate holds across the whole real recording."""
    _, rec = us95
    res, _, _ = us95_fused
    cls_of = {r.key: r.cls for r in fold_tracks(rec.frames)}
    for t in res.tracks:
        cats = {("non_motor" if cls_of[m] in (10, 15, 20) else
                 "motor" if (cls_of[m] or 0) >= 25 else None)
                for m in t.members}
        assert not ({"motor", "non_motor"} <= cats), t.members


def test_result_is_frozen():
    res = fuse(_handoff_frames(), calibrated=True)
    with pytest.raises(Exception):
        res.tracks[0].points = ()  # type: ignore[misc]


# --- render-side per-frame index (Item 43) ------------------------------------


def test_frame_times_s_aligns_and_flags_bad_stamps():
    """frame_times_s is 1:1 with the frames, numeric where the stamp parses,
    nan where it doesn't — the render index tolerates a garbled frame."""
    frames = [Frame(t="09:00:01.000", points=()),
              Frame(t="not-a-time", points=()),
              Frame(t="09:00:02.500", points=())]
    ts = frame_times_s(frames)
    assert len(ts) == len(frames)
    assert ts[0] == pytest.approx(9 * 3600 + 1)
    assert math.isnan(ts[1])
    assert ts[2] == pytest.approx(9 * 3600 + 2.5)


def test_frame_times_s_unwraps_midnight():
    """A stamp dropping >12 h reads as the next day, matching fold_tracks."""
    frames = [Frame(t="23:59:59.000", points=()),
              Frame(t="00:00:01.000", points=())]
    ts = frame_times_s(frames)
    assert ts[1] - ts[0] == pytest.approx(2.0)


def test_fused_frame_markers_one_marker_per_vehicle_per_frame():
    """The handoff vehicle (two raw tracks, one fused) is exactly one marker
    per frame in the overlap window — the cross-sensor dedup is preserved on
    screen rather than re-splitting into two markers."""
    frames = _handoff_frames()
    res = fuse(frames, calibrated=True)
    (fid,) = {t.fused_id for t in res.tracks}
    per_frame = fused_frame_markers(res, frame_times_s(frames))
    assert len(per_frame) == len(frames)
    # every frame that has any marker shows exactly the one fused id
    active = [m for m in per_frame if m]
    assert active
    for m in active:
        assert list(m) == [fid]
    # a mid-overlap frame (both sensors reporting) still yields a single marker
    overlap = [i for i, f in enumerate(frames)
               if len({p.sensor for p in f.points}) == 2]
    assert overlap
    for i in overlap:
        assert len(per_frame[i]) == 1


def test_fused_frame_markers_positions_track_the_fused_polyline():
    """Each frame's fused marker sits on that fused track's point nearest the
    frame time — the render reads the engine's coordinates, never re-derives
    them."""
    frames = _handoff_frames()
    res = fuse(frames, calibrated=True)
    times = frame_times_s(frames)
    per_frame = fused_frame_markers(res, times)
    (track,) = res.tracks
    for i, markers in enumerate(per_frame):
        if not markers:
            continue
        (pos,) = markers.values()
        nearest = min(track.points, key=lambda p: abs(p.t_s - times[i]))
        assert pos == pytest.approx((nearest.x_ft, nearest.y_ft))


def test_fused_frame_markers_two_vehicles_two_markers():
    """Two vehicles that never fuse show two distinct fused-id markers in the
    frames where both are present."""
    frames = _frames(
        (10, 30, 0.0, (0.0, 0.0), (30, 0), 51),
        (21, 30, 0.0, (0.0, 25.0), (30, 0), 51),  # 25 ft apart -> no fuse
    )
    res = fuse(frames, calibrated=True)
    per_frame = fused_frame_markers(res, frame_times_s(frames))
    both = [m for m in per_frame if len(m) == 2]
    assert both  # frames where both vehicles are up show two markers
    assert all(len(m) <= 2 for m in per_frame)
