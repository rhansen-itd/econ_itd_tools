"""Session 7.3: centerlines <-> Lineal persistence round-trip."""

import random

from model import (
    Lineal,
    Project,
    centerline_to_lineals,
    lineals_to_centerlines,
    load_centerlines,
    load_iprj,
    save_centerlines,
    save_iprj,
)

# A 4-point centerline: stop bar at (1000, 2400), heading upstream with a
# bend. Values are 2-decimal-exact so file round trips compare equal.
POINTS = [(1000.0, 2400.0), (1000.0, 2000.0), (1050.5, 1500.25), (1100.0, 1000.0)]

# The crossing road's centerline — its segments cross POINTS' mid-segment
# but share no endpoint with it, as intersecting roads normally do.
CROSS = [(400.0, 1900.0), (900.0, 1850.5), (1400.0, 1800.0), (1900.0, 1750.0)]


def placeholder() -> Lineal:
    """A vendor-file placeholder slot (Enable=0, zeroed points)."""
    return Lineal(enable=0, point_0=(0.0, 0.0), point_1=(0.0, 0.0))


# ---------------------------------------------------------------------------
# Save: points -> Lineals
# ---------------------------------------------------------------------------

def test_one_lineal_per_segment():
    lineals = centerline_to_lineals(POINTS)
    assert len(lineals) == len(POINTS) - 1
    for i, l in enumerate(lineals):
        assert l.enable == 1
        assert l.point_0 == POINTS[i]      # lower station
        assert l.point_1 == POINTS[i + 1]  # higher station


def test_single_segment_split_at_midpoint():
    """A lone Lineal reads back as a stray reference line, so a straight
    2-point centerline is written as two collinear halves."""
    lineals = centerline_to_lineals([(1000.0, 2400.0), (1000.0, 2000.0)])
    assert len(lineals) == 2
    assert lineals[0].point_1 == lineals[1].point_0 == (1000.0, 2200.0)
    assert lineals_to_centerlines(lineals) == [
        [(1000.0, 2400.0), (1000.0, 2200.0), (1000.0, 2000.0)]]


def test_too_few_points_gives_no_lineals():
    assert centerline_to_lineals([]) == []
    assert centerline_to_lineals([(10.0, 20.0)]) == []
    # Two coincident points collapse to one
    assert centerline_to_lineals([(10.0, 20.0), (10.0, 20.0)]) == []


def test_consecutive_duplicates_dropped():
    pts = [POINTS[0], POINTS[0], POINTS[1], POINTS[1], POINTS[2]]
    lineals = centerline_to_lineals(pts)
    assert len(lineals) == 2
    assert lineals_to_centerlines(lineals) == [[POINTS[0], POINTS[1], POINTS[2]]]


# ---------------------------------------------------------------------------
# Round trip: points -> Lineals -> points
# ---------------------------------------------------------------------------

def test_roundtrip_simple():
    assert lineals_to_centerlines(centerline_to_lineals(POINTS)) == [POINTS]


def test_roundtrip_full_precision_points():
    pts = [(1000.123456, 2400.654321), (1010.111111, 2000.222222),
           (1050.333333, 1500.444444)]
    assert lineals_to_centerlines(centerline_to_lineals(pts)) == [pts]


def test_roundtrip_two_centerlines():
    lineals = centerline_to_lineals(POINTS) + centerline_to_lineals(CROSS)
    assert lineals_to_centerlines(lineals) == [POINTS, CROSS]


def test_roundtrip_order_independent():
    """The Lineal list order carries no meaning within a chain — segments
    are rejoined by shared vertices whatever order the file lists them in.
    (Centerlines themselves come back in file order: whichever chain's
    first segment appears earliest in the list is first.)"""
    lineals = centerline_to_lineals(POINTS)
    for seed in range(10):
        shuffled = lineals[:]
        random.Random(seed).shuffle(shuffled)
        assert lineals_to_centerlines(shuffled) == [POINTS]
    assert lineals_to_centerlines(list(reversed(lineals))) == [POINTS]


def test_roundtrip_two_centerlines_interleaved():
    both = centerline_to_lineals(POINTS) + centerline_to_lineals(CROSS)
    shuffled = both[:]
    random.Random(7).shuffle(shuffled)
    got = lineals_to_centerlines(shuffled)
    assert sorted(got) == sorted([POINTS, CROSS])  # file order may differ


def test_roundtrip_survives_flipped_interior_segment():
    """Station 0 is recovered from the terminal segments' point order, so
    a foreign tool flipping an interior segment changes nothing."""
    lineals = centerline_to_lineals(POINTS)
    lineals[1].point_0, lineals[1].point_1 = lineals[1].point_1, lineals[1].point_0
    assert lineals_to_centerlines(lineals) == [POINTS]


def test_both_ends_hinted_falls_back_to_file_order():
    """Both terminal segments written outward (foreign edit): no unique
    station-0 hint, so the end on the lower-indexed Lineal wins."""
    lineals = centerline_to_lineals(POINTS)
    last = lineals[-1]
    last.point_0, last.point_1 = last.point_1, last.point_0
    assert lineals_to_centerlines(lineals) == [POINTS]


# ---------------------------------------------------------------------------
# Chain identification amid other Lineals
# ---------------------------------------------------------------------------

def test_disabled_and_placeholder_lineals_ignored():
    lineals = [placeholder(),
               Lineal(enable=0, point_0=(5.0, 5.0), point_1=(50.0, 50.0)),
               *centerline_to_lineals(POINTS),
               placeholder()]
    assert lineals_to_centerlines(lineals) == [POINTS]


def test_lone_line_is_a_stray_not_a_centerline():
    """The identification rule: a Lineal is part of a centerline only when
    it shares an endpoint with another Lineal. A lone vendor-drawn
    reference line is never a centerline."""
    stray = Lineal(enable=1, point_0=(5.0, 5.0), point_1=(700.0, 5.0))
    assert lineals_to_centerlines([stray]) == []
    assert lineals_to_centerlines([stray, *centerline_to_lineals(POINTS)]) == [POINTS]


def test_closed_loop_ignored():
    a, b, c = (0.0, 0.0), (100.0, 0.0), (0.0, 100.0)
    loop = [Lineal(enable=1, point_0=p, point_1=q)
            for p, q in [(a, b), (b, c), (c, a)]]
    assert lineals_to_centerlines(loop) == []
    assert lineals_to_centerlines(loop + centerline_to_lineals(POINTS)) == [POINTS]


def test_branching_component_ignored():
    a, b = (0.0, 0.0), (100.0, 0.0)
    fork = [Lineal(enable=1, point_0=a, point_1=b),
            Lineal(enable=1, point_0=b, point_1=(200.0, 50.0)),
            Lineal(enable=1, point_0=b, point_1=(200.0, -50.0))]
    assert lineals_to_centerlines(fork) == []
    assert lineals_to_centerlines(fork + centerline_to_lineals(POINTS)) == [POINTS]


def test_empty_and_no_candidates():
    assert lineals_to_centerlines([]) == []
    assert lineals_to_centerlines([placeholder()] * 3) == []


# ---------------------------------------------------------------------------
# Project-level save/load
# ---------------------------------------------------------------------------

def test_save_fills_placeholder_slots():
    project = Project(lineals=[placeholder() for _ in range(100)])
    save_centerlines(project, [POINTS, CROSS])
    assert len(project.lineals) == 100  # vendor fixed-size array kept
    assert [l.enable for l in project.lineals[:6]] == [1] * 6
    assert all(not l.enable for l in project.lineals[6:])
    assert load_centerlines(project) == [POINTS, CROSS]


def test_resave_replaces_whole_set():
    project = Project(lineals=[placeholder() for _ in range(100)])
    save_centerlines(project, [POINTS, CROSS])
    save_centerlines(project, [POINTS[:3]])  # 6 segments -> 2
    assert sum(1 for l in project.lineals if l.enable) == 2
    assert load_centerlines(project) == [POINTS[:3]]


def test_save_empty_deletes_all_centerlines():
    project = Project(lineals=[placeholder() for _ in range(100)])
    save_centerlines(project, [POINTS, CROSS])
    save_centerlines(project, [])
    assert not any(l.enable for l in project.lineals)
    assert load_centerlines(project) == []


def test_save_preserves_strays_and_foreign_components():
    """Save only replaces Lineal chains — a lone reference line, a
    disabled Lineal with geometry, and a branching component are neither
    replaced nor claimed as free slots."""
    stray = Lineal(enable=1, point_0=(5.0, 5.0), point_1=(700.0, 5.0))
    disabled = Lineal(enable=0, point_0=(9.0, 9.0), point_1=(90.0, 9.0))
    b = (2000.0, 0.0)
    fork = [Lineal(enable=1, point_0=(1900.0, 0.0), point_1=b),
            Lineal(enable=1, point_0=b, point_1=(2100.0, 50.0)),
            Lineal(enable=1, point_0=b, point_1=(2100.0, -50.0))]
    project = Project(lineals=[stray, disabled, *fork,
                               *centerline_to_lineals(POINTS), placeholder()])
    save_centerlines(project, [list(reversed(POINTS)), CROSS])
    assert stray.point_0 == (5.0, 5.0) and stray.enable == 1
    assert disabled.point_0 == (9.0, 9.0) and not disabled.enable
    assert all(f.enable for f in fork)
    assert load_centerlines(project) == [list(reversed(POINTS)), CROSS]


def test_save_appends_when_no_free_slots():
    project = Project()  # from-scratch project: no placeholder array
    save_centerlines(project, [POINTS, CROSS])
    assert len(project.lineals) == 6
    assert load_centerlines(project) == [POINTS, CROSS]


def test_replacement_reuses_freed_slots():
    project = Project()
    save_centerlines(project, [POINTS])
    save_centerlines(project, [POINTS[:3]])
    assert len(project.lineals) == 3  # old slots blanked and refilled, not grown
    assert sum(1 for l in project.lineals if l.enable) == 2
    assert load_centerlines(project) == [POINTS[:3]]


# ---------------------------------------------------------------------------
# Through the .iprj file itself
# ---------------------------------------------------------------------------

def test_file_roundtrip(tmp_path):
    project = Project(lineals=[placeholder() for _ in range(100)])
    save_centerlines(project, [POINTS, CROSS])
    path = tmp_path / "centerline.iprj"
    save_iprj(project, path)
    assert load_centerlines(load_iprj(path)) == [POINTS, CROSS]


def test_file_roundtrip_full_precision(tmp_path):
    # _fmt falls back to repr when 2 decimals would lose value, so odd
    # coordinates survive the file exactly too.
    pts = [(1000.123456, 2400.654321), (1010.111111, 2000.222222),
           (1050.333333, 1500.444444)]
    project = Project()
    save_centerlines(project, [pts])
    path = tmp_path / "centerline.iprj"
    save_iprj(project, path)
    assert load_centerlines(load_iprj(path)) == [pts]


# ---------------------------------------------------------------------------
# Band ownership (ROADMAP Item 21)
# ---------------------------------------------------------------------------

from model.bands import Owner  # noqa: E402
from model.centerline import (  # noqa: E402
    load_centerlines_owned,
    save_centerlines_owned,
)


def test_save_centerlines_owned_places_each_in_its_band():
    project = Project(lineals=[placeholder() for _ in range(100)])
    skipped = save_centerlines_owned(project, [
        (Owner.GENERAL, POINTS),  # 3 segments -> 0,1,2
        (Owner.FILE1, CROSS),     # 3 segments -> 20,21,22
        (Owner.FILE2, POINTS),    # 3 segments -> 60,61,62
    ])
    assert skipped == []
    assert [l.enable for l in project.lineals[0:3]] == [1, 1, 1]
    assert [l.enable for l in project.lineals[20:23]] == [1, 1, 1]
    assert [l.enable for l in project.lineals[60:63]] == [1, 1, 1]
    # nothing bled into the gaps between bands
    assert all(not l.enable for l in project.lineals[3:20])
    assert all(not l.enable for l in project.lineals[23:60])


def test_load_centerlines_owned_infers_band():
    project = Project(lineals=[placeholder() for _ in range(100)])
    save_centerlines_owned(project, [(Owner.FILE2, POINTS), (Owner.GENERAL, CROSS)])
    owned = load_centerlines_owned(project)
    # file order: GENERAL chain (idx 0) before FILE2 chain (idx 60)
    assert owned == [(Owner.GENERAL, CROSS), (Owner.FILE2, POINTS)]


def test_owned_centerlines_survive_the_file(tmp_path):
    project = Project(lineals=[placeholder() for _ in range(100)])
    save_centerlines_owned(project, [(Owner.FILE1, POINTS), (Owner.FILE2, CROSS)])
    path = tmp_path / "banded.iprj"
    save_iprj(project, path)
    assert load_centerlines_owned(load_iprj(path)) == [
        (Owner.FILE1, POINTS), (Owner.FILE2, CROSS)]


def test_centerline_overflowing_its_band_is_skipped():
    # A 21-segment centerline can't fit the 20-slot GENERAL band.
    big = [(float(i), 0.0) for i in range(22)]  # 22 points -> 21 segments
    project = Project(lineals=[placeholder() for _ in range(100)])
    skipped = save_centerlines_owned(project, [(Owner.GENERAL, big)])
    assert skipped == [big]
    assert load_centerlines_owned(project) == []
    # the same centerline fits a 40-slot FILE band
    assert save_centerlines_owned(project, [(Owner.FILE1, big)]) == []
    assert load_centerlines_owned(project) == [(Owner.FILE1, big)]
