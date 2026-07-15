"""Review labeling session tests (2026-07-14 round, model/review.py).

The pure half of the in-GUI ground-truth labeling: selection toggling, group
commit rules (refuse-don't-guess on bad input), and the observations-schema
(de)serialization that must stay loadable by scripts/fusion_eval.py — the
same schema as tests/fixtures/stitch_observations_2026-07-13.json.
"""

import json
from pathlib import Path

import pytest

from model.review import (
    KINDS,
    ReviewGroup,
    ReviewSession,
    observations_path,
)


# --- selection -----------------------------------------------------------------


def test_toggle_selects_and_deselects_in_order():
    s = ReviewSession()
    assert s.toggle((0, 100))
    assert s.toggle((1, 200))
    assert s.toggle((0, 300))
    assert s.selection == [(0, 100), (1, 200), (0, 300)]
    assert not s.toggle((1, 200))  # second click deselects
    assert s.selection == [(0, 100), (0, 300)]  # order of the rest kept
    s.clear_selection()
    assert s.selection == []


def test_is_selected():
    s = ReviewSession()
    s.toggle((0, 100))
    assert s.is_selected((0, 100))
    assert not s.is_selected((1, 100))


# --- group commit ----------------------------------------------------------------


def test_commit_moves_selection_into_a_group():
    s = ReviewSession()
    s.toggle((0, 100))
    s.toggle((1, 200))
    g = s.commit("handoff", note="through the corner")
    assert g.kind == "handoff"
    assert g.members == ((0, 100), (1, 200))
    assert g.note == "through the corner"
    assert s.selection == []  # consumed
    assert s.groups == [g]
    assert s.labeled_members() == {(0, 100), (1, 200)}


def test_commit_refuses_bad_input():
    s = ReviewSession()
    with pytest.raises(ValueError):
        s.commit("handoff")  # nothing selected
    s.toggle((0, 100))
    with pytest.raises(ValueError):
        s.commit("nonsense")  # unknown kind
    for kind in ("handoff", "persistence"):
        with pytest.raises(ValueError):
            s.commit(kind)  # pair kinds need two members
    # anchor and stray label a single track
    s.commit("anchor")
    s.toggle((0, 200))
    s.commit("stray")
    assert [g.kind for g in s.groups] == ["anchor", "stray"]


def test_bad_pair_needs_two_members():
    """bad_pair (Item 47) is the inverse of handoff/persistence — like them it
    describes two-or-more tracks, so a single member is refused."""
    assert "bad_pair" in KINDS
    s = ReviewSession()
    s.toggle((0, 100))
    with pytest.raises(ValueError):
        s.commit("bad_pair")  # only one member
    s.toggle((0, 200))  # same-sensor over-merge is a valid bad_pair
    g = s.commit("bad_pair", note="two vehicles fused into one")
    assert g.kind == "bad_pair"
    assert g.members == ((0, 100), (0, 200))
    assert g.note == "two vehicles fused into one"
    assert s.selection == []


def test_bad_pair_survives_json_round_trip(tmp_path: Path):
    s = ReviewSession(capture="c", recording="r.txt.gz")
    s.toggle((0, 100))
    s.toggle((1, 201))
    s.commit("bad_pair", unsure=True)
    path = tmp_path / "obs.json"
    s.save(path)
    loaded = ReviewSession.load(path)
    assert loaded.groups[0].kind == "bad_pair"
    assert loaded.groups[0].unsure is True
    assert loaded.groups[0].members == ((0, 100), (1, 201))


def test_same_sensor_is_derived():
    assert ReviewGroup("persistence", ((2, 10), (2, 20))).same_sensor
    assert not ReviewGroup("handoff", ((0, 10), (1, 20))).same_sensor
    assert not ReviewGroup("stray", ((0, 10),)).same_sensor  # single member


def test_remove_group():
    s = ReviewSession()
    s.toggle((0, 100))
    s.commit("stray")
    s.toggle((0, 200))
    s.commit("anchor")
    removed = s.remove(0)
    assert removed.kind == "stray"
    assert [g.kind for g in s.groups] == ["anchor"]


# --- observations schema ----------------------------------------------------------


def _session() -> ReviewSession:
    s = ReviewSession(
        capture="10_37_64_32_EVO_1783833336",
        recording="sites/32_US12&21st/10_37_64_32_EVO_1783833336.txt.gz",
        iprj_candidates=["sites/32_US12&21st/32_US-12&21st_1_2.iprj"])
    s.toggle((0, 881520))
    s.toggle((1, 415541))
    s.commit("handoff")
    s.toggle((2, 980012))
    s.toggle((2, 980072))
    s.commit("persistence", unsure=True, note="~12 s gap")
    s.toggle((1, 420881))
    s.commit("stray", ped=True)
    return s


def test_to_json_matches_fixture_schema():
    doc = _session().to_json()
    (name,) = doc["captures"]
    entry = doc["captures"][name]
    assert entry["recording"].endswith(".txt.gz")
    assert entry["iprj_candidates"]
    g0, g1, g2 = entry["groups"]
    assert g0 == {"kind": "handoff", "members": [[0, 881520], [1, 415541]]}
    # optional keys only when set, like the hand-written fixture
    assert g1["same_sensor"] is True and g1["unsure"] is True
    assert g1["note"] == "~12 s gap"
    assert "ped" not in g1
    assert g2["ped"] is True and "unsure" not in g2


def test_json_round_trip(tmp_path: Path):
    s = _session()
    path = tmp_path / "obs.json"
    s.save(path)
    loaded = ReviewSession.load(path)
    assert loaded.capture == s.capture
    assert loaded.recording == s.recording
    assert loaded.iprj_candidates == s.iprj_candidates
    assert loaded.groups == s.groups
    assert loaded.selection == []


def test_loadable_by_the_eval_harness_reader(tmp_path: Path):
    """The saved document walks exactly like the eval harness walks the
    2026-07-13 fixture: captures -> entry -> groups with kind/members, and
    every member is a [sensor, oid] pair of ints."""
    path = tmp_path / "obs.json"
    _session().save(path)
    obs = json.loads(path.read_text())
    for entry in obs["captures"].values():
        assert isinstance(entry["recording"], str)
        assert isinstance(entry["iprj_candidates"], list)
        for g in entry["groups"]:
            assert g["kind"] in KINDS
            for m in g["members"]:
                s_, o = m
                assert isinstance(s_, int) and isinstance(o, int)
                assert tuple(m) == (s_, o)  # the harness does tuple(m)


def test_fixture_itself_round_trips_through_from_json():
    """Loading the real multi-capture fixture takes its first capture and
    preserves the group flags — review resumes a hand-written file too."""
    fixture = Path(__file__).parent / "fixtures" / \
        "stitch_observations_2026-07-13.json"
    s = ReviewSession.from_json(json.loads(fixture.read_text()))
    assert s.capture == "64_32"
    assert s.recording.endswith("10_37_64_32_EVO_1783833336.txt.gz")
    assert len(s.groups) == 9
    assert s.groups[0].kind == "handoff"
    assert s.groups[0].members == ((0, 881520), (2, 979772), (1, 415541))
    assert s.groups[5].same_sensor  # the three slot-2 re-acquisitions


def test_observations_path_naming():
    assert observations_path(Path("/x/10_37_64_32_EVO_1.txt.gz")) \
        == Path("/x/10_37_64_32_EVO_1.observations.json")
    assert observations_path(Path("/x/cap.txt")) \
        == Path("/x/cap.observations.json")
    assert observations_path(Path("/x/other.dat")) \
        == Path("/x/other.dat.observations.json")
