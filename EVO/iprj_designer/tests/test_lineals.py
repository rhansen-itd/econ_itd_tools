"""Generic-lineal round-trip (Phase 3.2a, PHASE3_UI_PLAN §4.3):
`load_lineals`/`save_lineals` handle the non-chain stray Lineals, with the
endpoint-coincidence guard that keeps a stray from being re-read as part of
a centerline chain on the next load."""

from model.centerline import (load_centerlines, load_lineals,
                              lineals_to_centerlines, save_centerlines,
                              save_lineals)
from model.iprj_io import Lineal, Project


def placeholder():
    return Lineal(enable=0, point_0=(0.0, 0.0), point_1=(0.0, 0.0))


def project_with(lineals, n_placeholders=5):
    return Project(lineals=list(lineals) + [placeholder()
                                            for _ in range(n_placeholders)])


CHAIN = [Lineal(enable=1, point_0=(0.0, 0.0), point_1=(50.0, 0.0)),
         Lineal(enable=1, point_0=(50.0, 0.0), point_1=(100.0, 0.0))]


def chain():
    return [Lineal(enable=1, point_0=l.point_0, point_1=l.point_1)
            for l in CHAIN]


def test_load_lineals_returns_only_strays():
    stray = Lineal(enable=1, point_0=(200.0, 10.0), point_1=(250.0, 10.0))
    project = project_with(chain() + [stray])
    loaded = load_lineals(project)
    assert [(l.point_0, l.point_1) for l in loaded] == [
        ((200.0, 10.0), (250.0, 10.0))]
    # working copies: mutating a loaded lineal must not touch the project
    loaded[0].point_0 = (999.0, 999.0)
    assert project.lineals[2].point_0 == (200.0, 10.0)


def test_load_lineals_skips_disabled_with_geometry():
    ghost = Lineal(enable=0, point_0=(5.0, 5.0), point_1=(9.0, 9.0))
    assert load_lineals(project_with([ghost])) == []


def test_save_lineals_round_trips_through_placeholder_slots():
    project = project_with(chain())
    strays = [Lineal(enable=1, point_0=(200.0, 0.0), point_1=(250.0, 0.0)),
              Lineal(enable=1, point_0=(300.0, 5.0), point_1=(310.0, 45.0))]
    assert save_lineals(project, strays) == []
    assert len(project.lineals) == 7           # slots reused, none appended
    loaded = load_lineals(project)
    assert [(l.point_0, l.point_1) for l in loaded] == [
        ((200.0, 0.0), (250.0, 0.0)), ((300.0, 5.0), (310.0, 45.0))]
    # the chain is untouched
    assert lineals_to_centerlines(project.lineals) == [
        [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]]


def test_save_lineals_replaces_the_previous_stray_set():
    project = project_with([])
    save_lineals(project, [Lineal(enable=1, point_0=(1.0, 1.0),
                                  point_1=(2.0, 2.0))])
    save_lineals(project, [Lineal(enable=1, point_0=(7.0, 7.0),
                                  point_1=(9.0, 9.0))])
    loaded = load_lineals(project)
    assert [(l.point_0, l.point_1) for l in loaded] == [((7.0, 7.0), (9.0, 9.0))]
    save_lineals(project, [])                  # empty set deletes them all
    assert load_lineals(project) == []


def test_save_lineals_skips_chain_coincident_stray():
    project = project_with(chain())
    bad = Lineal(enable=1, point_0=(50.0, 0.0), point_1=(80.0, 40.0))
    ok = Lineal(enable=1, point_0=(200.0, 0.0), point_1=(250.0, 0.0))
    skipped = save_lineals(project, [bad, ok])
    assert skipped == [bad]
    assert len(load_lineals(project)) == 1
    # the chain still reads back as one centerline
    assert len(lineals_to_centerlines(project.lineals)) == 1


def test_save_lineals_skips_second_of_two_coincident_strays():
    project = project_with([])
    a = Lineal(enable=1, point_0=(0.0, 0.0), point_1=(50.0, 0.0))
    b = Lineal(enable=1, point_0=(50.0, 0.0), point_1=(100.0, 40.0))
    assert save_lineals(project, [a, b]) == [b]
    assert len(load_lineals(project)) == 1


def test_save_lineals_skips_degenerate_and_ignores_placeholders():
    project = project_with([])
    zero = Lineal(enable=1, point_0=(5.0, 5.0), point_1=(5.001, 5.002))
    skipped = save_lineals(project, [zero, placeholder()])
    assert skipped == [zero]                   # rounds to a shared key
    assert load_lineals(project) == []


def test_save_lineals_appends_when_no_free_slots():
    project = project_with([], n_placeholders=0)
    save_lineals(project, [Lineal(enable=1, point_0=(1.0, 1.0),
                                  point_1=(2.0, 2.0))])
    assert len(project.lineals) == 1
    assert load_lineals(project)[0].point_1 == (2.0, 2.0)


def test_guard_sees_chains_written_by_save_centerlines():
    project = project_with([])
    save_centerlines(project, [[(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]])
    bad = Lineal(enable=1, point_0=(100.0, 0.0), point_1=(150.0, 50.0))
    assert save_lineals(project, [bad]) == [bad]
    # nothing merged: still exactly one centerline, no strays
    assert load_centerlines(project) == [[(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]]
    assert load_lineals(project) == []


# ---------------------------------------------------------------------------
# Band ownership (ROADMAP Item 21)
# ---------------------------------------------------------------------------

from model.bands import Owner  # noqa: E402
from model.centerline import load_lineals_owned, save_lineals_owned  # noqa: E402


def _full():
    return [placeholder() for _ in range(100)]


def test_save_lineals_owned_places_in_bands():
    project = Project(lineals=_full())
    strays = [
        (Owner.GENERAL, Lineal(enable=1, point_0=(1.0, 1.0), point_1=(2.0, 2.0))),
        (Owner.FILE1, Lineal(enable=1, point_0=(3.0, 3.0), point_1=(4.0, 4.0))),
        (Owner.FILE2, Lineal(enable=1, point_0=(5.0, 5.0), point_1=(6.0, 6.0))),
    ]
    assert save_lineals_owned(project, strays) == []
    assert project.lineals[0].point_0 == (1.0, 1.0)
    assert project.lineals[20].point_0 == (3.0, 3.0)
    assert project.lineals[60].point_0 == (5.0, 5.0)


def test_load_lineals_owned_infers_band():
    project = Project(lineals=_full())
    project.lineals[25] = Lineal(enable=1, point_0=(3.0, 3.0), point_1=(4.0, 4.0))
    project.lineals[70] = Lineal(enable=1, point_0=(5.0, 5.0), point_1=(6.0, 6.0))
    owned = load_lineals_owned(project)
    assert [(o, l.point_0) for o, l in owned] == [
        (Owner.FILE1, (3.0, 3.0)), (Owner.FILE2, (5.0, 5.0))]


def test_owned_strays_survive_the_file(tmp_path):
    from model.iprj_io import load_iprj, save_iprj
    project = Project(lineals=_full())
    save_lineals_owned(project, [
        (Owner.FILE1, Lineal(enable=1, point_0=(3.0, 3.0), point_1=(4.0, 4.0)))])
    path = tmp_path / "owned_strays.iprj"
    save_iprj(project, path)
    owned = load_lineals_owned(load_iprj(path))
    assert [(o, l.point_0, l.point_1) for o, l in owned] == [
        (Owner.FILE1, (3.0, 3.0), (4.0, 4.0))]
