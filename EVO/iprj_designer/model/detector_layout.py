"""Side-by-side detector table layout (ROADMAP Item 16) — display-only.

The template editor's grid can show detectors that sit at the same distance
from the stop bar (the count loops across the lanes, the stop-bar zones, the
advance loops, ...) **side by side across lane columns** as one row, instead
of one stacked row per detector. This module is the pure, headless grouping
logic behind that layout — it never touches GUI code and never changes the
saved template (grouping is a view over the flat ``detectors`` list, not a
persisted field).

Two concepts:

* **Adjacency group** — one table row. Detectors are *adjacent* when their
  longitudinal extents (``setback_ft`` .. ``setback_ft + length_ft``, positive
  upstream) overlap or touch; a row is a **connected component** under that
  relation, so a chain of staggered overlaps (A–B overlap, B–C overlap, A–C
  not) still forms one band. `group_adjacent_detectors` returns the groups.
* **Track** — a sub-row within a group. Detectors in the same group that share
  a lane column would collide in one grid cell, so `assign_tracks` colors them
  (greedy, by lane span) onto separate tracks. Seeded rows never collide
  laterally (one detector per lane at each station), so they use a single
  track; tracks only matter for hand-built rows.

Grouping is done once when the editor seeds or loads a template (the detectors
are valid `templates.TemplateDetector` objects then); it is not recomputed on
every keystroke, so cards don't jump rows while a setback is being typed.
"""

from __future__ import annotations

from typing import Protocol, Sequence


class _HasExtent(Protocol):
    setback_ft: float
    length_ft: float


def longitudinal_span(det: _HasExtent) -> tuple[float, float]:
    """The detector's along-travel extent as ``(downstream_edge,
    upstream_edge)`` setbacks — ``setback_ft`` is the downstream (stop-bar
    side) edge, ``+ length_ft`` the upstream edge."""
    return (det.setback_ft, det.setback_ft + det.length_ft)


def _overlaps(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Two closed intervals overlap or touch (shared endpoints count — they
    are side by side at that station)."""
    return a[0] <= b[1] and b[0] <= a[1]


def group_adjacent_detectors(
    detectors: Sequence[_HasExtent],
) -> list[list[int]]:
    """Group detector indices into adjacency rows (connected components under
    longitudinal overlap; see module docstring).

    Returns lists of indices into ``detectors``. Groups are ordered by
    ascending minimum setback (then first input index) so upstream rows sit
    below stop-bar rows in the same order the seeder emits them; **input order
    is preserved within each group**, so flattening a freshly seeded list
    reproduces it exactly (output numbering stays put).
    """
    n = len(detectors)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        parent[find(i)] = find(j)

    spans = [longitudinal_span(d) for d in detectors]
    for i in range(n):
        for j in range(i + 1, n):
            if _overlaps(spans[i], spans[j]):
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):  # input order -> preserved within each component
        groups.setdefault(find(i), []).append(i)

    # order rows by the group's downstream-most edge, then first-seen index
    return sorted(
        groups.values(),
        key=lambda members: (min(spans[i][0] for i in members), members[0]),
    )


def assign_tracks(lane_spans: Sequence[tuple[int, int]]) -> list[int]:
    """Assign each detector in a group to a track (sub-row) so that no two
    detectors sharing a lane column land on the same track.

    ``lane_spans`` is one ``(lane_from, lane_to)`` inclusive pair per detector
    (from ``spanning_lanes[0]``/``[-1]``). Returns a track index per detector,
    lowest available first (greedy interval-graph coloring), in input order.
    Detectors that don't share any lane column all get track 0.
    """
    tracks: list[list[tuple[int, int]]] = []  # occupied lane spans per track
    result: list[int] = []
    for lo, hi in lane_spans:
        placed = -1
        for t, occupied in enumerate(tracks):
            if all(hi < o_lo or o_hi < lo for o_lo, o_hi in occupied):
                occupied.append((lo, hi))
                placed = t
                break
        if placed < 0:
            placed = len(tracks)
            tracks.append([(lo, hi)])
        result.append(placed)
    return result
