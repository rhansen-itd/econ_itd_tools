"""Planar geometry for drawing and editing zones — pure python, no GUI.

All functions are unit-agnostic (callers pass world pixels); y-down vs y-up
does not matter for any of the math here except the *side* conventions of
`dimensioned_rect` (resolved by an explicit point rather than a sign
convention) and the offset sign of the `Centerline` station/offset engine
(documented on the class in y-down terms).
"""

from __future__ import annotations

import bisect
import math
from typing import Iterable, Sequence

from .iprj_io import Point


def dist(p: Point, q: Point) -> float:
    return math.dist(p, q)


def point_segment_distance(pt: Point, a: Point, b: Point) -> float:
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    if dx == 0 and dy == 0:
        return dist(pt, a)
    t = ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return dist(pt, (ax + t * dx, ay + t * dy))


def point_in_polygon(pt: Point, poly: Sequence[Point]) -> bool:
    """Ray-casting test; points exactly on an edge may fall either way."""
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def polygon_hit(pt: Point, poly: Sequence[Point], tolerance: float = 0.0) -> bool:
    """Whether *pt* lands on the polygon body (inside, or within
    *tolerance* of an edge — so thin zones stay clickable)."""
    if len(poly) < 3:
        return False
    if point_in_polygon(pt, poly):
        return True
    if tolerance > 0:
        n = len(poly)
        for i in range(n):
            if point_segment_distance(pt, poly[i], poly[(i + 1) % n]) <= tolerance:
                return True
    return False


def snap_points(poly: Sequence[Point], midpoints: bool = True) -> list[Point]:
    """Snap candidates a polygon offers: its vertices, plus edge midpoints
    (useful when butting a loop against the middle of a neighbor's edge)."""
    pts = list(poly)
    if midpoints and len(poly) >= 2:
        n = len(poly)
        for i in range(n):
            a, b = poly[i], poly[(i + 1) % n]
            pts.append(((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0))
    return pts


def find_snap(
    pt: Point,
    polygons: Iterable[Sequence[Point]],
    radius: float,
    exclude_index: int | None = None,
    midpoints: bool = True,
) -> Point | None:
    """Nearest snap candidate of any *other* polygon within *radius*."""
    best = None
    best_d = radius
    for i, poly in enumerate(polygons):
        if i == exclude_index:
            continue
        for cand in snap_points(poly, midpoints):
            d = dist(pt, cand)
            if d < best_d:
                best_d, best = d, cand
    return best


def translation_to_snap(
    points: Sequence[Point],
    polygons: Iterable[Sequence[Point]],
    radius: float,
    exclude_index: int | None = None,
    midpoints: bool = True,
) -> Point | None:
    """(dx, dy) that snaps the best-matching vertex of *points* onto a
    neighboring polygon's snap candidate, or None if none is in range."""
    polygons = list(polygons)
    best_d = radius
    correction = None
    for p in points:
        target = find_snap(p, polygons, radius, exclude_index, midpoints)
        if target is not None:
            d = dist(p, target)
            if d < best_d:
                best_d = d
                correction = (target[0] - p[0], target[1] - p[1])
    return correction


def unit_vector(a: Point, b: Point) -> Point | None:
    """Unit vector from a toward b, or None if the points coincide."""
    d = dist(a, b)
    if d <= 0:
        return None
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d)


def dimensioned_rect(
    origin: Point,
    direction: Point,
    length1: float,
    length2: float,
    extrude_toward: Point,
) -> list[Point]:
    """Rectangle from one corner, an aim direction, and two side lengths.

    The first side runs *length1* from *origin* along *direction* (a unit
    vector); the rectangle is then extruded *length2* perpendicular to that
    side, on whichever side *extrude_toward* lies (defaults to the
    counter-clockwise normal when the point is on the line).

    Returns the four corners in drawing order starting at *origin*.
    """
    ux, uy = direction
    nx, ny = -uy, ux
    side = (extrude_toward[0] - origin[0]) * nx + (extrude_toward[1] - origin[1]) * ny
    if side < 0:
        nx, ny = -nx, -ny
    p2 = (origin[0] + length1 * ux, origin[1] + length1 * uy)
    return [
        origin,
        p2,
        (p2[0] + length2 * nx, p2[1] + length2 * ny),
        (origin[0] + length2 * nx, origin[1] + length2 * ny),
    ]


def offset_normal(direction: Point) -> Point:
    """Unit normal along which positive `Centerline` offsets lie:
    *direction* (a unit vector) rotated 90° so that in y-down world space
    it points to the right of travel (the CCW/left normal in y-up math)."""
    return (-direction[1], direction[0])


class Centerline:
    """Station/offset datum over a point-to-point polyline (no arcs).

    Station 0 is at the first point and grows along the line to ``length``
    at the last. Coordinates are whatever unit the caller works in (world
    px, feet); stations and offsets come back in that same unit. Positive
    offsets lie along `offset_normal` of the local direction — the right
    side of travel in y-down world space.

    Stations beyond either end extrapolate along the terminal segments, so
    a datum drawn a little short still places far-upstream detectors.
    Orientation is per-segment with no corner blending; a station exactly
    on an interior vertex takes the downstream segment's direction.
    """

    def __init__(self, points: Sequence[Point]) -> None:
        pts: list[Point] = []
        for p in points:
            q = (float(p[0]), float(p[1]))
            if not pts or q != pts[-1]:
                pts.append(q)
        if len(pts) < 2:
            raise ValueError("Centerline needs at least two distinct points")
        self.points = pts
        self.stations = [0.0]
        for a, b in zip(pts, pts[1:]):
            self.stations.append(self.stations[-1] + dist(a, b))

    @property
    def length(self) -> float:
        return self.stations[-1]

    def _segment(self, station: float) -> int:
        i = bisect.bisect_right(self.stations, station) - 1
        return max(0, min(i, len(self.points) - 2))

    def direction_at(self, station: float) -> Point:
        """Unit tangent (direction of increasing station) at *station*."""
        i = self._segment(station)
        return unit_vector(self.points[i], self.points[i + 1])

    def locate(self, station: float, offset: float = 0.0) -> tuple[Point, Point]:
        """(point, unit tangent) at *station*/*offset*."""
        i = self._segment(station)
        a = self.points[i]
        ux, uy = unit_vector(self.points[i], self.points[i + 1])
        nx, ny = offset_normal((ux, uy))
        s = station - self.stations[i]
        return (a[0] + s * ux + offset * nx, a[1] + s * uy + offset * ny), (ux, uy)

    def point_at(self, station: float, offset: float = 0.0) -> Point:
        return self.locate(station, offset)[0]

    def project(self, pt: Point) -> tuple[float, float]:
        """(station, offset) of the polyline point nearest *pt* — the
        inverse of `locate`, including the beyond-the-ends extrapolation
        (the end segments extend to infinity; interior projections clamp
        to their segment).

        Where the nearest foot is a clamped vertex, |offset| is the
        distance to that vertex, signed by which side of that segment *pt*
        lies. Equidistant candidates (the concave side of a corner)
        resolve to the lower station.
        """
        best = (0.0, 0.0)
        best_d = math.inf
        last = len(self.points) - 2
        for i in range(last + 1):
            a, b = self.points[i], self.points[i + 1]
            dx, dy = b[0] - a[0], b[1] - a[1]
            seg_len2 = dx * dx + dy * dy
            t = ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / seg_len2
            if i > 0:
                t = max(0.0, t)
            if i < last:
                t = min(1.0, t)
            foot = (a[0] + t * dx, a[1] + t * dy)
            d = dist(pt, foot)
            if d < best_d:
                best_d = d
                cross = dx * (pt[1] - foot[1]) - dy * (pt[0] - foot[0])
                station = self.stations[i] + t * math.sqrt(seg_len2)
                best = (station, d if cross >= 0 else -d)
        return best
