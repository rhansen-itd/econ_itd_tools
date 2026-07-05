"""Tests for the side-by-side detector table grouping (ROADMAP Item 16)."""

import pytest

from model.detector_layout import (assign_tracks, group_adjacent_detectors,
                                    longitudinal_span)
from model.templates import (ApproachTemplate, Lane, TemplateDetector,
                             seed_detectors)


def det(setback: float, length: float, span=(0,)) -> TemplateDetector:
    span = list(span)
    return TemplateDetector(kind="decision", spanning_lanes=span,
                            length_ft=length, setback_ft=setback,
                            output_offset=0, phase="thru")


# ---------------------------------------------------------------------------
# longitudinal_span
# ---------------------------------------------------------------------------

def test_longitudinal_span_is_setback_to_upstream_edge():
    assert longitudinal_span(det(165.0, 20.0)) == (165.0, 185.0)
    # negative (past-the-bar) setbacks work the same
    assert longitudinal_span(det(-15.0, 5.0)) == (-15.0, -10.0)


# ---------------------------------------------------------------------------
# group_adjacent_detectors — overlap / touch / gap boundaries
# ---------------------------------------------------------------------------

def test_overlapping_detectors_share_a_group():
    # two 15' detectors offset by 10' overlap over [10,15] -> one row
    dets = [det(0.0, 15.0), det(10.0, 15.0)]
    assert group_adjacent_detectors(dets) == [[0, 1]]


def test_touching_detectors_share_a_group():
    # shared endpoint counts as side-by-side at that station
    dets = [det(0.0, 10.0), det(10.0, 5.0)]
    assert group_adjacent_detectors(dets) == [[0, 1]]


def test_gap_splits_groups():
    dets = [det(0.0, 10.0), det(11.0, 9.0)]  # [0,10] and [11,20]
    assert group_adjacent_detectors(dets) == [[0], [1]]


def test_transitive_chain_is_one_group():
    # A-B touch, B-C touch, but A-C don't overlap -> still one connected band
    dets = [det(0.0, 10.0), det(10.0, 5.0), det(15.0, 5.0)]
    assert group_adjacent_detectors(dets) == [[0, 1, 2]]


def test_groups_ordered_by_setback_input_order_preserved_within():
    # deliberately unsorted input; two bands: {-15 band} and {100 band}
    dets = [
        det(100.0, 10.0, (1,)),   # 0  upstream band
        det(-15.0, 5.0, (0,)),    # 1  stop-bar band
        det(105.0, 10.0, (2,)),   # 2  upstream band (overlaps 0)
        det(-15.0, 5.0, (1,)),    # 3  stop-bar band (overlaps 1)
    ]
    groups = group_adjacent_detectors(dets)
    # downstream (-15) band first; within a group, original index order kept
    assert groups == [[1, 3], [0, 2]]


def test_empty_input():
    assert group_adjacent_detectors([]) == []


# ---------------------------------------------------------------------------
# group_adjacent_detectors — the seeded acceptance case
# ---------------------------------------------------------------------------

def acceptance() -> ApproachTemplate:
    return ApproachTemplate(
        name="45 mph north approach", speed_mph=45.0,
        lanes=[Lane("L"), Lane("T"), Lane("T"), Lane("R")],
        count_loops=True, base_output=33, direction="N",
        thru_phase=4, lt_phase=7)


def test_seeded_acceptance_groups_into_five_rows():
    rows = seed_detectors(acceptance())
    groups = group_adjacent_detectors(rows)
    # 12 detectors -> 5 side-by-side rows: count x4, stop-bar x4, the two
    # (non-overlapping) decision detectors, then the two advance loops.
    assert groups == [[0, 1, 2, 3], [4, 5, 6, 7], [8], [9], [10, 11]]
    kinds = [rows[g[0]].kind for g in groups]
    assert kinds == ["count", "stop_bar", "decision", "decision", "advance"]


def test_seeded_groups_flatten_back_to_seed_order():
    rows = seed_detectors(acceptance())
    flat = [i for g in group_adjacent_detectors(rows) for i in g]
    assert flat == list(range(len(rows)))  # order preserved -> numbering stable


# ---------------------------------------------------------------------------
# assign_tracks — lane-column collision avoidance
# ---------------------------------------------------------------------------

def test_non_overlapping_lanes_all_track_zero():
    # count loops one per lane never collide laterally
    assert assign_tracks([(0, 0), (1, 1), (2, 2), (3, 3)]) == [0, 0, 0, 0]


def test_lane_overlap_forces_new_track():
    # two spans sharing lane 1 -> different tracks
    assert assign_tracks([(0, 1), (1, 2)]) == [0, 1]


def test_greedy_reuses_lowest_free_track():
    # third span collides with the first (both lane 0) but not the second
    assert assign_tracks([(0, 0), (1, 1), (0, 0)]) == [0, 0, 1]


def test_assign_tracks_empty():
    assert assign_tracks([]) == []
