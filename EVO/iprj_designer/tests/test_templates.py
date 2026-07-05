import math
from pathlib import Path

import pytest

from model.geometry import Centerline
from model.templates import (FT_PER_S_PER_MPH, ApproachTemplate, Lane,
                              PlacementContext, TemplateDetector,
                              advance_setback_ft, anchor_lane_line_index,
                              decision_setback_ft, decision_setbacks_ft,
                              default_anchor_lane_line,
                              expand_and_place,
                              expand_and_place_on_centerline,
                              expand_template, lane_config_str,
                              lane_line_offsets_ft, load_template,
                              missing_placeholders, place_detectors,
                              place_detectors_on_centerline,
                              safe_stopping_distance_ft, save_template,
                              seed_detectors, template_from_dict,
                              template_to_dict)

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"


def acceptance_case() -> ApproachTemplate:
    """The Session 6 appendix example re-pinned for Phase 4.1: 45 mph,
    L|T|T|R @ 12', count loops, base output 33 (baked literal), north
    approach (SB traffic), Ph4 thru / Ph7 LT, default 1.0 s extension."""
    return ApproachTemplate(
        name="45 mph north approach",
        speed_mph=45.0,
        lanes=[Lane("L"), Lane("T"), Lane("T"), Lane("R")],
        count_loops=True,
        base_output=33,
        direction="N",
        thru_phase=4,
        lt_phase=7,
    )


def baked(**kwargs) -> ApproachTemplate:
    """A template with every placeholder baked (v1-style literals)."""
    defaults = dict(direction="N", thru_phase=4, lt_phase=7, base_output=1)
    defaults.update(kwargs)
    return ApproachTemplate(**defaults)


def test_defaults_are_placeholders():
    t = ApproachTemplate()
    assert t.lanes == [Lane("T")]
    assert t.count_loops is True
    assert t.extension_time_s == 1.0
    assert t.detectors == []
    # placement-time fields default to "prompt at placement"
    assert (t.direction, t.thru_phase, t.lt_phase, t.base_output) \
        == (None, None, None, None)
    assert t.anchor_lane_line is None


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


def test_template_rejects_nonpositive_extension():
    with pytest.raises(ValueError):
        ApproachTemplate(extension_time_s=0.0)


def test_lane_config_str():
    t = acceptance_case()
    assert lane_config_str(t.lanes) == "12'L | 12'T | 12'T | 12'R"


def test_dict_round_trip():
    t = acceptance_case()
    d = template_to_dict(t)
    assert d["lanes"][0] == {"movement": "L", "width_ft": 12.0, "advance_detector": True}
    assert d["base_output"] == 33
    assert template_from_dict(d) == t


def test_dict_round_trip_with_detectors_and_placeholders():
    t = ApproachTemplate(lanes=[Lane("T"), Lane("T")], detectors=[
        TemplateDetector("stop_bar", [0], 30.0, -5.0, 0, "thru"),
        TemplateDetector("advance", [0, 1], 10.0, 200.0, 4, 9),
    ])
    d = template_to_dict(t)
    assert d["direction"] is None and d["base_output"] is None
    assert d["detectors"][1]["spanning_lanes"] == [0, 1]
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
    assert '"base_output": 33' in text
    assert '"movement": "L"' in text


# ---------------------------------------------------------------------------
# Legacy (schema v1) templates still load
# ---------------------------------------------------------------------------

def test_v1_dict_upgrades():
    d = {
        "schema_version": 1,
        "name": "legacy",
        "speed_mph": 45.0,
        "lanes": [{"movement": "T"}],
        "count_loops": True,
        "starting_input": 33,  # retired alias, ignored
        "starting_output": 33,  # maps onto the Base Output literal
        "direction": "N",
        "thru_phase": 4,
        "lt_phase": 7,
    }
    t = template_from_dict(d)
    assert t.schema_version == 3
    assert t.base_output == 33
    assert (t.direction, t.thru_phase, t.lt_phase) == ("N", 4, 7)
    assert t.detectors == []  # v1 carried no rows -> seeded at expansion
    assert missing_placeholders(t) == []


def test_v1_example_file_loads_and_expands():
    t = load_template(TEMPLATES_DIR / "example_45mph_north.json")
    assert t.base_output == 33
    specs = expand_template(t)
    assert [s.output_number for s in specs] == list(range(33, 45))


def test_dilemma_kind_migrates_to_decision():
    """Old templates that stored the retired "dilemma" kind load as
    "decision" (ROADMAP Item 17)."""
    d = {"lanes": [{"movement": "T"}], "base_output": 1,
         "direction": "N", "thru_phase": 4,
         "detectors": [{"kind": "dilemma", "spanning_lanes": [0],
                        "length_ft": 20.0, "setback_ft": 165.0,
                        "output_offset": 0, "phase": "thru"}]}
    t = template_from_dict(d)
    assert t.detectors[0].kind == "decision"
    # and it expands under the new taxonomy (auto-named "Decision")
    assert expand_template(t)[0].name == "Ph 4 Decision"


def test_explicit_base_output_key_wins_over_starting_output():
    t = template_from_dict({"lanes": [{"movement": "T"}],
                            "base_output": 10, "starting_output": 99})
    assert t.base_output == 10


# ---------------------------------------------------------------------------
# TemplateDetector schema (spanning lanes, phases, offsets)
# ---------------------------------------------------------------------------

def test_detector_rejects_empty_or_noncontiguous_span():
    with pytest.raises(ValueError):
        TemplateDetector("count", [], 5.0, -15.0, 0)
    with pytest.raises(ValueError):
        TemplateDetector("count", [0, 2], 5.0, -15.0, 0)
    with pytest.raises(ValueError):
        TemplateDetector("count", [2, 1], 5.0, -15.0, 0)
    with pytest.raises(ValueError):
        TemplateDetector("count", [-1, 0], 5.0, -15.0, 0)


def test_detector_rejects_bad_length_and_phase():
    with pytest.raises(ValueError):
        TemplateDetector("count", [0], 0.0, -15.0, 0)
    with pytest.raises(ValueError):
        TemplateDetector("count", [0], 5.0, -15.0, 0, phase="left")


def test_template_rejects_span_past_lanes():
    with pytest.raises(ValueError):
        ApproachTemplate(lanes=[Lane("T")], detectors=[
            TemplateDetector("decision", [0, 1], 20.0, 165.0, 0)])


def test_lane_spanning_detector_expands_to_full_width():
    t = baked(lanes=[Lane("T", 12.0), Lane("T", 11.0)], detectors=[
        TemplateDetector("advance", [0, 1], 10.0, 200.0, 0, "thru")])
    (spec,) = expand_template(t)
    assert spec.width_ft == pytest.approx(23.0)
    assert spec.lateral_offset_ft == pytest.approx(0.0)
    assert spec.setback_ft == pytest.approx(200.0)  # stored value, not re-derived


# ---------------------------------------------------------------------------
# Placeholders & PlacementContext
# ---------------------------------------------------------------------------

def test_missing_placeholders_usage_aware():
    # thru-only approach: lt_phase never needed
    t = ApproachTemplate(lanes=[Lane("T")])
    assert missing_placeholders(t) == ["direction", "thru_phase", "base_output"]
    # an L lane brings lt_phase in
    t = ApproachTemplate(lanes=[Lane("L"), Lane("T")])
    assert missing_placeholders(t) \
        == ["direction", "thru_phase", "lt_phase", "base_output"]
    # context fills what the template leaves open
    ctx = PlacementContext(direction="N", thru_phase=4, lt_phase=7, base_output=1)
    assert missing_placeholders(t, ctx) == []
    assert missing_placeholders(acceptance_case()) == []


def test_expand_raises_naming_missing_placeholders():
    t = ApproachTemplate(lanes=[Lane("T")], direction="N")
    with pytest.raises(ValueError, match="thru_phase, base_output"):
        expand_template(t)


def test_expand_resolves_placeholders_from_context():
    t = ApproachTemplate(lanes=[Lane("L"), Lane("T")])
    ctx = PlacementContext(direction="E", thru_phase=2, lt_phase=5, base_output=17)
    specs = expand_template(t, ctx)
    assert specs[0].name == "WBL Count"
    assert specs[0].output_number == 17
    assert [s.phase for s in specs] == [5, 2, 5, 2, 2, 2, 2]


def test_baked_literal_wins_over_context():
    t = acceptance_case()  # direction="N", base_output=33 baked
    specs = expand_template(t, PlacementContext(direction="S", base_output=1))
    assert specs[0].name == "SBL Count"
    assert specs[0].output_number == 33


def test_literal_row_phase_ignores_context_phases():
    t = baked(lanes=[Lane("T")], detectors=[
        TemplateDetector("stop_bar", [0], 30.0, -5.0, 0, phase=6)])
    (spec,) = expand_template(t)
    assert spec.phase == 6
    assert spec.name == "Ph 6 SBT Stop Bar"


# ---------------------------------------------------------------------------
# Anchor lane line (Station 0)
# ---------------------------------------------------------------------------

def test_default_anchor_lane_line():
    # right side of the leading exclusive-LT block
    assert default_anchor_lane_line([Lane("L"), Lane("T"), Lane("T"), Lane("R")]) == 1
    assert default_anchor_lane_line([Lane("L"), Lane("L"), Lane("T")]) == 2
    # no leading exclusive LT lane -> leftmost lane's left edge
    assert default_anchor_lane_line([Lane("T"), Lane("T")]) == 0
    assert default_anchor_lane_line([Lane("LT"), Lane("T")]) == 0  # shared, not exclusive
    assert default_anchor_lane_line([Lane("T"), Lane("L")]) == 0  # not a leading block


def test_anchor_lane_line_override():
    t = acceptance_case()
    assert anchor_lane_line_index(t) == 1
    t.anchor_lane_line = 0
    assert anchor_lane_line_index(t) == 0
    specs = expand_template(t)
    assert [s.lateral_offset_ft for s in specs[:4]] == [0, 12, 24, 36]
    with pytest.raises(ValueError):
        ApproachTemplate(lanes=[Lane("T")], anchor_lane_line=2)


def test_lane_line_offsets():
    assert lane_line_offsets_ft([Lane("L", 12), Lane("T", 11)]) == [0, 12, 23]


# ---------------------------------------------------------------------------
# Kinematics — formulas and the continuous-coverage advance chain
# ---------------------------------------------------------------------------

def test_kinematic_formulas():
    # 45 mph = 66.0 ft/s: SSD = 66*1.0 + 66^2/20 = 283.8; decision = 2.5*66
    assert safe_stopping_distance_ft(45.0) == pytest.approx(283.8)
    assert decision_setback_ft(45.0) == pytest.approx(165.0)
    # 30 mph = 44.0 ft/s: 44 + 44^2/20 = 140.8; 2.5*44 = 110
    assert safe_stopping_distance_ft(30.0) == pytest.approx(140.8)
    assert decision_setback_ft(30.0) == pytest.approx(110.0)
    assert advance_setback_ft(45.0) == safe_stopping_distance_ft(45.0)
    # both grow with speed, and the advance sits beyond the decision detector
    for v in (25.0, 35.0, 45.0, 55.0):
        assert advance_setback_ft(v + 5) > advance_setback_ft(v)
        assert decision_setback_ft(v + 5) > decision_setback_ft(v)
        assert advance_setback_ft(v) > decision_setback_ft(v)


def test_decision_chain_values():
    # 45 mph, 1.0 s: stop-bar decision at 165 (edge 185), advance at 283.8,
    # carry 66 ft. corridor 283.8 - 185 = 98.8 > 66 -> one intermediate, and
    # the two gaps split the 78.8 ft of slack evenly (39.4 each): intermediate
    # downstream edge at 185 + 39.4 = 224.4.
    assert decision_setbacks_ft(45.0, 1.0, 20.0) == [pytest.approx(165.0),
                                                     pytest.approx(224.4)]
    # a 2.0 s extension carries 132 ft > 98.8 -> the single stop-bar decision
    # covers it, no intermediates
    assert decision_setbacks_ft(45.0, 2.0, 20.0) == [pytest.approx(165.0)]
    # 30 mph, 1.0 s: corridor 140.8 - 130 = 10.8 <= 44 -> just the one
    assert decision_setbacks_ft(30.0, 1.0, 20.0) == [pytest.approx(110.0)]
    # a longer decision loop needs more/tighter infill (60 ft: corridor
    # shrinks to 283.8 - 225 = 58.8, still one intermediate here)
    assert decision_setbacks_ft(45.0, 1.0, 60.0)[0] == pytest.approx(165.0)


def test_decision_chain_is_continuous_and_even():
    """No detection gap: every clear gap (between the advance detector, the
    intermediate decisions, and the stop-bar decision) is bridged by the
    extension — and the gaps are all equal (evenly spaced, ROADMAP Item 17)."""
    for mph in (25.0, 30.0, 35.0, 45.0, 55.0, 65.0):
        for ext in (0.5, 1.0, 1.5, 2.0):
            for dlen in (15.0, 20.0, 30.0):
                hold = mph * FT_PER_S_PER_MPH * ext
                # setbacks stop-bar-side first; append the advance on top
                edges = decision_setbacks_ft(mph, ext, dlen) + \
                    [safe_stopping_distance_ft(mph)]
                assert edges[0] == pytest.approx(decision_setback_ft(mph))
                # upstream edge of each decision to downstream edge of the next
                # detector upstream (every decision detector is dlen long)
                gaps = [edges[i + 1] - (edges[i] + dlen)
                        for i in range(len(edges) - 1)]
                for g in gaps:
                    assert g <= hold + 1e-9
                # every gap equal (to within rounding)
                for g in gaps:
                    assert g == pytest.approx(gaps[0], abs=1e-9)


# ---------------------------------------------------------------------------
# Seeding — math fills default rows (which stay editable)
# ---------------------------------------------------------------------------

def test_seed_rows_acceptance():
    rows = seed_detectors(acceptance_case())
    # rows run in ascending distance from the stop bar (ROADMAP Item 15):
    # count, stop bar, the decision chain (stop-bar-side first), then the
    # single advance per thru lane furthest upstream.
    assert [r.kind for r in rows] == ["count"] * 4 + ["stop_bar"] * 4 \
        + ["decision"] * 2 + ["advance"] * 2
    assert [r.output_offset for r in rows] == list(range(12))
    assert [r.phase for r in rows] \
        == ["lt", "thru", "thru", "thru", "lt", "thru", "thru", "thru",
            "thru", "thru", "thru", "thru"]
    # decisions span the two thru lanes; per-lane rows span their own lane
    assert [r.spanning_lanes for r in rows[8:10]] == [[1, 2], [1, 2]]
    assert [r.spanning_lanes for r in rows[:4]] == [[0], [1], [2], [3]]
    # decision chain: stop-bar-side row first, then the evenly-spaced infill
    assert [r.setback_ft for r in rows[8:10]] \
        == [pytest.approx(165.0), pytest.approx(224.4)]
    # a single advance per thru lane, both at the safe stopping distance
    assert [(r.spanning_lanes[0], r.setback_ft) for r in rows[10:]] \
        == [(1, pytest.approx(283.8)), (2, pytest.approx(283.8))]


def test_seed_lengths_from_template():
    """decision_length_ft / advance_length_ft seed the decision and advance
    detector lengths (ROADMAP Item 18)."""
    t = ApproachTemplate(lanes=[Lane("T")], speed_mph=45.0,
                         decision_length_ft=25.0, advance_length_ft=6.0,
                         direction="N", thru_phase=4, base_output=1)
    rows = seed_detectors(t)
    decisions = [r for r in rows if r.kind == "decision"]
    advances = [r for r in rows if r.kind == "advance"]
    assert decisions and all(r.length_ft == 25.0 for r in decisions)
    assert advances and all(r.length_ft == 6.0 for r in advances)
    # the seeded decision length feeds the coverage math too: a much longer
    # loop shrinks the corridor enough that the single stop-bar decision
    # already spans it, so no intermediates are seeded (vs. two at 20 ft)
    long_dec = [r for r in seed_detectors(
        ApproachTemplate(lanes=[Lane("T")], speed_mph=45.0,
                         decision_length_ft=60.0)) if r.kind == "decision"]
    assert len(long_dec) == 1 and len(decisions) == 2


def test_template_rejects_nonpositive_lengths():
    with pytest.raises(ValueError):
        ApproachTemplate(decision_length_ft=0.0)
    with pytest.raises(ValueError):
        ApproachTemplate(advance_length_ft=-1.0)


def test_seed_lengths_round_trip():
    t = ApproachTemplate(lanes=[Lane("T")], decision_length_ft=18.0,
                         advance_length_ft=8.0)
    assert t.schema_version == 3
    assert template_from_dict(template_to_dict(t)) == t


def test_seeded_rows_are_defaults_not_constraints():
    """Storing edited rows fully replaces the computed values — the math
    seeds, the schema governs."""
    t = acceptance_case()
    t.detectors = seed_detectors(t)
    t.detectors[9].setback_ft = 300.0  # user override of a kinematic seed
    t.speed_mph = 60.0  # changing inputs does NOT re-derive stored rows
    specs = expand_template(t)
    assert specs[9].setback_ft == pytest.approx(300.0)
    assert specs[10].setback_ft == pytest.approx(283.8)


def test_expand_seeds_when_detectors_empty():
    t = acceptance_case()
    assert t.detectors == []
    t.detectors = seed_detectors(t)
    assert expand_template(t) == expand_template(acceptance_case())


# ---------------------------------------------------------------------------
# Expansion (acceptance table re-pinned for Phase 4.1: anchor lane line,
# Base Output + offset numbering, continuous-coverage advance chain)
# ---------------------------------------------------------------------------

def test_expand_acceptance_table():
    specs = expand_template(acceptance_case())
    expected = [
        # output, name, length, width, setback, lateral (from anchor line 1)
        (33, "SBL Count", 5, 12, -15, -12),
        (34, "SBT Count 1", 5, 12, -15, 0),
        (35, "SBT Count 2", 5, 12, -15, 12),
        (36, "SBR Count", 5, 12, -15, 24),
        (37, "Ph 7 SBL Stop Bar", 30, 12, -5, -12),
        (38, "Ph 4 SBT Stop Bar 1", 30, 12, -5, 0),
        (39, "Ph 4 SBT Stop Bar 2", 30, 12, -5, 12),
        (40, "Ph 4 SBR Stop Bar", 30, 12, -5, 24),
        (41, "Ph 4 Decision 1", 20, 24, 165.0, 0),
        (42, "Ph 4 Decision 2", 20, 24, 224.4, 0),
        (43, "Ph 4 Advance 1", 10, 12, 283.8, 0),
        (44, "Ph 4 Advance 2", 10, 12, 283.8, 12),
    ]
    assert [(s.output_number, s.name, s.length_ft, s.width_ft) for s in specs] \
        == [(i, n, l, w) for i, n, l, w, _, _ in expected]
    for spec, (_, _, _, _, setback, lateral) in zip(specs, expected):
        assert spec.setback_ft == pytest.approx(setback)
        assert spec.lateral_offset_ft == pytest.approx(lateral)
    # outputs run from the base in offset lockstep
    assert [s.output_number for s in specs] == list(range(33, 45))
    # phases: L lanes on the LT phase, everything else on the thru phase
    assert [s.phase for s in specs] == [7, 4, 4, 4, 7, 4, 4, 4, 4, 4, 4, 4]
    assert [s.kind for s in specs] == ["count"] * 4 + ["stop_bar"] * 4 \
        + ["decision"] * 2 + ["advance"] * 2


def test_output_offset_gaps_carry_through():
    t = baked(lanes=[Lane("T")], base_output=32, detectors=[
        TemplateDetector("stop_bar", [0], 30.0, -5.0, 0, "thru"),
        TemplateDetector("advance", [0], 10.0, 283.8, 5, "thru")])
    assert [s.output_number for s in expand_template(t)] == [32, 37]


def test_expand_without_count_loops_shifts_outputs():
    t = acceptance_case()
    t.count_loops = False
    specs = expand_template(t)
    assert specs[0].name == "Ph 7 SBL Stop Bar"
    assert specs[0].output_number == 33
    assert len(specs) == 8  # 4 stop bar + 2 decision + 2 advance


def test_expand_single_thru_lane_names():
    t = baked(lanes=[Lane("T")])
    names = [s.name for s in expand_template(t)]
    # two decisions at 45 mph / 1.0 s -> numbered; single advance and the
    # rest are unique -> bare
    assert names == ["SBT Count", "Ph 4 SBT Stop Bar", "Ph 4 Decision 1",
                     "Ph 4 Decision 2", "Ph 4 Advance"]


def test_expand_direction_prefixes():
    for direction, prefix in (("N", "SB"), ("S", "NB"), ("E", "WB"), ("W", "EB")):
        t = baked(lanes=[Lane("T")], direction=direction)
        assert expand_template(t)[0].name == f"{prefix}T Count"


def test_expand_turn_lanes_get_no_advance_or_decision():
    # advance_detector toggles on turn-only lanes are ignored
    t = baked(lanes=[Lane("L"), Lane("R")])
    kinds = [s.kind for s in expand_template(t)]
    assert kinds == ["count", "count", "stop_bar", "stop_bar"]


def test_expand_advance_toggle_per_lane():
    t = baked(lanes=[Lane("T", advance_detector=False), Lane("T")])
    specs = expand_template(t)
    advances = [s for s in specs if s.kind == "advance"]
    # the toggled-off lane gets no advance; only the enabled lane's single
    # advance survives, at the safe stopping distance
    assert [a.lateral_offset_ft for a in advances] == [12]
    assert [a.setback_ft for a in advances] == [pytest.approx(283.8)]
    # decision detectors span both thru lanes regardless of the toggle
    decisions = [s for s in specs if s.kind == "decision"]
    assert all(d.width_ft == pytest.approx(24.0) for d in decisions)


# ---------------------------------------------------------------------------
# Straight placement
# ---------------------------------------------------------------------------

def test_place_north_approach_y_down():
    # North approach, SB traffic moving down-screen (+y): upstream is (0,-1)
    # and the driver's right is west (-x). The ref is the anchor point —
    # where the stop bar crosses the LT/thru lane line — so the SBL lanes
    # sit at negative lateral offsets (east of it, +x).
    t = acceptance_case()
    placed = expand_and_place(t, stop_bar_ref=(100.0, 200.0), upstream_dir=(0.0, -1.0))
    # SBL count loop: laterally -12..0 ft (x 112 -> 100), longitudinally
    # -15..-10 ft (past the bar, y 215 -> 210)
    assert placed[0].points == [(112, 215), (100, 215), (100, 210), (112, 210)]
    # Advance 1 sits in the first thru lane (lateral 0..12 -> x 100 -> 88),
    # leading edge 283.8 ft upstream
    adv = placed[10]
    assert adv.spec.name == "Ph 4 Advance 1"
    assert adv.points[0] == (pytest.approx(100), pytest.approx(200 - 283.8))
    assert adv.points[2] == (pytest.approx(88), pytest.approx(200 - 293.8))


def test_place_east_approach_y_down():
    # East approach, WB traffic (-x travel): upstream is (1,0) and the
    # driver's right is north (-y on screen). Single thru lane -> anchor 0.
    t = baked(lanes=[Lane("T")], direction="E")
    placed = expand_and_place(t, stop_bar_ref=(0.0, 0.0), upstream_dir=(1.0, 0.0))
    assert placed[0].points == [(-15, 0), (-15, -12), (-10, -12), (-10, 0)]


def test_place_units_per_ft_scales():
    t = baked(lanes=[Lane("T")])
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


def test_expand_and_place_accepts_context():
    t = ApproachTemplate(lanes=[Lane("T")])
    ctx = PlacementContext(direction="N", thru_phase=4, base_output=8)
    placed = expand_and_place(t, (0.0, 0.0), (0.0, -1.0), context=ctx)
    assert placed[0].spec.output_number == 8


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
    """A 90° bend 200 units upstream of the stop bar: at 45 mph the first
    advance loop (283.8 ft setback) lands on the second leg, rotated to
    follow it, while detectors near the stop bar match straight placement."""
    t = baked(lanes=[Lane("T")], speed_mph=45.0)
    cl = [(0.0, 0.0), (0.0, -200.0), (-300.0, -200.0)]
    placed = place_detectors_on_centerline(expand_template(t), cl, (0.0, 0.0))
    by_kind: dict = {}
    for p in placed:
        by_kind.setdefault(p.spec.kind, p)  # first advance = upstream-most
    # count loop straddles station -15..-10 on the first (straight-up) leg;
    # SB traffic's right is -x, so lateral 0..12 ft runs x 0 -> -12
    assert by_kind["count"].points == [(0, 15), (-12, 15), (-12, 10), (0, 10)]
    # first advance loop: stations 283.8..293.8 sit on the westbound second
    # leg (x = 200 - station); driver's right there is +y (y = -200 + lateral)
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
