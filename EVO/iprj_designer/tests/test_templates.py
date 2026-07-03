import math

import pytest

from model.geometry import Centerline
from model.templates import (ApproachTemplate, Lane, advance_setback_ft,
                              dilemma_setback_ft, expand_and_place,
                              expand_and_place_on_centerline,
                              expand_template, lane_config_str, load_template,
                              place_detectors, place_detectors_on_centerline,
                              safe_stopping_distance_ft,
                              save_template, template_from_dict,
                              template_to_dict)


def acceptance_case() -> ApproachTemplate:
    """The Session 6 appendix example: 45 mph, L|T|T|R @ 12', count loops,
    starting output 33, north approach (SB traffic), Ph4 thru / Ph7 LT."""
    return ApproachTemplate(
        name="45 mph north approach",
        speed_mph=45.0,
        lanes=[Lane("L"), Lane("T"), Lane("T"), Lane("R")],
        count_loops=True,
        starting_output=33,
        direction="N",
        thru_phase=4,
        lt_phase=7,
    )


def test_defaults():
    t = ApproachTemplate()
    assert t.lanes == [Lane("T")]
    assert t.direction == "N"
    assert t.count_loops is True


def test_lane_rejects_bad_movement():
    with pytest.raises(ValueError):
        Lane("X")
    with pytest.raises(ValueError):
        Lane("")


def test_lane_accepts_combined_movements():
    assert Lane("tr").movement == "TR"  # normalized upper-case


def test_template_rejects_bad_direction():
    with pytest.raises(ValueError):
        ApproachTemplate(direction="NE")


def test_template_requires_a_lane():
    with pytest.raises(ValueError):
        ApproachTemplate(lanes=[])


def test_lane_config_str():
    t = acceptance_case()
    assert lane_config_str(t.lanes) == "12'L | 12'T | 12'T | 12'R"


def test_dict_round_trip():
    t = acceptance_case()
    d = template_to_dict(t)
    assert d["lanes"][0] == {"movement": "L", "width_ft": 12.0, "advance_detector": True}
    assert template_from_dict(d) == t


def test_json_round_trip(tmp_path):
    t = acceptance_case()
    path = tmp_path / "sub" / "45mph_north.json"
    save_template(t, path)  # parent dir is created
    assert load_template(path) == t


def test_json_is_human_editable(tmp_path):
    path = tmp_path / "t.json"
    save_template(acceptance_case(), path)
    text = path.read_text()
    assert '"starting_output": 33' in text
    assert '"movement": "L"' in text


# ---------------------------------------------------------------------------
# Session 6.2 — expansion
# ---------------------------------------------------------------------------

def test_kinematic_formulas():
    # 45 mph = 66.0 ft/s: SSD = 66*1.0 + 66^2/20 = 283.8; dilemma = 2.5*66
    assert safe_stopping_distance_ft(45.0) == pytest.approx(283.8)
    assert dilemma_setback_ft(45.0) == pytest.approx(165.0)
    # 30 mph = 44.0 ft/s: 44 + 44^2/20 = 140.8; 2.5*44 = 110
    assert safe_stopping_distance_ft(30.0) == pytest.approx(140.8)
    assert dilemma_setback_ft(30.0) == pytest.approx(110.0)
    assert advance_setback_ft(45.0) == safe_stopping_distance_ft(45.0)
    # both grow with speed, and advances sit beyond the dilemma detector
    for v in (25.0, 35.0, 45.0, 55.0):
        assert advance_setback_ft(v + 5) > advance_setback_ft(v)
        assert dilemma_setback_ft(v + 5) > dilemma_setback_ft(v)
        assert advance_setback_ft(v) > dilemma_setback_ft(v)


def test_expand_acceptance_table():
    """The ROADMAP appendix table (dilemma/advance distances per the
    documented ITE formulas — the table's ~100/~200 were placeholders)."""
    specs = expand_template(acceptance_case())
    expected = [
        # output, name, length, width, setback
        (33, "SBL Count", 5, 12, -15),
        (34, "SBT Count 1", 5, 12, -15),
        (35, "SBT Count 2", 5, 12, -15),
        (36, "SBR Count", 5, 12, -15),
        (37, "Ph 7 SBL Stop Bar", 30, 12, -5),
        (38, "Ph 4 SBT Stop Bar 1", 30, 12, -5),
        (39, "Ph 4 SBT Stop Bar 2", 30, 12, -5),
        (40, "Ph 4 SBR Stop Bar", 30, 12, -5),
        (41, "Ph 4 Dilemma", 20, 24, 165.0),
        (42, "Ph 4 Advance 1", 10, 12, 283.8),
        (43, "Ph 4 Advance 2", 10, 12, 283.8),
    ]
    assert [(s.output_number, s.name, s.length_ft, s.width_ft) for s in specs] \
        == [(i, n, l, w) for i, n, l, w, _ in expected]
    for spec, (_, _, _, _, setback) in zip(specs, expected):
        assert spec.setback_ft == pytest.approx(setback)
    # outputs run in lockstep from starting_output
    assert [s.output_number for s in specs] == list(range(33, 44))
    # phases: L lanes on the LT phase, everything else on the thru phase
    assert [s.phase for s in specs] == [7, 4, 4, 4, 7, 4, 4, 4, 4, 4, 4]
    # lateral layout: lanes left to right; dilemma spans the two thru lanes
    assert [s.lateral_offset_ft for s in specs[:4]] == [0, 12, 24, 36]
    assert specs[8].lateral_offset_ft == 12
    assert [s.kind for s in specs] == ["count"] * 4 + ["stop_bar"] * 4 \
        + ["dilemma"] + ["advance"] * 2


def test_expand_without_count_loops_shifts_outputs():
    t = acceptance_case()
    t.count_loops = False
    specs = expand_template(t)
    assert specs[0].name == "Ph 7 SBL Stop Bar"
    assert specs[0].output_number == 33
    assert len(specs) == 7


def test_expand_single_thru_lane_names_unnumbered():
    t = ApproachTemplate(lanes=[Lane("T")])
    names = [s.name for s in expand_template(t)]
    assert names == ["SBT Count", "Ph 4 SBT Stop Bar", "Ph 4 Dilemma",
                     "Ph 4 Advance"]


def test_expand_direction_prefixes():
    for direction, prefix in (("N", "SB"), ("S", "NB"), ("E", "WB"), ("W", "EB")):
        t = ApproachTemplate(lanes=[Lane("T")], direction=direction)
        assert expand_template(t)[0].name == f"{prefix}T Count"


def test_expand_turn_lanes_get_no_advance_or_dilemma():
    # advance_detector toggles on turn-only lanes are ignored
    t = ApproachTemplate(lanes=[Lane("L"), Lane("R")])
    kinds = [s.kind for s in expand_template(t)]
    assert kinds == ["count", "count", "stop_bar", "stop_bar"]


def test_expand_advance_toggle_per_lane():
    t = ApproachTemplate(lanes=[Lane("T", advance_detector=False), Lane("T")])
    advances = [s for s in expand_template(t) if s.kind == "advance"]
    assert len(advances) == 1
    assert advances[0].name == "Ph 4 Advance"  # only one -> unnumbered
    assert advances[0].lateral_offset_ft == 12  # the second lane


def test_place_north_approach_y_down():
    # North approach, SB traffic moving down-screen (+y): upstream is (0,-1)
    # and the driver's right is west (-x).
    t = acceptance_case()
    placed = expand_and_place(t, stop_bar_ref=(100.0, 200.0), upstream_dir=(0.0, -1.0))
    # SBL count loop: laterally 0..12 ft right (x 100 -> 88), longitudinally
    # -15..-10 ft (past the bar, y 215 -> 210)
    assert placed[0].points == [(100, 215), (88, 215), (88, 210), (100, 210)]
    # Advance 1 sits in the first thru lane, leading edge 283.8 ft upstream
    adv = placed[9]
    assert adv.spec.name == "Ph 4 Advance 1"
    assert adv.points[0] == (pytest.approx(88), pytest.approx(200 - 283.8))
    assert adv.points[2] == (pytest.approx(76), pytest.approx(200 - 293.8))


def test_place_east_approach_y_down():
    # East approach, WB traffic (-x travel): upstream is (1,0) and the
    # driver's right is north (-y on screen).
    t = ApproachTemplate(lanes=[Lane("T")], direction="E")
    placed = expand_and_place(t, stop_bar_ref=(0.0, 0.0), upstream_dir=(1.0, 0.0))
    assert placed[0].points == [(-15, 0), (-15, -12), (-10, -12), (-10, 0)]


def test_place_units_per_ft_scales():
    t = ApproachTemplate(lanes=[Lane("T")])
    ft = expand_and_place(t, (0.0, 0.0), (0.0, -1.0))
    px = expand_and_place(t, (0.0, 0.0), (0.0, -1.0), units_per_ft=2.0)
    for a, b in zip(ft, px):
        for (ax, ay), (bx, by) in zip(a.points, b.points):
            assert (bx, by) == (pytest.approx(2 * ax), pytest.approx(2 * ay))


def test_place_diagonal_direction_preserves_dimensions():
    t = acceptance_case()
    placed = expand_and_place(t, (50.0, 50.0), (3.0, -4.0))  # normalized inside
    for p in placed:
        a, b, c, d = p.points
        assert math.dist(a, b) == pytest.approx(p.spec.width_ft)
        assert math.dist(b, c) == pytest.approx(p.spec.length_ft)
        assert math.dist(c, d) == pytest.approx(p.spec.width_ft)
        assert math.dist(d, a) == pytest.approx(p.spec.length_ft)
        # right angle at b
        dot = (a[0] - b[0]) * (c[0] - b[0]) + (a[1] - b[1]) * (c[1] - b[1])
        assert dot == pytest.approx(0.0, abs=1e-9)


def test_place_rejects_zero_direction():
    with pytest.raises(ValueError):
        place_detectors(expand_template(acceptance_case()), (0.0, 0.0), (0.0, 0.0))


def test_expand_and_place_matches_expand():
    t = acceptance_case()
    specs = expand_template(t)
    placed = expand_and_place(t, (0.0, 0.0), (0.0, -1.0))
    assert [p.spec for p in placed] == specs


# -- curvilinear placement (Session 7.5) --------------------------------------

def test_curvilinear_straight_datum_matches_straight_placement():
    """On a straight centerline the curvilinear form reproduces
    place_detectors exactly — including a ref clicked off the datum, a
    diagonal direction, and unit scaling."""
    t = acceptance_case()
    cases = [
        # centerline (stop bar first, upstream), ref, upstream dir, units/ft
        ([(100.0, 200.0), (100.0, -400.0)], (100.0, 200.0), (0.0, -1.0), 1.0),
        ([(100.0, 200.0), (100.0, -400.0)], (88.0, 200.0), (0.0, -1.0), 1.0),
        ([(50.0, 50.0), (650.0, -750.0)], (50.0, 50.0), (3.0, -4.0), 2.0),
    ]
    for cl, ref, upstream, upf in cases:
        straight = expand_and_place(t, ref, upstream, upf)
        curvy = expand_and_place_on_centerline(t, cl, ref, upf)
        for a, b in zip(straight, curvy):
            assert b.spec == a.spec
            for (ax, ay), (bx, by) in zip(a.points, b.points):
                assert bx == pytest.approx(ax, abs=1e-9)
                assert by == pytest.approx(ay, abs=1e-9)


def test_curvilinear_advance_follows_bend():
    """A 90° bend 200 units upstream of the stop bar: at 45 mph the advance
    loop (283.8 ft setback) lands on the second leg, rotated to follow it,
    while detectors near the stop bar match straight placement."""
    t = ApproachTemplate(lanes=[Lane("T")], speed_mph=45.0)
    cl = [(0.0, 0.0), (0.0, -200.0), (-300.0, -200.0)]
    placed = place_detectors_on_centerline(expand_template(t), cl, (0.0, 0.0))
    by_kind = {p.spec.kind: p for p in placed}
    # count loop straddles station -15..-10 on the first (straight-up) leg;
    # SB traffic's right is -x, so lateral 0..12 ft runs x 0 -> -12
    assert by_kind["count"].points == [(0, 15), (-12, 15), (-12, 10), (0, 10)]
    # advance loop: stations 283.8..293.8 sit on the westbound second leg
    # (x = 200 - station); driver's right there is +y (y = -200 + lateral)
    expected = [(-83.8, -200.0), (-83.8, -188.0), (-93.8, -188.0), (-93.8, -200.0)]
    for (x, y), (ex, ey) in zip(by_kind["advance"].points, expected):
        assert x == pytest.approx(ex)
        assert y == pytest.approx(ey)


def test_curvilinear_corners_so_relocate_points():
    """corners_so is the attachment record: locating each stored
    (station, offset) on the datum reproduces the placed points."""
    t = acceptance_case()
    cl = [(0.0, 0.0), (0.0, -200.0), (-300.0, -200.0)]
    placed = expand_and_place_on_centerline(t, cl, (5.0, 2.0), 1.5)
    datum = Centerline(cl)
    for det in placed:
        assert det.corners_so is not None and len(det.corners_so) == 4
        for (s, off), (x, y) in zip(det.corners_so, det.points):
            px, py = datum.point_at(s, off)
            assert px == pytest.approx(x, abs=1e-9)
            assert py == pytest.approx(y, abs=1e-9)


def test_straight_placement_carries_no_corners_so():
    placed = expand_and_place(acceptance_case(), (0.0, 0.0), (0.0, -1.0))
    assert all(det.corners_so is None for det in placed)
