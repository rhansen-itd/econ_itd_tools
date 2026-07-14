"""Composed transform + N-sensor relational calibration (ROADMAP Item 39).

Synthetic tests inject a *known* rigid misalignment into one sensor's raw
detections, so the closed-form solver must recover its inverse to float
precision, and build placements with known parameters so the compose order
and the commit sign/units math are checked against hand-computed values.

Real-site tests run the whole loop on the US95&SH8 fixture pair — a genuine
two-sensor site whose stream also carries two sparse extra sensor ids (4, 5),
which exercise the too-few-pairs guardrails on real data. The three
correctness gates the plan hands this item (CALIBRATION_ALIGNMENT_PLAN.md
§8): calibration recovery, group-placement compose-order, and the
commit→re-solve ≈identity round trip that pins the azimuth sign.
"""

import math
from dataclasses import replace
from pathlib import Path

import pytest

from model import units, zonefit
from model.calibration import (
    COARSE_MATCH_DIST_M,
    IDENTITY,
    MIN_PAIRS,
    AlignmentTransform,
    Placement,
    RigidDelta,
    WorldDelta,
    build_alignment,
    calibrate,
    commit_alignment,
    committed_sensor_config,
    find_pairs,
    invert_alignment_m,
    invert_placement_m,
    rotated_about,
    translated,
    translation_placement,
    world_delta,
)
from model.iprj_io import load_iprj
from model.replay import (Frame, LiveAligner, Recording, TrackPoint,
                          anchor_world_ft, autocalibrate, load_recording,
                          realign)
from test_zonefit import _make_site, _zline

FIXTURES = Path(__file__).resolve().parent / "fixtures"
US95_REC = FIXTURES / "10_37_2_86_EVO_1770311735.txt"
US95_IPRJ = FIXTURES / "us95&sh8.iprj"

needs_us95 = pytest.mark.skipif(
    not US95_REC.is_file() or not US95_IPRJ.is_file(),
    reason="US95 fixtures not present")


# --- synthetic frames: a known misalignment to recover ---------------------------


def _pt(oid: int, x_m: float, y_m: float) -> TrackPoint:
    return TrackPoint(oid=oid, sensor=oid % 10, cls=1, x_ft=0.0, y_ft=0.0,
                      heading=None, x_raw_m=x_m, y_raw_m=y_m)


def _misaligned_frames(mis: RigidDelta, n: int = 80,
                       spread: float = 60.0) -> list[Frame]:
    """One vehicle per frame sweeping a 2-D arc; sensor 0 reports truth,
    sensor 1 reports through the misalignment *mis*."""
    frames = []
    for i in range(n):
        k = 2 * math.pi * i / n
        x = spread * math.cos(k)
        y = 0.5 * spread * math.sin(2 * k) + 10.0
        mx, my = mis.apply_m(x, y)
        frames.append(Frame(t="00:00:00.000",
                            points=(_pt(10, x, y), _pt(11, mx, my))))
    return frames


def test_rigid_delta_algebra():
    d = RigidDelta.make(30.0, (3.0, -2.0))
    assert d.theta_deg == pytest.approx(30.0)
    # y-down complex sense: rotating (1, 0) by +90° gives (0, 1)
    q = RigidDelta.make(90.0)
    assert q.apply_m(1.0, 0.0) == pytest.approx((0.0, 1.0))
    # compose applies right-to-left; inverse cancels exactly
    p = RigidDelta.make(-12.0, (5.0, 7.0))
    x, y = 4.0, -9.0
    assert d.compose(p).apply_m(x, y) == pytest.approx(d.apply_m(*p.apply_m(x, y)))
    r = d.inverse().compose(d)
    assert r.theta_deg == pytest.approx(0.0, abs=1e-12)
    assert (r.d_x, r.d_y) == pytest.approx((0.0, 0.0), abs=1e-12)
    assert r.apply_m(x, y) == pytest.approx((x, y))


def test_solver_recovers_injected_misalignment_exactly():
    """The Item 38 recovery gate, exact case: noise-free pairs through a known
    rigid misalignment must solve to its inverse at float precision."""
    mis = RigidDelta.make(2.0, (1.5, -1.0))
    cal = calibrate(_misaligned_frames(mis), frame_stride=1)
    entry = cal.for_sensor(1)
    assert entry.status == "ok"
    assert entry.n_pairs == 80
    assert entry.mean_residual_m == pytest.approx(0.0, abs=1e-9)
    got = cal.deltas[1]
    # C ∘ mis == identity: the correction re-agrees the perturbed sensor
    rt = got.compose(mis)
    assert rt.theta_deg == pytest.approx(0.0, abs=1e-9)
    assert (rt.d_x, rt.d_y) == pytest.approx((0.0, 0.0), abs=1e-9)
    # and the reference is the gauge: identity by absence
    assert cal.for_sensor(0).status == "reference"
    assert 0 not in cal.deltas


def test_guardrails_flag_instead_of_guessing():
    mis = RigidDelta.make(1.0, (1.0, 1.0))
    frames = _misaligned_frames(mis, n=60)
    # sensor 2: appears, but 500 m from any reference point -> no pairs
    # sensor 3: co-located but only in 10 frames -> too few pairs
    aug = []
    for i, f in enumerate(frames):
        pts = list(f.points)
        pts.append(_pt(12, 500.0 + i, 500.0))
        if i < 10:
            pts.append(_pt(13, f.points[0].x_raw_m + 0.5, f.points[0].y_raw_m))
        aug.append(Frame(t=f.t, points=tuple(pts)))
    cal = calibrate(aug, frame_stride=1)
    assert cal.for_sensor(2).status == "no_pairs"
    assert cal.for_sensor(3).status == "too_few_pairs"
    assert cal.for_sensor(3).n_pairs == 10
    for s in (2, 3):
        assert s not in cal.deltas
        assert cal.for_sensor(s).flagged
        assert cal.for_sensor(s).delta == IDENTITY
    assert {e.sensor for e in cal.flagged} == {2, 3}
    # sensor 1 is unaffected by the junk sensors
    assert cal.for_sensor(1).status == "ok"


def test_short_lever_arm_falls_back_to_translation_only():
    """Pairs clustered tighter than MIN_SPREAD_M can't pin rotation (the
    zonefit MIN_SPREAD_FT analogue): keep the translation, drop the rotation,
    flag the sensor."""
    mis = RigidDelta.make(0.0, (2.0, -3.0))
    frames = []
    for i in range(60):
        x, y = 100.0 + (i % 8) * 0.5, 50.0 + (i % 5) * 0.5  # ~4 m cluster
        frames.append(Frame(t="00:00:00.000",
                            points=(_pt(10, x, y), _pt(11, *mis.apply_m(x, y)))))
    cal = calibrate(frames, frame_stride=1)
    entry = cal.for_sensor(1)
    assert entry.status == "translation_only"
    assert entry.flagged
    got = cal.deltas[1]  # translation-only is still a usable correction
    assert got.theta_deg == 0.0
    assert (got.d_x, got.d_y) == pytest.approx((-2.0, 3.0), abs=1e-9)


def test_inconsistent_pairs_are_refused():
    """Pairs no rigid map can explain (mean residual above the gate) come
    back identity + flagged — a wrong correction is worse than none."""
    frames = []
    for i in range(60):
        k = 2 * math.pi * i / 60
        x, y = 80.0 * math.cos(k), 40.0 * math.sin(2 * k)
        # alternate ±8 m: nearest-rigid-fit residual ≈ 8 m > the 5 m gate
        off = 8.0 if i % 2 else -8.0
        frames.append(Frame(t="00:00:00.000",
                            points=(_pt(10, x, y), _pt(11, x + off, y))))
    cal = calibrate(frames, frame_stride=1)
    entry = cal.for_sensor(1)
    assert entry.status == "high_residual"
    assert entry.mean_residual_m > 5.0
    assert 1 not in cal.deltas


def test_degenerate_input_never_raises():
    assert calibrate([]).sensors == ()
    # reference sensor absent from the stream: everything is unpairable
    mis = RigidDelta.make(1.0)
    cal = calibrate(_misaligned_frames(mis), reference=9, frame_stride=1)
    assert all(e.status == "no_pairs" for e in cal.sensors)
    assert cal.deltas == {}


# --- compose order + placement handle --------------------------------------------


def test_transform_composes_calibration_before_placement():
    """The load-bearing order (plan §1): Cᵢ in EVO meters first, then G to
    world feet. With a scaled placement the two orders differ numerically."""
    delta = RigidDelta.make(15.0, (2.0, -1.0))
    placement = Placement(2.0, 0.5, 100.0, -40.0)  # scale ≈ 2.06, rotated
    tr = AlignmentTransform(calib={1: delta}, placement=placement)
    x, y = 12.0, -7.0
    assert tr.apply(1, x, y) == pytest.approx(placement.apply_m(*delta.apply_m(x, y)))
    # wrong order would differ
    wrong = delta.apply_m(*(units.ft_to_m(v) for v in placement.apply_m(x, y)))
    assert tr.apply(1, x, y) != pytest.approx(wrong)
    # a sensor with no delta passes through the placement untouched, exactly
    assert tr.apply(0, x, y) == placement.apply_m(x, y)


def test_translation_placement_reproduces_legacy_fallback():
    anchor, ref = (1234.5, -678.9), (5.0, 7.5)
    p = translation_placement(anchor, ref)
    for x, y in ((0.0, 0.0), (12.3, -4.5), (5.0, 7.5)):
        legacy = (anchor[0] + units.m_to_ft(x - ref[0]),
                  anchor[1] + units.m_to_ft(y - ref[1]))
        assert p.apply_m(x, y) == pytest.approx(legacy, abs=1e-9)
    assert p.scale == 1.0 and p.rotation_deg == 0.0


def test_group_move_edits_placement_as_a_rigid_body():
    """A translate + rotate-about-pivot on the placement moves every world
    point by exactly that rigid map (so a locked group drag can never bend
    the calibrated cluster), scale untouched."""
    proj, zones = _make_site()
    seed = zonefit.fit(proj, zones)
    pivot, ang, dxy = (400.0, 300.0), 5.0, (25.0, -10.0)
    moved = translated(rotated_about(seed, pivot, ang), *dxy)
    assert isinstance(moved, Placement)
    assert moved.scale == pytest.approx(seed.scale, abs=1e-12)
    assert moved.rotation_deg == pytest.approx(seed.rotation_deg + ang)
    q = complex(math.cos(math.radians(ang)), math.sin(math.radians(ang)))
    for e_m in ((3.0, 4.0), (-20.0, 15.0), (0.0, 0.0)):
        w = complex(*seed.apply_m(*e_m))
        expect = q * (w - complex(*pivot)) + complex(*pivot) + complex(*dxy)
        assert moved.apply_m(*e_m) == pytest.approx((expect.real, expect.imag))


def test_nudged_delta_moves_markers_by_exactly_the_drag():
    """Item 40's unlocked per-sensor gesture: nudging a sensor's Cᵢ by a
    world-feet drag Δw moves that sensor's markers by exactly Δw under the
    placement, whatever the placement's rotation/scale — and leaves rotation
    untouched (position-only handle, plan §4)."""
    from model.calibration import nudged_delta

    proj, zones = _make_site()
    placement = zonefit.fit(proj, zones)  # rotated, scaled real fit
    delta = RigidDelta.make(3.0, (2.0, -1.0))
    dw = (17.0, -9.5)  # world feet
    nudged = nudged_delta(delta, placement, dw)
    assert nudged.theta_deg == pytest.approx(delta.theta_deg)  # rotation held
    for e_m in ((10.0, 20.0), (-30.0, 5.0), (0.0, 0.0)):
        w0 = placement.apply_m(*delta.apply_m(*e_m))
        w1 = placement.apply_m(*nudged.apply_m(*e_m))
        assert (w1[0] - w0[0], w1[1] - w0[1]) == pytest.approx(dw, abs=1e-9)
    # a degenerate zero-scale placement passes the delta through unchanged
    assert nudged_delta(delta, Placement(0.0, 0.0, 1.0, 1.0), dw) == delta


def test_invert_placement_roundtrips():
    proj, zones = _make_site()
    zf = zonefit.fit(proj, zones)
    manual = rotated_about(translated(zf, 12.0, -8.0), (100.0, 100.0), -20.0)
    for p in (zf, manual, translation_placement((50.0, 60.0), (1.0, 2.0))):
        for e_m in ((7.0, -3.0), (0.0, 0.0), (-41.2, 18.9)):
            w = p.apply_m(*e_m)
            assert invert_placement_m(p, *w) == pytest.approx(e_m, abs=1e-9)
    with pytest.raises(ValueError):
        invert_placement_m(Placement(0.0, 0.0, 1.0, 1.0), 0.0, 0.0)


def test_zonefit_identity_calib_is_bit_identical():
    """The plan-§0 reduction at the fit level: identity deltas leave the
    calibrated refit equal (dataclass ==, so bit-for-bit) to today's fit."""
    proj, zones = _make_site()
    base = zonefit.fit(proj, zones)
    assert zonefit.fit(proj, zones, calib={0: IDENTITY, 2: IDENTITY}) == base
    assert zonefit.fit(proj, zones, calib={}) == base


def test_zonefit_calibrated_refit_absorbs_a_sensor_delta():
    """Perturb one slot's stream zones by a rigid map, hand fit() its inverse
    as that slot's calibration: the refit must recover the original
    similarity (the compose-consistency seam, plan §1)."""
    proj, zones = _make_site()
    base = zonefit.fit(proj, zones)
    mis = RigidDelta.make(3.0, (4.0, -2.5))
    perturbed = [
        replace(z, points_m=tuple(mis.apply_m(*p) for p in z.points_m))
        if z.slot == 2 else z
        for z in zones]
    refit = zonefit.fit(proj, perturbed, calib={2: mis.inverse()})
    assert refit is not None
    assert refit.rotation_deg == pytest.approx(base.rotation_deg, abs=1e-9)
    assert refit.scale == pytest.approx(base.scale, abs=1e-12)
    assert refit.mean_residual_ft == pytest.approx(0.0, abs=1e-9)


# --- the sensor-move delta + commit math (plan §5c, reframed 2026-07-11) ----------


def test_world_delta_identity_when_nothing_authored():
    """current == base → every sensor's delta is exactly identity, so ghosts
    sit on the sensors and commit_alignment proposes nothing."""
    proj, zones = _make_site()
    zf = zonefit.fit(proj, zones)
    tr = AlignmentTransform(calib={}, placement=zf)
    for slot in (0, 1, 2):
        wd = world_delta(tr, tr, slot)
        assert wd.rotation_deg == pytest.approx(0.0, abs=1e-9)
        assert wd.scale == pytest.approx(1.0, abs=1e-12)
        assert wd.apply_ft(123.4, -56.7) == pytest.approx((123.4, -56.7), abs=1e-6)
        assert not wd.moves((123.4, -56.7))
    assert commit_alignment(proj, tr, tr) == {}


def test_world_delta_group_move_is_the_same_rigid_map_for_every_sensor():
    """A pure group drag+rotate (no calibration) reads as one world-feet rigid
    move applied to every sensor — the block gesture the owner described:
    ghost sensors and markers translate/rotate together."""
    proj, zones = _make_site()
    zf = zonefit.fit(proj, zones)
    base = AlignmentTransform(calib={}, placement=zf)
    pivot, ang, dxy = (350.0, 250.0), 6.0, (30.0, -12.0)
    cur = AlignmentTransform(
        calib={}, placement=translated(rotated_about(zf, pivot, ang), *dxy))
    q = complex(math.cos(math.radians(ang)), math.sin(math.radians(ang)))
    for slot in (0, 1, 2):
        wd = world_delta(base, cur, slot)
        assert wd.rotation_deg == pytest.approx(ang)
        assert wd.scale == pytest.approx(1.0, abs=1e-9)
        for w in ((0.0, 0.0), (500.0, 300.0), (-40.0, 90.0)):
            expect = q * (complex(*w) - complex(*pivot)) + complex(*pivot) \
                + complex(*dxy)
            assert wd.apply_ft(*w) == pytest.approx(
                (expect.real, expect.imag), abs=1e-6)


def test_world_delta_calibration_only_matches_the_conjugated_rigid_map():
    """With the same placement on both sides, a sensor's delta is exactly the
    similarity-conjugated Cᵢ: rotation θ (the "ADD θ°" sign) and position
    G(C(G⁻¹(pos))) — the old commit math as a special case."""
    proj, zones = _make_site()
    zf = zonefit.fit(proj, zones)
    delta = RigidDelta.make(-4.0, (3.0, 6.0))
    base = AlignmentTransform(calib={}, placement=zf)
    cur = AlignmentTransform(calib={1: delta}, placement=zf)
    wd = world_delta(base, cur, 1)
    assert wd.rotation_deg == pytest.approx(delta.theta_deg)
    assert wd.scale == pytest.approx(1.0, abs=1e-9)
    pos_ft = (712.6, 388.1)
    expect = zf.apply_m(*delta.apply_m(*invert_placement_m(zf, *pos_ft)))
    assert wd.apply_ft(*pos_ft) == pytest.approx(expect, abs=1e-6)
    # conjugation preserves rigidity: the sensor moves the same distance C
    # moves its EVO-frame image (in feet)
    e_m = invert_placement_m(zf, *pos_ft)
    moved_ft = math.dist(pos_ft, wd.apply_ft(*pos_ft))
    assert moved_ft == pytest.approx(
        units.m_to_ft(math.dist(e_m, delta.apply_m(*e_m))) * zf.scale, rel=1e-9)
    # an uncalibrated sensor passes through identity
    assert world_delta(base, cur, 0).apply_ft(*pos_ft) == pytest.approx(
        pos_ft, abs=1e-6)


def test_invert_alignment_roundtrips_the_composed_transform():
    proj, zones = _make_site()
    zf = zonefit.fit(proj, zones)
    tr = AlignmentTransform(calib={2: RigidDelta.make(3.0, (1.0, -2.0))},
                            placement=zf)
    for slot in (0, 2):
        for e_m in ((7.0, -3.0), (0.0, 0.0), (-41.2, 18.9)):
            w = tr.apply(slot, *e_m)
            assert invert_alignment_m(tr, slot, *w) == pytest.approx(
                e_m, abs=1e-9)


def test_commit_identity_delta_changes_nothing():
    proj, zones = _make_site()
    emp = units.effective_meter_per_pixel(proj.background)
    wd = WorldDelta(1.0, 0.0, 0.0, 0.0)
    az, pos = committed_sensor_config(-170.56, (855.95, 313.82), wd, emp)
    assert az == pytest.approx(-170.56)
    assert pos == pytest.approx((855.95, 313.82), abs=1e-9)


def test_commit_alignment_writes_a_pure_group_move():
    """The 2026-07-11 reframing's new case: no calibration at all, just a
    group drag — every mapped sensor commits the same rigid move."""
    proj, zones = _make_site()
    zf = zonefit.fit(proj, zones)
    emp = units.effective_meter_per_pixel(proj.background)
    base = AlignmentTransform(calib={}, placement=zf)
    cur = AlignmentTransform(calib={}, placement=translated(zf, 20.0, -8.0))
    updates = commit_alignment(proj, cur, base)
    assert set(updates) == {si for _, si in zf.slot_to_sensor}
    for si, (az, px) in updates.items():
        s = proj.sensors[si]
        assert az == pytest.approx(s.azimuth_angle or 0.0)  # translation only
        moved = (units.px_to_ft(px[0] - s.position_x, emp),
                 units.px_to_ft(px[1] - s.position_y, emp))
        assert moved == pytest.approx((20.0, -8.0), abs=1e-6)
    # nothing was mutated by the pure commit
    assert proj.sensors[next(iter(updates))].position_x is not None


# --- slot restriction + auto reference (the "S5/S6" fix, 2026-07-11) --------------


def test_calibrate_slots_filter_ignores_stray_stream_ids():
    """Stray oid%10 slots (fused/transient ids) are not sensors: with the
    mapped-slots filter they are neither solved nor reported, so a 4-sensor
    site can never report an impossible "S5/S6"."""
    mis = RigidDelta.make(1.0, (1.0, 1.0))
    frames = []
    for i, f in enumerate(_misaligned_frames(mis, n=60)):
        pts = list(f.points)
        pts.append(_pt(14, 500.0 + i, 500.0))  # stray slot 4, sparse
        if i < 10:
            pts.append(_pt(15, 300.0, 300.0 + i))  # stray slot 5
        frames.append(Frame(t=f.t, points=tuple(pts)))
    unrestricted = calibrate(frames, frame_stride=1)
    assert {e.sensor for e in unrestricted.sensors} == {0, 1, 4, 5}
    cal = calibrate(frames, frame_stride=1, slots={0, 1})
    assert {e.sensor for e in cal.sensors} == {0, 1}
    assert not cal.flagged
    assert cal.for_sensor(1).status == "ok"


def test_calibrate_auto_reference_picks_the_best_observed_slot():
    """reference=None anchors the gauge on the slot with the most detections
    — a site whose stream has no slot 0 still solves instead of returning
    all-no_pairs against a nonexistent reference."""
    mis = RigidDelta.make(2.0, (1.5, -1.0))
    # renumber the synthetic frames' sensors 0/1 -> 1/2 (no slot 0 at all)
    frames = [
        Frame(t=f.t, points=tuple(
            replace(p, oid=p.oid + 1, sensor=p.sensor + 1) for p in f.points))
        for f in _misaligned_frames(mis)]
    all_no_pairs = calibrate(frames, frame_stride=1)  # legacy slot-0 gauge
    assert all(e.status == "no_pairs" for e in all_no_pairs.sensors)
    cal = calibrate(frames, frame_stride=1, reference=None)
    assert cal.reference in (1, 2)
    other = 2 if cal.reference == 1 else 1
    assert cal.for_sensor(cal.reference).status == "reference"
    assert cal.for_sensor(other).status == "ok"


# --- real multi-sensor site: the three plan-§8 correctness gates ------------------


@pytest.fixture(scope="module")
def us95():
    proj = load_iprj(US95_IPRJ)
    rec = load_recording(proj, US95_REC, max_frames=None)
    return proj, rec


@pytest.fixture(scope="module")
def us95_cal(us95):
    _, rec = us95
    return calibrate(rec.frames)


def _map_sensor_raw(frames, sensor, delta):
    """Simulate the corrected device: sensor *sensor*'s raw EVO detections
    re-emitted through *delta* (world coords irrelevant to the solver)."""
    out = []
    for f in frames:
        pts = tuple(
            replace(p, x_raw_m=delta.apply_m(p.x_raw_m, p.y_raw_m)[0],
                    y_raw_m=delta.apply_m(p.x_raw_m, p.y_raw_m)[1])
            if p.sensor == sensor else p
            for p in f.points)
        out.append(Frame(t=f.t, points=pts))
    return out


@needs_us95
def test_us95_relational_solve(us95_cal):
    """The real two-sensor site: sensor 1 solves cleanly against sensor 0
    (the ~0.7°/7 m disagreement the owner's script also finds on this class
    of site); the sparse extra stream ids 4 and 5 are refused, not fit."""
    entry = us95_cal.for_sensor(1)
    assert entry.status == "ok"
    assert entry.n_pairs > 300
    assert 0.0 < entry.delta.theta_deg < 2.0
    assert entry.mean_residual_m < 3.0
    assert math.hypot(entry.delta.d_x, entry.delta.d_y) < 10.0
    for s in (4, 5):
        assert us95_cal.for_sensor(s).status in ("no_pairs", "too_few_pairs")
        assert s not in us95_cal.deltas
    assert us95_cal.for_sensor(0).status == "reference"


@needs_us95
def test_calibration_recovery_on_real_site(us95, us95_cal):
    """The roadmap's recovery gate on real radar data: perturb one sensor's
    frame by a known rigid map and the solver must recover the delta that
    re-agrees it (up to the pairing noise of a statistical fit)."""
    _, rec = us95
    # start from the corrected stream so the perturbation is the only error
    agreed = _map_sensor_raw(rec.frames, 1, us95_cal.deltas[1])
    mis = RigidDelta.make(1.5, (2.0, -1.0))
    recovered = calibrate(_map_sensor_raw(agreed, 1, mis)).deltas[1]
    rt = recovered.compose(mis)
    # ≈identity at pairing-noise scale, an order of magnitude below both the
    # injected perturbation (1.5°, 2.2 m) and the site's own correction
    # (measured: 0.23°, 0.47 m)
    assert rt.theta_deg == pytest.approx(0.0, abs=0.5)
    assert math.hypot(rt.d_x, rt.d_y) < 1.0


@needs_us95
def test_commit_then_resolve_is_identity(us95, us95_cal):
    """The commit→reload ≈identity round trip (plan §5c, honest scope): after
    folding C₁ into the config, the corrected stream re-solves to ≈identity —
    the pure-function proof the commit math and its signs are self-consistent."""
    proj, rec = us95
    transform = build_alignment(proj, rec.zones, us95_cal)
    assert transform is not None
    # base shares the placement so the committed delta is exactly the
    # conjugated C₁ — the sign-pinning isolation; the composed group-move
    # case is covered by test_commit_alignment_writes_a_pure_group_move
    base = AlignmentTransform(calib={}, placement=transform.placement)
    updates = commit_alignment(proj, transform, base)
    assert set(updates) == {1}  # slot 1 -> project sensor 1 via the Z; match;
    #                             sensor 0 is unmoved and therefore skipped
    new_az, new_px = updates[1]
    delta = us95_cal.deltas[1]
    # the azimuth sign: ADD θ°, as sensor_calibration.py recommends
    assert new_az - proj.sensors[1].azimuth_angle == pytest.approx(delta.theta_deg)
    assert new_px != pytest.approx((proj.sensors[1].position_x,
                                    proj.sensors[1].position_y))
    # the corrected device's stream re-reads to ≈identity
    resolved = calibrate(_map_sensor_raw(rec.frames, 1, delta))
    entry = resolved.for_sensor(1)
    assert entry.status == "ok"
    # ≈identity within pairing noise (measured: 0.15°, 0.45 m — the corrected
    # stream matches a different, larger pair set, the plan-§5c honest scope),
    # an order of magnitude under the 0.72°/7.2 m correction it folded in
    assert entry.delta.theta_deg == pytest.approx(0.0, abs=0.4)
    assert math.hypot(entry.delta.d_x, entry.delta.d_y) < 1.0
    # and nothing was mutated by the pure commit
    assert proj.sensors[1].azimuth_angle == 31.84


@needs_us95
def test_group_move_keeps_intersensor_agreement(us95, us95_cal):
    """The compose-order gate on real data: a group move relands every marker
    through the expected world-feet rigid map while cross-sensor distances —
    the thing calibration fixed — stay locked."""
    proj, rec = us95
    tr = build_alignment(proj, rec.zones, us95_cal)
    frame = next(f for f in rec.frames
                 if {p.sensor for p in f.points} >= {0, 1})
    pts = [(p.sensor, p.x_raw_m, p.y_raw_m) for p in frame.points
           if p.sensor in (0, 1)]
    before = [complex(*tr.apply(*p)) for p in pts]
    pivot, ang, dxy = (900.0, 900.0), 4.0, (12.0, -7.0)
    tr2 = AlignmentTransform(
        calib=tr.calib,
        placement=translated(rotated_about(tr.placement, pivot, ang), *dxy))
    after = [complex(*tr2.apply(*p)) for p in pts]
    q = complex(math.cos(math.radians(ang)), math.sin(math.radians(ang)))
    for w, w2 in zip(before, after):
        expect = q * (w - complex(*pivot)) + complex(*pivot) + complex(*dxy)
        assert (w2.real, w2.imag) == pytest.approx((expect.real, expect.imag))
    for i in range(len(before)):
        for j in range(i + 1, len(before)):
            assert abs(after[i] - after[j]) == pytest.approx(
                abs(before[i] - before[j]), abs=1e-9)


@needs_us95
def test_reduction_no_calibration_is_todays_zonefit(us95):
    """Plan §0: with no vehicle-pair calibration the parsed frames and the
    calibrated-refit placement are exactly (==) today's Z; behavior."""
    proj, rec = us95
    assert rec.alignment is not None
    assert rec.alignment.calib == {}
    assert rec.alignment.placement == rec.zone_fit
    # build_alignment with no calibration reuses the identical fit
    tr = build_alignment(proj, rec.zones)
    assert tr.placement == rec.zone_fit
    # frame coordinates are the plain zone-fit similarity, bit-for-bit
    for f in rec.frames[:50]:
        for p in f.points:
            assert (p.x_ft, p.y_ft) == rec.zone_fit.apply_m(p.x_raw_m, p.y_raw_m)


@needs_us95
def test_realign_swaps_the_transform_without_reparsing(us95, us95_cal):
    proj, rec = us95
    tr = build_alignment(proj, rec.zones, us95_cal)
    rec2 = realign(rec, tr)
    assert rec2.alignment is tr
    assert len(rec2.frames) == len(rec.frames)
    f, f2 = rec.frames[10], rec2.frames[10]
    for p, p2 in zip(f.points, f2.points):
        assert (p2.oid, p2.cls, p2.heading) == (p.oid, p.cls, p.heading)
        assert (p2.x_raw_m, p2.y_raw_m) == (p.x_raw_m, p.y_raw_m)
        assert (p2.x_ft, p2.y_ft) == tr.apply(p.sensor, p.x_raw_m, p.y_raw_m)
    # None restores the legacy translation fallback
    rec3 = realign(rec, None)
    p = rec3.frames[10].points[0]
    assert p.x_ft == pytest.approx(
        rec.anchor_ft[0] + units.m_to_ft(p.x_raw_m - rec.ref_m[0]))
    # the input recording is untouched
    assert rec.frames[10].points[0].x_ft == f.points[0].x_ft


def test_live_aligner_external_alignment_overrides():
    """Item 40's live seam: assigning .alignment re-routes feed() through the
    composed transform; clearing it falls back to the auto Z; fit."""
    proj, zones = _make_site()
    la = LiveAligner(proj, sensor_index=0)
    la.feed("C;5.0,5.0", t="09:00:00.000")
    la.feed(_zline(zones))
    assert la.zones  # raw zones retained for the calibrated refit
    delta = RigidDelta.make(2.5, (1.0, -0.5))
    tr = AlignmentTransform(calib={2: delta}, placement=la.zone_fit)
    la.alignment = tr
    x, y = 30.0, 45.0
    frame = la.feed(f"F;0;1;2;3;42,1,{x},{y},0.0")  # oid 42 -> sensor 2
    assert (frame.points[0].x_ft, frame.points[0].y_ft) == pytest.approx(
        tr.apply(2, x, y))
    la.alignment = None
    frame = la.feed(f"F;0;1;2;3;42,1,{x},{y},0.0")
    assert (frame.points[0].x_ft, frame.points[0].y_ft) == pytest.approx(
        la.zone_fit.apply_m(x, y))


@needs_us95
def test_find_pairs_reads_only_raw_meters(us95):
    """Background-blindness: pairs are identical whatever world transform the
    frames were aligned through."""
    _, rec = us95
    scrambled = realign(rec, None)  # different world coords, same raw meters
    a = find_pairs(rec.frames[:400], 1)
    b = find_pairs(scrambled.frames[:400], 1)
    assert a == b
    assert len(a) > 20


# --- autocalibrate: the self-calibrating pre-pass (2026-07-14 round) -------------


def _synthetic_recording(proj, frames) -> Recording:
    """A minimal Recording over synthetic frames: no Z; fit, translation
    anchor — the shape autocalibrate must handle without a zone match."""
    return Recording(sensor_index=0, ref_m=(0.0, 0.0), ref_seen=False,
                     anchor_ft=anchor_world_ft(proj, 0), frames=frames)


def test_autocalibrate_recovers_and_realigns_synthetic():
    """The whole pre-pass on a known misalignment: solve C₁ = mis⁻¹, build
    the composed transform, realign — the two sensors' views of the same
    vehicle coincide afterwards, and the solve report rides along."""
    proj, _ = _make_site()
    mis = RigidDelta.make(2.0, (1.5, -1.0))
    frames = _misaligned_frames(mis, n=250)  # stride-5 solve sees MIN_PAIRS
    rec = _synthetic_recording(proj, frames)
    rec2 = autocalibrate(proj, rec)
    assert rec2 is not rec
    assert set(rec2.alignment.calib) == {1}
    assert rec2.alignment.calibration.for_sensor(1).status == "ok"
    rt = rec2.alignment.calib[1].compose(mis)
    assert rt.theta_deg == pytest.approx(0.0, abs=1e-6)
    assert math.hypot(rt.d_x, rt.d_y) == pytest.approx(0.0, abs=1e-6)
    for f in rec2.frames[::25]:
        p0, p1 = f.points
        assert math.hypot(p0.x_ft - p1.x_ft,
                          p0.y_ft - p1.y_ft) == pytest.approx(0.0, abs=1e-6)
    # the input recording is untouched (realign copies)
    assert rec.frames[0].points[1].x_ft == 0.0


def test_autocalibrate_refusal_keeps_frames_but_reports():
    """Guardrails carry through: too few pairs -> the frames come back
    unchanged and calib stays empty (calibrated remains False downstream),
    but the refused solve is attached so callers can say why."""
    proj, _ = _make_site()
    frames = _misaligned_frames(RigidDelta.make(2.0, (1.5, -1.0)), n=10)
    rec = _synthetic_recording(proj, frames)
    rec2 = autocalibrate(proj, rec)
    assert rec2.frames is rec.frames
    assert not rec2.alignment.calib
    assert rec2.alignment.calibration.for_sensor(1).status == "too_few_pairs"


@needs_us95
def test_autocalibrate_real_recording(us95):
    """On the real two-sensor site: the non-reference sensor solves and the
    frames re-align through the composed transform (raw meters untouched);
    the sparse vendor-combined slots 4/5 are refused, never moved."""
    proj, rec = us95
    rec2 = autocalibrate(proj, rec)
    assert rec2 is not rec
    cal = rec2.alignment.calibration
    trusted = set(rec2.alignment.calib)
    assert trusted and cal.reference not in trusted
    for s in (4, 5):
        entry = cal.for_sensor(s)
        assert entry is not None and entry.flagged
    for p, p2 in zip(rec.frames[10].points, rec2.frames[10].points):
        assert (p2.x_raw_m, p2.y_raw_m) == (p.x_raw_m, p.y_raw_m)
        assert (p2.x_ft, p2.y_ft) == rec2.alignment.apply(
            p.sensor, p.x_raw_m, p.y_raw_m)
