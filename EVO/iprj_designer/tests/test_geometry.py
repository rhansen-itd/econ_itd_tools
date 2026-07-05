import pytest

from model import geometry

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def test_point_segment_distance():
    assert geometry.point_segment_distance((5, 5), (0, 0), (10, 0)) == 5.0
    assert geometry.point_segment_distance((-3, 4), (0, 0), (10, 0)) == 5.0
    assert geometry.point_segment_distance((7, 0), (3, 0), (3, 0)) == 4.0  # degenerate


def test_point_in_polygon():
    assert geometry.point_in_polygon((5, 5), SQUARE)
    assert not geometry.point_in_polygon((15, 5), SQUARE)
    assert not geometry.point_in_polygon((-1, -1), SQUARE)


def test_polygon_hit_tolerance():
    # just outside an edge, within tolerance
    assert not geometry.polygon_hit((10.5, 5.0), SQUARE, tolerance=0.0)
    assert geometry.polygon_hit((10.5, 5.0), SQUARE, tolerance=1.0)
    assert not geometry.polygon_hit((5.0, 5.0), SQUARE[:2], tolerance=5.0)  # not a polygon


def test_snap_points_include_midpoints():
    pts = geometry.snap_points(SQUARE)
    assert (5.0, 0.0) in pts and (10.0, 5.0) in pts
    assert len(pts) == 8
    assert geometry.snap_points(SQUARE, midpoints=False) == SQUARE


def test_find_snap_nearest_and_exclusion():
    other = [(20.0, 0.0), (30.0, 0.0), (30.0, 10.0), (20.0, 10.0)]
    polys = [SQUARE, other]
    # near SQUARE's (10,0) vertex
    assert geometry.find_snap((11.0, 0.5), polys, radius=3.0) == (10.0, 0.0)
    # excluding SQUARE leaves nothing in range
    assert geometry.find_snap((11.0, 0.5), polys, radius=3.0, exclude_index=0) is None
    # out of radius
    assert geometry.find_snap((16.0, 5.0), polys, radius=2.0) is None


def test_translation_to_snap():
    moved = [(10.5, 0.4), (20.5, 0.4), (20.5, 10.4), (10.5, 10.4)]
    corr = geometry.translation_to_snap(moved, [SQUARE, moved], radius=2.0,
                                        exclude_index=1)
    assert corr == pytest.approx((-0.5, -0.4))  # (10.5,0.4) -> (10,0)
    assert geometry.translation_to_snap(moved, [moved], radius=2.0,
                                        exclude_index=0) is None


def test_dimensioned_rect_axis_aligned():
    # aim east, 10 long, extrude 20 toward +y (y-down: south side)
    rect = geometry.dimensioned_rect((0, 0), (1.0, 0.0), 10.0, 20.0,
                                     extrude_toward=(5.0, 50.0))
    assert rect == [(0, 0), (10.0, 0.0), (10.0, 20.0), (0.0, 20.0)]
    # same but mouse on the -y side flips the extrusion
    rect = geometry.dimensioned_rect((0, 0), (1.0, 0.0), 10.0, 20.0,
                                     extrude_toward=(5.0, -50.0))
    assert rect == [(0, 0), (10.0, 0.0), (10.0, -20.0), (0.0, -20.0)]


def test_dimensioned_rect_diagonal_preserves_lengths():
    u = geometry.unit_vector((0, 0), (3.0, 4.0))
    rect = geometry.dimensioned_rect((0, 0), u, 10.0, 20.0,
                                     extrude_toward=(100.0, 0.0))
    assert geometry.dist(rect[0], rect[1]) == pytest.approx(10.0)
    assert geometry.dist(rect[1], rect[2]) == pytest.approx(20.0)
    assert geometry.dist(rect[3], rect[0]) == pytest.approx(20.0)
    # right angles: diagonal matches
    assert geometry.dist(rect[0], rect[2]) == pytest.approx((100 + 400) ** 0.5)


def test_unit_vector_degenerate():
    assert geometry.unit_vector((1, 1), (1, 1)) is None
    assert geometry.unit_vector((0, 0), (0, 2)) == (0.0, 1.0)


# --- station/offset engine (Session 7.1) ---

# east 100, then south (y-down) 50 — an L with the bend at (100, 0)
BEND = geometry.Centerline([(0, 0), (100, 0), (100, 50)])


def test_centerline_stations_and_length():
    assert BEND.stations == [0.0, 100.0, 150.0]
    assert BEND.length == 150.0


def test_centerline_point_at_and_offset_sign():
    assert BEND.point_at(30.0) == (30.0, 0.0)
    # eastbound in y-down: positive offset is screen-down (right of travel)
    assert BEND.point_at(30.0, 5.0) == (30.0, 5.0)
    assert BEND.point_at(30.0, -5.0) == (30.0, -5.0)
    # second segment heads south; right of travel is now -x
    assert BEND.point_at(120.0, 5.0) == (95.0, 20.0)


def test_centerline_locate_returns_direction():
    pt, u = BEND.locate(120.0, 5.0)
    assert pt == (95.0, 20.0)
    assert u == (0.0, 1.0)


def test_centerline_vertex_uses_downstream_segment():
    assert BEND.direction_at(99.9) == (1.0, 0.0)
    assert BEND.direction_at(100.0) == (0.0, 1.0)
    # the final station keeps the last segment's direction
    assert BEND.direction_at(150.0) == (0.0, 1.0)


def test_centerline_extrapolates_past_ends():
    assert BEND.point_at(-10.0) == (-10.0, 0.0)
    assert BEND.direction_at(-10.0) == (1.0, 0.0)
    assert BEND.point_at(160.0) == (100.0, 60.0)


def test_centerline_diagonal_preserves_station_spacing():
    c = geometry.Centerline([(0, 0), (30, 40)])
    assert c.length == 50.0
    assert c.point_at(25.0) == pytest.approx((15.0, 20.0))
    assert geometry.dist(c.point_at(10.0), c.point_at(35.0)) == pytest.approx(25.0)


@pytest.mark.parametrize(
    "station, offset", [(30.0, 5.0), (120.0, -3.0), (0.0, -4.0), (150.0, 2.0)]
)
def test_centerline_project_roundtrips_locate(station, offset):
    s, o = BEND.project(BEND.point_at(station, offset))
    assert (s, o) == pytest.approx((station, offset))


def test_centerline_project_extrapolates_past_ends():
    assert BEND.project((-10.0, 0.0)) == pytest.approx((-10.0, 0.0))
    # past the south end: (110, 60) is 10 upstream-of-nothing, left of travel
    assert BEND.project((110.0, 60.0)) == pytest.approx((160.0, -10.0))


def test_centerline_project_outside_corner():
    # outside the bend both segments' nearest foot is the shared vertex:
    # station is the vertex's, |offset| the distance, sign from segment 1
    # (ties resolve to the lower station), and (104, -3) sits screen-up of
    # eastbound travel = negative side
    assert BEND.project((104.0, -3.0)) == pytest.approx((100.0, -5.0))


def test_centerline_degenerate_points():
    assert geometry.Centerline([(0, 0), (0, 0), (10, 0)]).length == 10.0
    with pytest.raises(ValueError):
        geometry.Centerline([(5, 5)])
    with pytest.raises(ValueError):
        geometry.Centerline([(3, 3), (3, 3)])


def test_offset_normal():
    assert geometry.offset_normal((1.0, 0.0)) == (0.0, 1.0)
    assert geometry.offset_normal((0.0, 1.0)) == (-1.0, 0.0)


# -- rotation (Phase 2) --------------------------------------------------------

def test_polygon_centroid_square():
    assert geometry.polygon_centroid(SQUARE) == pytest.approx((5.0, 5.0))


def test_polygon_centroid_winding_independent():
    assert geometry.polygon_centroid(list(reversed(SQUARE))) == pytest.approx((5.0, 5.0))


def test_polygon_centroid_area_weighted_not_vertex_mean():
    # L-shape: 2x1 rect (area 2, centroid (1, .5)) + 1x1 on top (centroid
    # (.5, 1.5)) -> area-weighted centroid (5/6, 5/6); the vertex mean is 1
    lshape = [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)]
    assert geometry.polygon_centroid(lshape) == pytest.approx((5 / 6, 5 / 6))


def test_polygon_centroid_degenerate_falls_back_to_mean():
    collinear = [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)]
    assert geometry.polygon_centroid(collinear) == pytest.approx((5.0, 0.0))
    assert geometry.polygon_centroid([(2.0, 4.0)]) == (2.0, 4.0)
    assert geometry.polygon_centroid([(0.0, 0.0), (4.0, 2.0)]) == pytest.approx((2.0, 1.0))
    with pytest.raises(ValueError):
        geometry.polygon_centroid([])


def test_rotate_points_about_explicit_pivot():
    # +90 deg about the origin maps (10,0)->(0,10): screen-clockwise in y-down
    rot = geometry.rotate_points([(10.0, 0.0)], 90.0, pivot=(0.0, 0.0))
    assert rot[0] == pytest.approx((0.0, 10.0))


def test_rotate_points_default_pivot_is_centroid():
    rot = geometry.rotate_points(SQUARE, 90.0)
    assert geometry.polygon_centroid(rot) == pytest.approx((5.0, 5.0))
    # square rotated 90 about its center is the same square, corners cycled
    for p, q in zip(rot, SQUARE[1:] + SQUARE[:1]):
        assert p == pytest.approx(q, abs=1e-9)


def test_rotate_points_roundtrip():
    poly = [(1.0, 2.0), (8.0, 3.0), (7.0, 9.0), (2.0, 7.0)]
    back = geometry.rotate_points(geometry.rotate_points(poly, 37.0), -37.0)
    for p, q in zip(back, poly):
        assert p == pytest.approx(q)


def test_rotation_angle_deg_signs_and_edges():
    pivot = (5.0, 5.0)
    assert geometry.rotation_angle_deg(pivot, (10.0, 5.0), (5.0, 10.0)) == pytest.approx(90.0)
    assert geometry.rotation_angle_deg(pivot, (5.0, 10.0), (10.0, 5.0)) == pytest.approx(-90.0)
    assert geometry.rotation_angle_deg(pivot, (10.0, 5.0), (0.0, 5.0)) == pytest.approx(180.0)
    assert geometry.rotation_angle_deg(pivot, pivot, (10.0, 5.0)) == 0.0
    # magnitude is radius-independent
    assert geometry.rotation_angle_deg(pivot, (6.0, 5.0), (5.0, 95.0)) == pytest.approx(90.0)


def test_rotation_angle_feeds_rotate_points():
    # the 2-click workflow: grab at `frm`, drag to `to`; rotating by the
    # measured angle must carry `frm` onto the ray pivot->`to`
    pivot, frm, to = (3.0, 4.0), (9.0, 4.0), (3.0, -2.0)
    ang = geometry.rotation_angle_deg(pivot, frm, to)
    moved = geometry.rotate_points([frm], ang, pivot=pivot)[0]
    assert moved == pytest.approx((3.0, -2.0))


# -- marquee hit test (Phase 3.2a) ---------------------------------------------

def test_segments_intersect_crossing_and_disjoint():
    assert geometry.segments_intersect((0, 0), (10, 10), (0, 10), (10, 0))
    assert not geometry.segments_intersect((0, 0), (10, 0), (0, 5), (10, 5))


def test_segments_intersect_touching_and_collinear():
    assert geometry.segments_intersect((0, 0), (10, 0), (10, 0), (10, 10))
    assert geometry.segments_intersect((0, 0), (10, 0), (5, 0), (15, 0))
    assert not geometry.segments_intersect((0, 0), (10, 0), (11, 0), (20, 0))


BIG_SQUARE = [(0, 0), (40, 0), (40, 40), (0, 40)]


def test_marquee_vertex_inside_rect():
    assert geometry.polygon_intersects_rect(BIG_SQUARE, (-5, -5), (5, 5))


def test_marquee_corners_may_come_in_any_order():
    assert geometry.polygon_intersects_rect(BIG_SQUARE, (5, 5), (-5, -5))


def test_marquee_edge_crossing_without_vertex_inside():
    # thin rect slicing through the square's middle: no vertex containment
    assert geometry.polygon_intersects_rect(BIG_SQUARE, (-10, 15), (50, 25))


def test_marquee_rect_entirely_inside_polygon():
    assert geometry.polygon_intersects_rect(BIG_SQUARE, (10, 10), (30, 30))


def test_marquee_disjoint():
    assert not geometry.polygon_intersects_rect(BIG_SQUARE, (100, 100), (150, 150))


def test_marquee_touching_edge_counts():
    assert geometry.polygon_intersects_rect(BIG_SQUARE, (40, 10), (60, 30))


def test_marquee_two_point_segment():
    seg = [(0, 0), (100, 100)]
    assert geometry.polygon_intersects_rect(seg, (40, 20), (60, 80))
    assert not geometry.polygon_intersects_rect(seg, (60, 0), (100, 30))
    assert not geometry.polygon_intersects_rect([], (0, 0), (10, 10))


# -- vertex insertion (ROADMAP Item 5) -------------------------------------------

def test_nearest_edge_insertion_projects_onto_nearest_edge():
    # outside the bottom edge (y-down: the (0,0)->(10,0) side)
    assert geometry.nearest_edge_insertion((5.0, -3.0), SQUARE) == (1, (5.0, 0.0))
    # from inside, nearest the right edge
    assert geometry.nearest_edge_insertion((9.0, 5.0), SQUARE) == (2, (10.0, 5.0))


def test_nearest_edge_insertion_closing_edge_appends():
    # nearest the wrap-around edge (0,10)->(0,0): insert index is len(poly)
    assert geometry.nearest_edge_insertion((-3.0, 5.0), SQUARE) == (4, (0.0, 5.0))


def test_nearest_edge_insertion_clamps_to_vertex_lower_edge_wins():
    # beyond the (10,0) corner both adjacent edges clamp to that vertex;
    # the tie resolves to the lower edge index
    assert geometry.nearest_edge_insertion((13.0, -2.0), SQUARE) == (1, (10.0, 0.0))


def test_nearest_edge_insertion_two_point_open_segment():
    seg = [(0.0, 0.0), (10.0, 0.0)]
    assert geometry.nearest_edge_insertion((4.0, 3.0), seg) == (1, (4.0, 0.0))
    # no closing edge on a 2-point polyline: beyond the start still inserts at 1
    assert geometry.nearest_edge_insertion((-5.0, 0.0), seg) == (1, (0.0, 0.0))


def test_nearest_edge_insertion_degenerate():
    # coincident points: distance ties at the shared vertex, index 1 wins
    assert geometry.nearest_edge_insertion(
        (5.0, 5.0), [(2.0, 2.0), (2.0, 2.0), (2.0, 2.0)]) == (1, (2.0, 2.0))
    with pytest.raises(ValueError):
        geometry.nearest_edge_insertion((0.0, 0.0), [(1.0, 1.0)])
