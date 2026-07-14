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
    _Track,
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
        if len(dists) < 10:
            return None  # too few matched samples to be a fair probe
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
            if before is None:
                continue  # too few matched samples to be a fair probe
            after = mean_sep(rec_cal.frames, ka, kb)
            assert after < before
            checked += 1
    assert checked >= 3


@needs_us95
def test_us95_no_class_divide_violations(us95, us95_fused):
    """No fused track anywhere mixes a *driving* motorized member with a
    non-motorized one — the §3/§4 class gate holds across the whole real
    recording.  Members that never beat walking pace are exempt since the
    observation round: the vendor labels pedestrians (and the fragments they
    shed) cls 30, and the behavioral override deliberately reclassifies
    them (module doc)."""
    _, rec = us95
    res, _, _ = us95_fused
    walking = DEFAULT_PARAMS.ped_pct95_ft_s
    raw = {r.key: _Track(r) for r in fold_tracks(rec.frames)}
    for t in res.tracks:
        if any(s >= 4 for s, _ in t.members):
            continue  # vendor-combined: its seam assertion outranks its
            # own flip-flopping per-frame class labels (module doc)
        cats = set()
        for m in t.members:
            r = raw[m]
            if r.cat == "motor" and r.pct95_v <= walking:
                continue  # never beat walking pace: class untrustworthy
            cats.add(r.cat)
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


# --- observation-round mechanisms (2026-07-13; stitch_observations fixture) ---


def test_vendor_seam_merge_joins_both_retired_members():
    """A combined-slot id (oid%10 >= 4) starting the frame after two raw
    tracks die at its birth point absorbs both — the vendor's own fusion,
    honored with zero temporal overlap (module doc)."""
    frames = _frames(
        (20, 30, 0.0, (0.0, 0.0), (30, 0), 20),   # S0 view, dies t=1.9 x=57
        (41, 30, 0.0, (0.0, 3.0), (30, 0), 20),   # S1 view, dies alongside
        (44, 0, 2.0, (60.0, 0.0), (30, 0), 30),   # vendor-combined slot 4
    )
    res = fuse(frames, calibrated=True)
    assert len(res.tracks) == 1
    t = res.tracks[0]
    assert set(t.members) == {(0, 20), (1, 41), (4, 44)}
    assert t.kind == "fused"  # two real sensors behind the combined id
    assert res.id_of[(4, 44)] == res.id_of[(0, 20)]


def test_vendor_seam_ignores_track_moving_the_other_way():
    """The seam's velocity guard: a track coincidentally dying near the
    combined birth while moving against it is not a member."""
    frames = _frames(
        (20, 30, 0.0, (0.0, 0.0), (30, 0), 20),    # true member, dies x=57
        (30, 30, 0.0, (117.0, 4.0), (-30, 0), 20),  # oncoming, dies x=60
        (44, 0, 2.0, (60.0, 0.0), (30, 0), 30),
    )
    res = fuse(frames, calibrated=True)
    fid = res.id_of[(4, 44)]
    members = next(t.members for t in res.tracks if t.fused_id == fid)
    assert (0, 20) in members and (0, 30) not in members


def test_parked_resume_bridges_a_red_light_gap():
    """A queued vehicle re-acquired 45 s later a few feet away is one track —
    beyond the stopped window, inside the parked one."""
    frames = _frames(
        (30, 30, 0.0, (0.0, 0.0), (20, 0), 30),     # ends t=2.9 at x=58
        (40, 30, 48.0, (60.0, 0.0), (15, 0), 30),   # resumes 2 ft on
    )
    res = fuse(frames, calibrated=True)
    assert res.id_of[(0, 30)] == res.id_of[(0, 40)]


def test_parked_resume_occupancy_veto():
    """If another vehicle parked on the spot during the gap, the queue
    flushed and refilled — the resume is a different vehicle: refuse."""
    parker = [(50, 30, 10.0, (59.0, 1.0), (0, 0), 100)]  # parks 10 s there
    drive_off = [(50, 30, 20.0, (59.0, 1.0), (25, 0), 20)]  # then leaves
    frames = _frames(
        (30, 30, 0.0, (0.0, 0.0), (20, 0), 30),
        (40, 30, 48.0, (60.0, 0.0), (15, 0), 30),
        *parker, *drive_off,
    )
    res = fuse(frames, calibrated=True)
    assert res.id_of[(0, 30)] != res.id_of[(0, 40)]


def test_relabel_bridge_tolerates_brief_double_tracking():
    """A same-sensor re-label whose successor is born in the predecessor's
    final moments (small temporal overlap) still bridges."""
    frames = _frames(
        (30, 30, 0.0, (0.0, 0.0), (20, 0), 25),    # ends t=2.4 at x=48
        (40, 30, 2.0, (41.0, 0.0), (20, 0), 25),   # born 0.4 s before that
    )
    res = fuse(frames, calibrated=True)
    assert res.id_of[(0, 30)] == res.id_of[(0, 40)]
    (t,) = res.tracks
    assert [p.t_s for p in t.points] == sorted(p.t_s for p in t.points)


def test_duplicate_twin_absorbed_into_host():
    """A same-sensor twin living its whole life a few feet off a longer
    track (sensor double-tracking) is absorbed, not left as a second
    vehicle."""
    frames = _frames(
        (30, 30, 0.0, (0.0, 0.0), (20, 0), 60),
        (40, 30, 0.5, (10.5, 4.0), (20, 0), 20),   # rides 4 ft off, 2 s
    )
    res = fuse(frames, calibrated=True)
    assert len(res.tracks) == 1
    assert set(res.tracks[0].members) == {(0, 30), (0, 40)}


def test_stopped_queue_neighbours_never_absorb():
    """Two stationary same-sensor tracks 15 ft apart (queued cars in
    adjacent lanes) stay separate: neither is non-motorized and their
    velocities are unreadable."""
    frames = _frames(
        (30, 30, 0.0, (0.0, 0.0), (0, 0), 100),
        (40, 30, 0.0, (0.0, 15.0), (0, 0), 100),
    )
    res = fuse(frames, calibrated=True)
    assert len(res.tracks) == 2


def test_behavioral_pedestrian_override_bridges_misclassified_ped():
    """A long track that never beats walking pace bridges with a cls-10
    pedestrian even though the vendor labeled it cls 30 (the 2_85 capture's
    43 s 'motor' pedestrian)."""
    frames = _frames(
        (10, 10, 0.0, (0.0, 0.0), (4, 0), 100),      # ped, ends t=9.9 x=39.6
        (21, 30, 10.0, (40.4, 0.0), (4, 0), 150),    # "cls 30", walking pace
    )
    res = fuse(frames, calibrated=True)
    assert res.id_of[(0, 10)] == res.id_of[(1, 21)]
    fid = res.id_of[(0, 10)]
    t = next(t for t in res.tracks if t.fused_id == fid)
    assert t.category == "non_motor"


def test_flicker_flagged_stray():
    """A sub-second track that goes nowhere is kind='stray' — flagged, not
    deleted."""
    frames = _frames((30, 30, 0.0, (0.0, 0.0), (3, 0), 8))
    res = fuse(frames, calibrated=True)
    (t,) = res.tracks
    assert t.kind == "stray"


def test_shadow_flagged_stray():
    """A short-lived track riding a fixed offset beside a much longer
    concurrent companion moving the same way (a radar shadow) is flagged."""
    frames = _frames(
        (30, 30, 0.0, (0.0, 0.0), (30, 0), 100),      # the real vehicle
        (40, 30, 3.0, (90.0, 25.0), (30, 0), 30),     # 25 ft shadow, 3 s
    )
    res = fuse(frames, calibrated=True)
    kinds = {t.members[0]: t.kind for t in res.tracks}
    assert kinds[(0, 40)] == "stray"
    assert kinds[(0, 30)] != "stray"


OBS_FIXTURE = FIXTURES / "stitch_observations_2026-07-13.json"
SITES = Path(__file__).resolve().parents[3] / "sites"


@pytest.mark.skipif(not SITES.exists(), reason="sites/ captures not present")
def test_observation_acceptance_2_86_xx735():
    """Owner-labeled acceptance on the 2_86_xx735 capture (2026-07-13
    observation round): confirmed red-light queue pairs bridge, anchors
    stay clean of same-sensor absorption, the labeled stray never stands
    as its own real track."""
    import gzip

    obs = json.loads(OBS_FIXTURE.read_text())["captures"]["2_86_xx735"]
    proj = load_iprj(US95_IPRJ)
    rec = load_recording(proj, US95_REC, max_frames=None)
    res = fuse(rec.frames, calibrated=False)

    id_of = res.id_of
    by_fid = {t.fused_id: t for t in res.tracks}
    # confirmed (not 'unsure') persistence pairs share one fused track
    for g in obs["groups"]:
        members = [tuple(m) for m in g["members"]]
        if g["kind"] == "persistence" and not g.get("unsure"):
            assert len({id_of[m] for m in members}) == 1, g
        elif g["kind"] == "anchor" and members[0] != (1, 422141):
            # 422141 is the documented uncalibrated wide-gate miss
            (m,) = members
            t = by_fid[id_of[m]]
            same_sensor_extras = [
                x for x in t.members if x != m and x[0] == m[0]]
            assert not same_sensor_extras, g
        elif g["kind"] == "stray":
            (m,) = members
            t = by_fid[id_of[m]]
            assert t.kind == "stray" or len(t.members) > 1, g


# --- stuck-ghost tail trimming (2026-07-14 round) --------------------------------


def test_stuck_tail_split_into_ghost():
    """A moving track that freezes from full speed inside one sample and holds
    to its death is split: the live head keeps the id_of entry, the frozen
    tail surfaces as a dimmed kind="ghost" track."""
    frames = _frames(
        (10, 30, 0.0, (0, 0), (30, 0), 31),      # moving, 0..90 ft over 3 s
        (10, 30, 3.1, (93, 0), (0, 0), 50),      # frozen 4.9 s, dies frozen
    )
    res = fuse(frames, calibrated=True)
    ghosts = [t for t in res.tracks if t.kind == "ghost"]
    assert len(ghosts) == 1
    (g,) = ghosts
    assert g.members == ((0, 10),)
    # the tail holds the hold radius around the frozen spot (the last in-
    # radius moving sample is swallowed into the suffix by construction)
    assert all(abs(p.x_ft - 93.0) <= DEFAULT_PARAMS.stuck_hold_r_ft
               for p in g.points)
    live = [t for t in res.tracks if t.kind != "ghost"]
    assert len(live) == 1
    assert live[0].points[-1].x_ft == pytest.approx(87.0)
    # the shared member key resolves to the live head, not the ghost
    assert res.id_of[(0, 10)] == live[0].fused_id


def test_braking_stop_keeps_its_tail():
    """A real car decelerating to a stop (even briskly) arrives at the hold
    radius slowly — physically plausible, so the frozen tail is kept."""
    pts = []
    t, x, v = 0.0, 0.0, 30.0
    while v > 0:  # brake at 10 ft/s^2, sampled at 10 fps
        pts.append((t, x))
        x += v * 0.1
        v -= 1.0
        t += 0.1
    hold_until = t + 5.0
    while t < hold_until:  # holds 5 s at the stop, then the track drops
        pts.append((t, x))
        t += 0.1
    frames = [Frame(t=_t(tt), points=(_pt(10, xx, 0.0),)) for tt, xx in pts]
    res = fuse(frames, calibrated=True)
    assert [t.kind for t in res.tracks] == ["single"]
    assert len(res.tracks[0].points) == len(pts)


def test_parked_position_hop_not_trimmed():
    """A stopped car whose radar position hops once (big boundary step, near-
    zero net window displacement) is not a stick — the window gate rejects."""
    frames = _frames(
        (10, 30, 0.0, (0, 0), (30, 0), 21),      # drives 60 ft
        (10, 30, 2.1, (60, 0), (0, 0), 12),      # stops 1.2 s
        (10, 30, 3.3, (65, 0), (0, 0), 50),      # hops 5 ft, frozen to death
    )
    res = fuse(frames, calibrated=True)
    assert not [t for t in res.tracks if t.kind == "ghost"]


def test_freeze_that_resumes_is_not_a_stick():
    """A mid-track freeze that resumes moving was a stop, not a stick — the
    tail-only trim never touches it."""
    frames = _frames(
        (10, 30, 0.0, (0, 0), (30, 0), 21),
        (10, 30, 2.1, (63, 0), (0, 0), 40),      # frozen 4 s mid-track
        (10, 30, 6.1, (64, 0), (10, 0), 20),     # resumes
    )
    res = fuse(frames, calibrated=True)
    assert not [t for t in res.tracks if t.kind == "ghost"]
    assert len(res.tracks) == 1


def test_ghost_tail_no_longer_vetoes_parked_resume():
    """The motivating case (module doc): a stuck ghost frozen on a queue spot
    used to trip the parked-resume occupancy veto and split a real red-light
    resume. Trimmed, the veto sees only the ghost's moving head."""
    specs = [
        (10, 30, 0.0, (50, 0), (10, 0), 51),     # A arrives at (100, 0) ...
        (10, 30, 5.1, (100, 0), (0, 0), 10),     # ... stops 1 s, drops
        (110, 30, 45.0, (102, 0), (15, 0), 30),  # A's resume 39 s later
        # the stick: drives -x through the corridor, freezes at (100, 2) —
        # 2 ft off A's parking spot — for ~10 s during A's gap, then dies
        (20, 30, 15.0, (160, 2), (-30, 0), 20),
        (20, 30, 17.0, (100, 2), (0, 0), 100),
    ]
    res = fuse(_frames(*specs), calibrated=True)
    assert res.id_of[(0, 10)] == res.id_of[(0, 110)]  # the resume bridges
    by_fid = {t.fused_id: t for t in res.tracks}
    assert set(by_fid[res.id_of[(0, 10)]].members) == {(0, 10), (0, 110)}
    assert [t.kind for t in res.tracks].count("ghost") == 1
    # control: with trimming disabled the frozen tail poisons the stitch —
    # the stick gets absorbed into the real vehicle's trajectory
    no_trim = FusionParams(stuck_v_fast_ft_s=math.inf)
    res2 = fuse(_frames(*specs), calibrated=True, params=no_trim)
    by_fid2 = {t.fused_id: t for t in res2.tracks}
    assert (0, 20) in by_fid2[res2.id_of[(0, 10)]].members


# --- render-side seam smoothing (2026-07-14 round) --------------------------------


def _smoothing_case():
    """A cross-sensor handoff with a 4-ft lateral disagreement: the blend ramps
    y from 0 to 4 across the overlap, leaving a kink at either end."""
    frames = _frames(
        (10, 30, 0.0, (0, 0), (30, 0), 21),       # sensor 0, y = 0
        (21, 30, 1.5, (45, 4), (30, 0), 26),      # sensor 1, y = 4
    )
    return fuse(frames, calibrated=True)


def test_smooth_seams_touches_only_the_seam_window():
    from model.fusion import smooth_seams

    res = _smoothing_case()
    sm = smooth_seams(res, window_s=1.0)
    (tr,), (tr2,) = res.tracks, sm.tracks
    assert tr2.fused_id == tr.fused_id and tr2.members == tr.members
    assert [p.t_s for p in tr2.points] == [p.t_s for p in tr.points]
    assert [p.src for p in tr2.points] == [p.src for p in tr.points]
    t0 = 9 * 3600  # _t() stamps are seconds past 9am
    changed = [a.t_s - t0 for a, b in zip(tr.points, tr2.points)
               if (a.x_ft, a.y_ft) != (b.x_ft, b.y_ft)]
    assert changed, "the seam window must actually smooth"
    # seams live in the 1.5..2.0 overlap; ±1 s reaches at most 0.5..3.0
    assert min(changed) >= 0.5 - 1e-9
    assert max(changed) <= 3.0 + 1e-9


def test_smooth_seams_reduces_handoff_jerk():
    from model.fusion import smooth_seams

    res = _smoothing_case()
    sm = smooth_seams(res, window_s=1.0)

    def max_step(tr):
        ys = [p.y_ft for p in tr.points]
        return max(abs(b - a) for a, b in zip(ys, ys[1:]))

    assert max_step(sm.tracks[0]) < max_step(res.tracks[0])
    # and the lateral transition still lands on sensor 1's lane
    assert sm.tracks[0].points[-1].y_ft == pytest.approx(4.0)


def test_smooth_seams_leaves_single_tracks_untouched():
    from model.fusion import smooth_seams

    frames = _frames((10, 30, 0.0, (0, 0), (30, 0), 40))
    res = fuse(frames, calibrated=True)
    sm = smooth_seams(res, window_s=1.0)
    assert sm.tracks == res.tracks
    assert dict(sm.id_of) == dict(res.id_of)


# --- 2026-07-14 calibrated-eval round: flicker veto + stitch<->fuse fixpoint ----


def test_flicker_blip_never_anchors_a_bridge():
    """A single-sample blip on a queue spot must not bridge onto the vehicle
    acquired there later (the 2_86_xx107 regression): one radar sample has no
    velocity, reads "stopped", and under the generous stopped gates it used
    to merge — poisoning the fused track's sensor set so the vehicle's true
    cross-sensor partner could never associate. The flicker veto refuses the
    blip as a bridge endpoint; it stands alone and is flagged a stray."""
    frames = _frames(
        (11, 30, 0.0, (0.0, 0.0), (0.0, 0.0), 1),       # sensor-1 blip
        (20, 30, 14.2, (2.0, 0.0), (20.0, 0.0), 100),   # sensor-0 vehicle
        # sensor-1 view of the same vehicle, acquired mid-track far from the
        # blip (out of its stopped-gate range), riding ~3 ft off sensor 0
        (31, 30, 17.6, (70.0, 3.0), (20.0, 0.0), 58),
    )
    res = fuse(frames, calibrated=True)
    assert res.id_of[(0, 20)] == res.id_of[(1, 31)]  # the real handoff fuses
    by_fid = {t.fused_id: t for t in res.tracks}
    blip = by_fid[res.id_of[(1, 11)]]
    assert blip.members == ((1, 11),)
    assert blip.kind == "stray"
    assert by_fid[res.id_of[(0, 20)]].kind == "fused"


def test_queue_resume_bridges_after_cross_sensor_association():
    """A red-light gap seen by two sensors: at the raw stage every endpoint
    has two comparably-close successor views (its own sensor's and the
    other's), so the ambiguity margin rightly refuses every bridge — but
    once cross-sensor association merges each side's views into one
    composite, the resume is unique and must bridge (the stitch<->fuse
    fixpoint, 2_86_xx107's second regression)."""
    frames = _frames(
        # before the light: both sensors watch the vehicle drive up and park
        # (sensor 1's view rides ~3 ft ahead along the lane)
        (40, 30, 0.0, (0.0, 0.0), (20.0, 0.0), 50),
        (40, 30, 5.0, (100.0, 0.0), (0.0, 0.0), 30),
        (41, 30, 0.1, (3.0, 0.0), (20.0, 0.0), 49),
        (41, 30, 5.05, (103.0, 0.0), (0.0, 0.0), 30),
        # green, ~9 s later: both sensors re-acquire it pulling away
        (50, 30, 17.0, (101.0, 0.0), (20.0, 0.0), 60),
        (51, 30, 17.1, (104.5, 0.0), (20.0, 0.0), 58),
    )
    res = fuse(frames, calibrated=True)
    fids = {res.id_of[k] for k in ((0, 40), (1, 41), (0, 50), (1, 51))}
    assert len(fids) == 1, f"queue resume split across fused ids {fids}"
    track = next(t for t in res.tracks if t.fused_id == fids.pop())
    assert track.kind == "fused"
