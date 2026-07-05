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


def nearest_edge_insertion(pt: Point, poly: Sequence[Point]) -> tuple[int, Point]:
    """Where a new vertex lands when added to *poly* at the edge nearest
    *pt*: (insertion index into the point list, the clamped projection of
    *pt* onto that edge).

    Edges wrap (last→first) for 3+ points, so a hit on the closing edge
    inserts at the end of the list; a 2-point open polyline has just the
    one segment between its endpoints. A projection that clamps to a
    shared vertex is equidistant from both edges and resolves to the
    lower edge index.
    """
    pts = list(poly)
    n = len(pts)
    if n < 2:
        raise ValueError("nearest_edge_insertion needs at least two points")
    best = (1, pts[0])
    best_d = math.inf
    for i in range(n if n >= 3 else 1):
        a, b = pts[i], pts[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(
            0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / seg2))
        foot = (a[0] + t * dx, a[1] + t * dy)
        d = dist(pt, foot)
        if d < best_d:
            best_d = d
            best = (i + 1, foot)
    return best


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


def _orient(a: Point, b: Point, c: Point) -> float:
    """Cross product (b-a) x (c-a): >0 c left of ab (y-up), <0 right, 0 collinear."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _within_bbox(a: Point, b: Point, c: Point) -> bool:
    """Whether *c* (known collinear with ab) lies within ab's bounding box."""
    return (min(a[0], b[0]) <= c[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= c[1] <= max(a[1], b[1]))


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Whether closed segments ab and cd share any point (touching counts)."""
    o1, o2 = _orient(a, b, c), _orient(a, b, d)
    o3, o4 = _orient(c, d, a), _orient(c, d, b)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    if o1 == 0 and _within_bbox(a, b, c):
        return True
    if o2 == 0 and _within_bbox(a, b, d):
        return True
    if o3 == 0 and _within_bbox(c, d, a):
        return True
    return o4 == 0 and _within_bbox(c, d, b)


def polygon_intersects_rect(poly: Sequence[Point], corner_a: Point,
                            corner_b: Point) -> bool:
    """Whether *poly* touches the axis-aligned rectangle spanned by two
    opposite corners — the marquee-selection hit test. Handles open
    2-point "polygons" (lineal segments) as segments; touching counts."""
    pts = list(poly)
    if not pts:
        return False
    xmin, xmax = sorted((corner_a[0], corner_b[0]))
    ymin, ymax = sorted((corner_a[1], corner_b[1]))
    for x, y in pts:  # any vertex inside the rect
        if xmin <= x <= xmax and ymin <= y <= ymax:
            return True
    if len(pts) == 1:
        return False
    rect = [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]
    edges = zip(pts, pts[1:] + pts[:1]) if len(pts) >= 3 else [(pts[0], pts[1])]
    for e1, e2 in edges:  # any edge crossing a rect edge
        for r1, r2 in zip(rect, rect[1:] + rect[:1]):
            if segments_intersect(e1, e2, r1, r2):
                return True
    # rect entirely inside the polygon
    return len(pts) >= 3 and point_in_polygon(rect[0], pts)


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


def polygon_centroid(poly: Sequence[Point]) -> Point:
    """Area centroid (shoelace formula) — the natural rotation pivot.

    Sign-independent of winding order and of y-down vs y-up. Degenerate
    input (fewer than 3 vertices, or near-zero area such as a collinear
    "polygon") falls back to the vertex mean.
    """
    n = len(poly)
    if n == 0:
        raise ValueError("polygon_centroid needs at least one point")
    if n >= 3:
        a2 = cx = cy = 0.0  # 2*signed area and unnormalized centroid sums
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            cross = x1 * y2 - x2 * y1
            a2 += cross
            cx += (x1 + x2) * cross
            cy += (y1 + y2) * cross
        if abs(a2) > 1e-12:
            return (cx / (3.0 * a2), cy / (3.0 * a2))
    return (sum(x for x, _ in poly) / n, sum(y for _, y in poly) / n)


def rotate_points(
    points: Sequence[Point],
    angle_deg: float,
    pivot: Point | None = None,
) -> list[Point]:
    """Rotate *points* by *angle_deg* around *pivot* (default: the polygon's
    `polygon_centroid`).

    Uses the standard rotation matrix, so a positive angle is CCW in y-up
    math — which renders as *clockwise on screen* in this project's y-down
    world coordinates. Pair with `rotation_angle_deg` (same convention) and
    the rotated shape follows the mouse either way.
    """
    if pivot is None:
        pivot = polygon_centroid(points)
    px, py = pivot
    c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    return [(px + (x - px) * c - (y - py) * s,
             py + (x - px) * s + (y - py) * c) for x, y in points]


def rotation_angle_deg(pivot: Point, from_pt: Point, to_pt: Point) -> float:
    """Signed angle (degrees, (-180, 180]) that carries the ray
    pivot→*from_pt* onto the ray pivot→*to_pt* — the angle to feed
    `rotate_points` in a two-click/drag rotation workflow. Same sign
    convention as `rotate_points`. Returns 0.0 when either point coincides
    with the pivot."""
    ax, ay = from_pt[0] - pivot[0], from_pt[1] - pivot[1]
    bx, by = to_pt[0] - pivot[0], to_pt[1] - pivot[1]
    if (ax == 0 and ay == 0) or (bx == 0 and by == 0):
        return 0.0
    angle = math.degrees(math.atan2(ax * by - ay * bx, ax * bx + ay * by))
    return 180.0 if angle == -180.0 else angle


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


def nearest_centerline(
    centerlines: Sequence["Centerline | None"],
    pt: Point,
    max_offset: float | None = None,
) -> int | None:
    """Index of the centerline whose datum passes nearest *pt* (smallest
    ``|offset|`` from its `project`), or None when none qualifies.

    ``None`` entries (controllers without a usable datum yet) are skipped.
    When *max_offset* is given, a centerline only qualifies if *pt* lies
    within that perpendicular distance of it — the snap threshold that keeps
    template placement from following a centerline the click is nowhere near
    (with *max_offset* None the nearest datum always wins, however far).
    """
    best_i, best_off = None, None
    for i, c in enumerate(centerlines):
        if c is None:
            continue
        off = abs(c.project(pt)[1])
        if max_offset is not None and off > max_offset:
            continue
        if best_off is None or off < best_off:
            best_i, best_off = i, off
    return best_i
