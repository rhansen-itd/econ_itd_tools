"""Zone-based alignment tests (the overlay-rotation fix).

Unit tests build a synthetic project whose EVO-frame zones are generated
from the map zones through a known similarity, so the fit must recover the
exact parameters. Integration tests pin the two real site pairs the
investigation was run on (OVERLAY_ROTATION_INVESTIGATION.md): Banks, which
is rotated ≈ −34° and was the broken site, and US95&SH8, which needs ≈
identity and must stay correct.
"""

import cmath
import math
from pathlib import Path

import pytest

from model import units, zonefit
from model.iprj_io import Background, EventZone, IgnoreZone, Project, Sensor, load_iprj
from model.replay import LiveAligner, load_recording, parse_recording
from model.zonefit import RawZone, ZoneFit, fit, match_slots, parse_zline

SITES = Path(__file__).resolve().parents[3] / "sites"
BANKS_REC = SITES / "Banks" / "10_37_23_201_EVO_1783582697.txt"
US95_REC = SITES / "86_US95&SH8" / "10_37_2_86_EVO_1770311735.txt"


# --- synthetic site: map zones + a known EVO->world similarity ---------------

MPP = 0.1  # meter per world pixel
ROT = math.radians(-30.0)
SCALE = 0.95
A = SCALE * cmath.exp(1j * ROT)  # world_ft = A * evo_ft + T
T = complex(100.0, 200.0)


def _evo_m(px_pt: tuple[float, float]) -> tuple[float, float]:
    """Invert the known similarity: world px -> EVO meters."""
    w = complex(units.px_to_ft(px_pt[0], MPP), units.px_to_ft(px_pt[1], MPP))
    e = (w - T) / A
    return units.ft_to_m(e.real), units.ft_to_m(e.imag)


def _quad(cx: float, cy: float, half: float = 30.0) -> list[tuple[float, float]]:
    return [(cx - half, cy - half), (cx + half, cy - half),
            (cx + half, cy + half), (cx - half, cy + half)]


def _make_site() -> tuple[Project, list[RawZone]]:
    """Two sensors; sensor 0 ends up stream slot 0, sensor 1 slot 2 (a gap,
    like Banks' absent slot 2), with distinct signatures. Returns the project
    and the RawZones exactly as a Z; line would carry them."""
    s0 = Sensor(
        position_x=500.0, position_y=500.0,
        event_zones=[
            EventZone(phase_number=6, output_number=33, points=_quad(400, 300)),
            EventZone(phase_number=2, output_number=40, points=_quad(900, 350)),
        ],
        ignore_zones=[IgnoreZone(points=_quad(1200, 900, half=100.0))],
    )
    s1 = Sensor(
        position_x=800.0, position_y=800.0,
        event_zones=[
            EventZone(phase_number=4, output_number=41, points=_quad(300, 1100)),
            EventZone(phase_number=8, output_number=0, points=_quad(1000, 1300)),
            EventZone(phase_number=0, output_number=0, points=_quad(600, 700)),
        ],
    )
    proj = Project(background=Background(meter_per_pixel=MPP), sensors=[s0, s1])

    zones = []
    for slot, sensor in ((0, s0), (2, s1)):
        for z in sensor.event_zones:
            zones.append(RawZone(
                slot, False, z.phase_number, z.output_number,
                tuple(_evo_m(p) for p in z.points)))
        for z in sensor.ignore_zones:
            zones.append(RawZone(
                slot, True, 0, 0, tuple(_evo_m(p) for p in z.points)))
    return proj, zones


def _zline(zones: list[RawZone]) -> str:
    chunks = []
    for z in zones:
        coords = ",".join(f"{c:.6f}" for pt in z.points_m for c in pt)
        chunks.append(f"{z.slot},{int(z.is_ignore)},{z.phase},{z.output},{coords}")
    return "Z;" + ";".join(chunks)


# --- Z; grammar ---------------------------------------------------------------

def test_parse_zline_roundtrip():
    _, zones = _make_site()
    parsed = parse_zline(_zline(zones))
    assert len(parsed) == len(zones)
    for p, z in zip(parsed, zones):
        assert (p.slot, p.is_ignore, p.phase, p.output) == (
            z.slot, z.is_ignore, z.phase, z.output)
        for pp, zp in zip(p.points_m, z.points_m):
            assert pp == pytest.approx(zp)


def test_parse_zline_rejects_non_z_and_malformed():
    assert parse_zline("C;1.0,2.0") == []
    assert parse_zline("Z;0,0,1") == []                       # header only
    assert parse_zline("Z;0,0,1,2,1.0,2.0,3.0,4.0") == []     # 2 vertices
    assert parse_zline("Z;0,0,1,2,1.0,2.0,3.0,4.0,5.0") == []  # odd coords
    # one malformed zone invalidates the whole line (no partial fits)
    good = "0,0,1,2,0.0,0.0,10.0,0.0,10.0,10.0"
    assert parse_zline(f"Z;{good};0,0,x,2,0.0,0.0,10.0,0.0,10.0,10.0") == []


# --- signature slot matching ---------------------------------------------------

def test_match_slots_by_signature():
    proj, zones = _make_site()
    assert match_slots(proj, zones) == {0: 0, 2: 1}


def test_match_slots_subset_project():
    """A project holding only one of the streamed sensors (Banks' split
    banks_3_4.iprj situation) still matches its sensor to the right slot."""
    proj, zones = _make_site()
    solo = Project(background=proj.background, sensors=[proj.sensors[1]])
    assert match_slots(solo, zones) == {2: 0}


def test_match_slots_drops_ambiguous_signatures():
    proj, zones = _make_site()
    # duplicate sensor 0 -> its signature is no longer unique on the project
    twin = Project(background=proj.background,
                   sensors=[proj.sensors[0], proj.sensors[0]])
    assert match_slots(twin, zones) == {}


# --- the similarity fit ---------------------------------------------------------

def test_fit_recovers_exact_similarity():
    proj, zones = _make_site()
    zf = fit(proj, zones)
    assert zf is not None
    assert zf.rotation_deg == pytest.approx(math.degrees(ROT), abs=1e-9)
    assert zf.scale == pytest.approx(SCALE, abs=1e-12)
    assert zf.mean_residual_ft == pytest.approx(0.0, abs=1e-9)
    assert zf.n_zones == 6
    assert zf.slot_to_sensor == ((0, 0), (2, 1))
    # apply_m maps an EVO point onto its known world image
    ex, ey = _evo_m((400.0, 300.0))
    wx, wy = zf.apply_m(ex, ey)
    assert wx == pytest.approx(units.px_to_ft(400.0, MPP), abs=1e-9)
    assert wy == pytest.approx(units.px_to_ft(300.0, MPP), abs=1e-9)


def test_fit_falls_back_on_too_few_zones():
    proj, zones = _make_site()
    slot0_only = [z for z in zones if z.slot == 0][:2]
    solo = Project(background=proj.background, sensors=[Sensor(
        position_x=1.0, position_y=1.0,
        event_zones=proj.sensors[0].event_zones[:2])])
    assert fit(solo, slot0_only) is None


def test_fit_falls_back_on_small_spread():
    """Zones clustered tighter than MIN_SPREAD_FT can't pin rotation (the
    H3 short-baseline lesson) -> no fit."""
    tight = Sensor(position_x=1.0, position_y=1.0, event_zones=[
        EventZone(phase_number=p, output_number=p, points=_quad(500 + 10 * p, 500, half=4.0))
        for p in (1, 2, 3)])
    proj = Project(background=Background(meter_per_pixel=MPP), sensors=[tight])
    zones = [RawZone(0, False, z.phase_number, z.output_number,
                     tuple(_evo_m(p) for p in z.points))
             for z in tight.event_zones]
    assert fit(proj, zones) is None


def test_fit_falls_back_on_bad_residual():
    """Matching signatures but non-similar geometry (wrong site / stale
    file) -> residual gate trips, translation fallback keeps working."""
    proj, zones = _make_site()
    # keep signatures, but shove each zone a different, non-similar way:
    # no single rotation+scale+translation can absorb per-zone scatter
    offsets = [(0.0, 0.0), (400.0, -50.0), (-250.0, 500.0)]
    scrambled = [
        RawZone(z.slot, z.is_ignore, z.phase, z.output,
                tuple((x + offsets[j][0], y + offsets[j][1])
                      for x, y in z.points_m))
        for j, z in enumerate(z for z in zones if z.slot == 0)]
    solo = Project(background=proj.background, sensors=[proj.sensors[0]])
    assert fit(solo, scrambled) is None


# --- replay + live wiring -------------------------------------------------------

def _recording_text(zones: list[RawZone], evo_pt: tuple[float, float]) -> str:
    return (
        "09:00:00.000\n"
        "C;5.0,5.0,0.9\n"
        f"{_zline(zones)}\n"
        "09:00:00.100\n"
        f"F;0;1;2;3;42,1,{evo_pt[0]},{evo_pt[1]},0.0\n"
    )


def test_parse_recording_applies_zone_fit():
    proj, zones = _make_site()
    ex, ey = _evo_m((900.0, 350.0))  # a known map location, via the similarity
    rec = parse_recording(proj, _recording_text(zones, (ex, ey)), sensor_index=0)
    assert rec.zone_fit is not None
    assert rec.zone_fit.rotation_deg == pytest.approx(math.degrees(ROT), abs=1e-6)
    p = rec.frames[0].points[0]
    assert p.x_ft == pytest.approx(units.px_to_ft(900.0, MPP), abs=1e-6)
    assert p.y_ft == pytest.approx(units.px_to_ft(350.0, MPP), abs=1e-6)
    # raw meters preserved for hover/debug regardless of transform
    assert (p.x_raw_m, p.y_raw_m) == pytest.approx((ex, ey))


def test_parse_recording_without_z_keeps_translation():
    proj, zones = _make_site()
    text = "09:00:00.000\nC;5.0,5.0\n09:00:00.100\nF;0;1;2;3;42,1,6.0,7.0,0.0\n"
    rec = parse_recording(proj, text, sensor_index=0)
    assert rec.zone_fit is None
    p = rec.frames[0].points[0]
    assert p.x_ft - rec.anchor_ft[0] == pytest.approx(units.m_to_ft(1.0), abs=1e-9)
    assert p.y_ft - rec.anchor_ft[1] == pytest.approx(units.m_to_ft(2.0), abs=1e-9)


def test_live_aligner_switches_on_z_line():
    proj, zones = _make_site()
    ex, ey = _evo_m((900.0, 350.0))
    la = LiveAligner(proj, sensor_index=0)
    la.feed("C;5.0,5.0", t="09:00:00.000")

    before = la.feed(f"F;0;1;2;3;42,1,{ex},{ey},0.0")
    assert la.zone_fit is None  # no Z; yet -> translation
    assert before.points[0].x_ft == pytest.approx(
        la.anchor_ft[0] + units.m_to_ft(ex - 5.0), abs=1e-9)

    assert la.feed(_zline(zones)) is None  # config line, no frame emitted
    assert la.zone_fit is not None

    after = la.feed(f"F;0;1;2;3;42,1,{ex},{ey},0.0")
    assert after.points[0].x_ft == pytest.approx(units.px_to_ft(900.0, MPP), abs=1e-6)
    assert after.points[0].y_ft == pytest.approx(units.px_to_ft(350.0, MPP), abs=1e-6)


# --- real-site integration (read-only fixtures) ---------------------------------

@pytest.mark.skipif(not BANKS_REC.is_file() or
                    not (SITES / "Banks" / "banks_1_2.iprj").is_file(),
                    reason="Banks fixtures not present")
def test_banks_1_2_rotation_recovered():
    """The broken site: the fit must find the ≈ −34° rotation the manual
    long-baseline calibration established, with residuals at map hand-
    placement accuracy (investigation §4: manual estimate −33.7°)."""
    proj = load_iprj(SITES / "Banks" / "banks_1_2.iprj")
    rec = load_recording(proj, BANKS_REC)
    zf = rec.zone_fit
    assert zf is not None
    assert dict(zf.slot_to_sensor) == {0: 0, 1: 1}
    assert zf.n_zones == 30
    assert -36.0 < zf.rotation_deg < -33.0
    assert zf.mean_residual_ft < 10.0


@pytest.mark.skipif(not BANKS_REC.is_file() or
                    not (SITES / "Banks" / "banks_3_4.iprj").is_file(),
                    reason="Banks fixtures not present")
def test_banks_3_4_identifies_slot_3_exactly():
    """The split project holding only stream slot 3's sensor: signature
    matching must identify it (not slot 0), and the per-sensor fit is exact
    — the vendor generated one side from the other (investigation §2b)."""
    proj = load_iprj(SITES / "Banks" / "banks_3_4.iprj")
    rec = load_recording(proj, BANKS_REC)
    zf = rec.zone_fit
    assert zf is not None
    assert dict(zf.slot_to_sensor) == {3: 0}
    assert zf.max_residual_ft < 0.1
    # the vendor's convention is pure rotation at the STORED MeterPerPixel;
    # our scale is exactly effective/stored (the §1a rounding recovered)
    stored = proj.background.meter_per_pixel
    emp = units.effective_meter_per_pixel(proj.background)
    assert zf.scale == pytest.approx(emp / stored, abs=1e-4)


@pytest.mark.skipif(not US95_REC.is_file(),
                    reason="US95 recording not present")
def test_us95_stays_near_identity():
    """The previously-correct site: the fit must be ≈ identity so the fix
    cannot regress it (what killed the reverted H3 attempt)."""
    proj = load_iprj(SITES / "86_US95&SH8" / "us95&sh8.iprj")
    rec = load_recording(proj, US95_REC)
    zf = rec.zone_fit
    assert zf is not None
    assert abs(zf.rotation_deg) < 3.0
    assert zf.scale == pytest.approx(1.0, abs=0.05)
    assert zf.mean_residual_ft < 10.0
