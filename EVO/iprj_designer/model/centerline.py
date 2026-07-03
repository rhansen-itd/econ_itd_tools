"""Persist approach centerlines through the iprj `Lineal` entity.

The vendor format has no polyline entity; the closest is `Lineal`, a fixed
2-point line. A centerline of N ordered points is saved as enabled
Lineals, one per segment — segment i runs point_0=points[i] (lower
station) to point_1=points[i+1] — and reconstructed on load by walking the
enabled Lineals as an undirected graph of segments and chaining runs that
share an endpoint.

**Identification rule** (see IPRJ_FORMAT.md): `Lineal` carries no name or
tag, so centerlines are identified purely by shape — any Lineal that
shares an endpoint with another Lineal is part of a centerline; a
connected component that forms a simple open chain (every vertex on at
most two segments, exactly two chain ends) of two or more segments is one
centerline. A project usually holds several (intersecting roads: two at
minimum). A *lone* segment sharing no endpoint is taken to be a stray
vendor-drawn reference line and is never a centerline; so that a genuine
single-segment (straight) centerline survives, save splits it at its
midpoint into two collinear Lineals — it reloads with one interpolated
mid vertex, geometrically identical. Two centerlines drawn with a
*coincident vertex* would merge or stop chaining on reload (crossing
mid-segment, as intersecting roads normally do, is fine — only shared
endpoints join). Components with branching vertices or cycles are never
candidates and are left untouched.

Orientation: a bag of undirected segments doesn't carry direction, so the
per-segment point order is used as a hint — station 0 is the chain end
that is `point_0` of its terminal segment (what save writes). If foreign
edits leave both or neither end looking like that, the end on the
lower-indexed Lineal wins, so reconstruction is deterministic either way.

Vertices are matched at 2-decimal precision, mirroring the vendor's float
formatting; consecutive shared endpoints are written from the same value,
so real files always rejoin exactly.
"""

from __future__ import annotations

from typing import Sequence

from .iprj_io import Lineal, Point, Project

_KEY_DECIMALS = 2  # vendor files format floats to 2 decimals

_Key = tuple[float, float]


def _key(p: Point) -> _Key:
    return (round(float(p[0]), _KEY_DECIMALS), round(float(p[1]), _KEY_DECIMALS))


def _is_free_slot(lineal: Lineal) -> bool:
    """A placeholder slot (vendor files pre-allocate 100 with Enable=0 and
    zeroed points) that save may claim; a disabled Lineal with real
    geometry is someone's drawing and is left alone."""
    zero = (0.0, 0.0)
    return (not lineal.enable
            and (lineal.point_0 is None or _key(lineal.point_0) == zero)
            and (lineal.point_1 is None or _key(lineal.point_1) == zero))


def centerline_to_lineals(points: Sequence[Point]) -> list[Lineal]:
    """One centerline's ordered points -> enabled `Lineal`s, one per segment.

    Segment i is point_0=points[i], point_1=points[i+1], so the point
    order carries the station direction. Consecutive duplicate points
    (2-decimal precision) are dropped — a zero-length segment would break
    the shared-vertex chaining. A single-segment centerline is split at
    its midpoint into two collinear Lineals, because a lone Lineal reads
    back as a stray reference line, not a centerline (see module
    docstring). Fewer than two distinct points -> [].
    """
    pts: list[Point] = []
    for p in points:
        q = (float(p[0]), float(p[1]))
        if not pts or _key(q) != _key(pts[-1]):
            pts.append(q)
    if len(pts) == 2:
        (x0, y0), (x1, y1) = pts
        pts.insert(1, ((x0 + x1) / 2.0, (y0 + y1) / 2.0))
    return [Lineal(enable=1, point_0=a, point_1=b) for a, b in zip(pts, pts[1:])]


def _find_chains(lineals: Sequence[Lineal]) -> list[tuple[list[Point], list[Lineal]]]:
    """Every centerline hidden in *lineals*: a list of (ordered points,
    the Lineal objects that encode it), ordered by first appearance
    (lowest Lineal index) in the list."""
    # Usable segments: enabled, two distinct endpoints.
    segs: list[tuple[int, _Key, _Key, Point, Point]] = []
    for i, l in enumerate(lineals):
        if not l.enable or l.point_0 is None or l.point_1 is None:
            continue
        k0, k1 = _key(l.point_0), _key(l.point_1)
        if k0 != k1:
            segs.append((i, k0, k1, l.point_0, l.point_1))
    if not segs:
        return []

    by_vertex: dict[_Key, list[int]] = {}
    for si, (_, k0, k1, _, _) in enumerate(segs):
        by_vertex.setdefault(k0, []).append(si)
        by_vertex.setdefault(k1, []).append(si)

    # Connected components of segments, in first-appearance order.
    seen: set[int] = set()
    chains: list[list[int]] = []  # simple open chains of >= 2 segments
    for start in range(len(segs)):
        if start in seen:
            continue
        stack, comp = [start], []
        seen.add(start)
        while stack:
            si = stack.pop()
            comp.append(si)
            for k in (segs[si][1], segs[si][2]):
                for sj in by_vertex[k]:
                    if sj not in seen:
                        seen.add(sj)
                        stack.append(sj)
        if len(comp) < 2:
            continue  # a lone segment is a stray reference line
        degrees = [len(by_vertex[k]) for k in
                   {k for si in comp for k in (segs[si][1], segs[si][2])}]
        # A simple open chain: no vertex on 3+ segments, exactly two ends,
        # and one more vertex than segments (i.e. no cycle).
        if (max(degrees) <= 2 and degrees.count(1) == 2
                and len(degrees) == len(comp) + 1):
            chains.append(comp)

    results: list[tuple[list[Point], list[Lineal]]] = []
    for chain in sorted(chains, key=lambda c: min(segs[si][0] for si in c)):
        # Pick the station-0 end: the chain end written as its segment's
        # point_0 (the save convention); tie/none -> lower-indexed Lineal.
        ends = []  # (end key, its single incident segment, is point_0)
        for si in chain:
            for pos, k in ((0, segs[si][1]), (1, segs[si][2])):
                if len(by_vertex[k]) == 1:
                    ends.append((k, si, pos == 0))
        hinted = [e for e in ends if e[2]]
        pick = hinted if len(hinted) == 1 else ends
        start_key, si, _ = min(pick, key=lambda e: segs[e[1]][0])

        # Walk the chain from station 0, emitting the actual (unrounded)
        # coordinates each segment carries.
        points: list[Point] = []
        used: list[Lineal] = []
        k, remaining = start_key, set(chain)
        while remaining:
            si = next(sj for sj in by_vertex[k] if sj in remaining)
            remaining.discard(si)
            _, k0, k1, p0, p1 = segs[si]
            near, far, k = (p0, p1, k1) if k0 == k else (p1, p0, k0)
            if not points:
                points.append(near)
            points.append(far)
            used.append(lineals[segs[si][0]])
        results.append((points, used))
    return results


def _stray_indices(lineals: Sequence[Lineal]) -> list[int]:
    """Indices of the *stray* Lineals: enabled, two distinct endpoints,
    sharing no endpoint (2-decimal key) with any other usable segment —
    i.e. single-segment components, which the chain reader treats as
    vendor-drawn reference lines rather than centerlines."""
    usable: list[tuple[int, _Key, _Key]] = []
    for i, l in enumerate(lineals):
        if not l.enable or l.point_0 is None or l.point_1 is None:
            continue
        k0, k1 = _key(l.point_0), _key(l.point_1)
        if k0 != k1:
            usable.append((i, k0, k1))
    degree: dict[_Key, int] = {}
    for _, k0, k1 in usable:
        degree[k0] = degree.get(k0, 0) + 1
        degree[k1] = degree.get(k1, 0) + 1
    return [i for i, k0, k1 in usable if degree[k0] == 1 and degree[k1] == 1]


def load_lineals(project: Project) -> list[Lineal]:
    """The project's generic (non-chain stray) Lineals, as fresh working
    copies for the GUI's editable pool — `save_lineals` writes the edited
    set back, mirroring the `load_centerlines`/`save_centerlines` split."""
    return [Lineal(enable=1,
                   point_0=(float(l.point_0[0]), float(l.point_0[1])),
                   point_1=(float(l.point_1[0]), float(l.point_1[1])),
                   extra=dict(l.extra))
            for l in (project.lineals[i] for i in _stray_indices(project.lineals))]


def save_lineals(project: Project, lineals: Sequence[Lineal]) -> list[Lineal]:
    """Write *lineals* as the project's full set of generic strays,
    replacing the previous set in place (placeholder slots first, append
    when the 100-slot array is full — same slot policy as
    `save_centerlines`, whose chains and other components are untouched).

    **Endpoint-coincidence guard:** a stray that shares an endpoint
    (2-decimal key) with any other enabled Lineal — a centerline chain
    vertex, another stray, or an earlier lineal in this same call — would
    be re-read as part of a centerline chain on the next load (see the
    module docstring), so it is *not* written; the skipped Lineals are
    returned for the caller to surface. Zero-length segments are skipped
    for the same reason (unusable geometry). Call this *after*
    `save_centerlines` so the guard sees the final chain vertices.
    Entries without real geometry (placeholders) are ignored.
    """
    for i in _stray_indices(project.lineals):
        slot = project.lineals[i]
        slot.enable = 0
        slot.point_0 = (0.0, 0.0)
        slot.point_1 = (0.0, 0.0)
    taken: set[_Key] = set()
    for l in project.lineals:
        if l.enable and l.point_0 is not None and l.point_1 is not None:
            taken.add(_key(l.point_0))
            taken.add(_key(l.point_1))
    skipped: list[Lineal] = []
    free = (l for l in project.lineals if _is_free_slot(l))
    for lin in lineals:
        if not lin.enable or lin.point_0 is None or lin.point_1 is None:
            continue
        k0, k1 = _key(lin.point_0), _key(lin.point_1)
        if k0 == k1 or k0 in taken or k1 in taken:
            skipped.append(lin)
            continue
        taken.update((k0, k1))
        p0 = (float(lin.point_0[0]), float(lin.point_0[1]))
        p1 = (float(lin.point_1[0]), float(lin.point_1[1]))
        slot = next(free, None)
        if slot is None:
            project.lineals.append(Lineal(enable=1, point_0=p0, point_1=p1))
        else:
            slot.enable = 1
            slot.point_0 = p0
            slot.point_1 = p1
    return skipped


def lineals_to_centerlines(lineals: Sequence[Lineal]) -> list[list[Point]]:
    """Reconstruct every centerline's ordered points from a project's
    Lineals (see module docstring for how they are identified and
    oriented), in file order. [] when the project has none."""
    return [points for points, _ in _find_chains(lineals)]


def load_centerlines(project: Project) -> list[list[Point]]:
    return lineals_to_centerlines(project.lineals)


def save_centerlines(project: Project, centerlines: Sequence[Sequence[Point]]) -> None:
    """Write *centerlines* as the project's full set, replacing the
    previous set in place.

    Every Lineal chain currently encoding a centerline is blanked back to
    placeholder form; the new segments then fill placeholder slots first
    (vendor files keep their fixed 100-slot array) and append only when
    the array is full. Other Lineals — lone reference lines, branching or
    cyclic components, disabled slots with geometry — are untouched.
    Centerlines of fewer than two distinct points are dropped, so passing
    [] deletes them all.
    """
    for _, old in _find_chains(project.lineals):
        for lineal in old:
            lineal.enable = 0
            lineal.point_0 = (0.0, 0.0)
            lineal.point_1 = (0.0, 0.0)
    free = (l for l in project.lineals if _is_free_slot(l))
    for points in centerlines:
        for seg in centerline_to_lineals(points):
            slot = next(free, None)
            if slot is None:
                project.lineals.append(seg)
            else:
                slot.enable = seg.enable
                slot.point_0 = seg.point_0
                slot.point_1 = seg.point_1
