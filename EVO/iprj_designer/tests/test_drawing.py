import pytest

from gui.drawing import (DIM_LENGTH1, DIM_LENGTH2, DIM_OFF, CenterlineController,
                         DrawingController, bumped_name, derive_attachments,
                         is_placeholder, next_output_number)
from model import geometry
from model.iprj_io import EventZone

FT_PER_PX = 0.25  # 10 ft == 40 world px


def make_ctrl(zones=None, calibrated=True, numbered=False):
    zones = zones if zones is not None else []
    ctrl = DrawingController(
        zones, lambda: FT_PER_PX if calibrated else None,
        next_output=(lambda: next_output_number([zones])) if numbered else None)
    return ctrl


def square(x=0.0, y=0.0, size=40.0, name="Z"):
    return EventZone(enable=1, zone_name=name, points=[
        (x, y), (x + size, y), (x + size, y + size), (x, y + size)])


# -- free draw ---------------------------------------------------------------

def test_free_draw_four_clicks_commits_loop():
    ctrl = make_ctrl()
    for p in [(0, 0), (40, 0), (40, 40), (0, 40)]:
        ctrl.mouse_down(p)
    assert len(ctrl.zones) == 1
    assert ctrl.zones[0].points == [(0, 0), (40, 0), (40, 40), (0, 40)]
    assert ctrl.zones[0].enable == 1
    assert ctrl.pending == []


def test_point_level_undo_while_drawing():
    ctrl = make_ctrl()
    ctrl.mouse_down((0, 0))
    ctrl.mouse_down((40, 0))
    ctrl.undo()
    assert ctrl.pending == [(0, 0)]
    ctrl.undo()
    assert ctrl.pending == []


def test_shape_level_undo_after_commit():
    ctrl = make_ctrl()
    for p in [(0, 0), (40, 0), (40, 40), (0, 40)]:
        ctrl.mouse_down(p)
    ctrl.undo()
    assert ctrl.zones == []


def test_escape_clears_pending():
    ctrl = make_ctrl()
    ctrl.mouse_down((0, 0))
    assert ctrl.key("Escape")
    assert ctrl.pending == []


# -- dimensioned draw --------------------------------------------------------

def test_dimensioned_rectangle_east_extrude_south():
    ctrl = make_ctrl()
    ctrl.mouse_down((100, 100))
    ctrl.mouse_move((200, 100))          # aim due east
    assert ctrl.key("1") and ctrl.dim_stage == DIM_LENGTH1
    ctrl.key("0")                        # buffer "10"
    assert ctrl.key("Enter") and ctrl.dim_stage == DIM_LENGTH2
    ctrl.mouse_move((150, 300))          # mouse below: extrude toward +y
    ctrl.key("2")
    ctrl.key("0")
    ctrl.key("Enter")
    assert len(ctrl.zones) == 1
    assert ctrl.zones[0].points == pytest.approx(
        [(100, 100), (140, 100), (140, 180), (100, 180)])
    assert ctrl.dim_stage == DIM_OFF and ctrl.pending == []


def test_dimensioned_rectangle_extrude_side_follows_mouse():
    ctrl = make_ctrl()
    ctrl.mouse_down((100, 100))
    ctrl.mouse_move((200, 100))
    ctrl.key("d")
    for k in "10":
        ctrl.key(k)
    ctrl.key("Enter")
    ctrl.mouse_move((150, 50))           # mouse above: extrude toward -y
    for k in "20":
        ctrl.key(k)
    ctrl.key("Enter")
    assert ctrl.zones[0].points == pytest.approx(
        [(100, 100), (140, 100), (140, 20), (100, 20)])


def test_direction_frozen_when_first_length_committed():
    ctrl = make_ctrl()
    ctrl.mouse_down((0, 0))
    ctrl.mouse_move((100, 0))
    ctrl.key("d")
    for k in "10":
        ctrl.key(k)
    ctrl.key("Enter")
    ctrl.mouse_move((0, 100))            # aiming elsewhere must not swing side 1
    for k in "20":
        ctrl.key(k)
    ctrl.key("Enter")
    assert ctrl.zones[0].points[1] == pytest.approx((40, 0))


def test_dimension_entry_requires_calibration():
    ctrl = make_ctrl(calibrated=False)
    ctrl.mouse_down((0, 0))
    ctrl.mouse_move((100, 0))
    assert ctrl.key("1")
    assert ctrl.dim_stage == DIM_OFF
    assert "calibrate" in ctrl.message


def test_dimension_entry_backspace_and_escape():
    ctrl = make_ctrl()
    ctrl.mouse_down((0, 0))
    ctrl.mouse_move((100, 0))
    ctrl.key("1")
    ctrl.key("5")
    ctrl.key("Backspace")
    assert ctrl.dim_buffer == "1"
    ctrl.key("Escape")
    assert ctrl.dim_stage == DIM_OFF
    assert ctrl.pending == [(0, 0)]      # first corner survives one Escape


def test_dimension_preview_rectangle():
    ctrl = make_ctrl()
    ctrl.mouse_down((0, 0))
    ctrl.mouse_move((100, 0))
    ctrl.key("d")
    for k in "10":
        ctrl.key(k)
    prev = ctrl.preview_polygon()
    assert prev == [(0, 0), pytest.approx((40, 0))]
    ctrl.key("Enter")
    ctrl.mouse_move((50, 100))
    for k in "20":
        ctrl.key(k)
    prev = ctrl.preview_polygon()
    assert prev == pytest.approx([(0, 0), (40, 0), (40, 80), (0, 80)])


# -- snapping ----------------------------------------------------------------

def test_click_snaps_to_other_zone_vertex():
    ctrl = make_ctrl([square(0, 0)])
    ctrl.key("g")
    assert ctrl.snap_enabled
    ctrl.snap_radius = 12.0
    ctrl.mouse_down((45, 3))             # near (40, 0)
    assert ctrl.pending == [(40.0, 0.0)]


def test_snap_to_edge_midpoint():
    ctrl = make_ctrl([square(0, 0)])
    ctrl.key("g")
    ctrl.mouse_down((42, 22))            # near right-edge midpoint (40, 20)
    assert ctrl.pending == [(40.0, 20.0)]


def test_snap_off_by_default_and_toggles():
    ctrl = make_ctrl([square(0, 0)])
    ctrl.mouse_down((45, 3))
    assert ctrl.pending == [(45, 3)]
    ctrl.key("g")
    ctrl.key("g")
    assert not ctrl.snap_enabled


# -- edit mode ---------------------------------------------------------------

def test_edit_select_and_cycle():
    ctrl = make_ctrl([square(0, 0, name="A"), square(100, 0, name="B")])
    ctrl.set_mode("edit")
    assert ctrl.selected == 1            # last zone preselected
    ctrl.key("n")
    assert ctrl.selected == 0
    ctrl.key("b")
    assert ctrl.selected == 1
    ctrl.mouse_down((20, 20))            # click body of A
    ctrl.mouse_up((20, 20))
    assert ctrl.selected == 0


def test_edit_drag_body_moves_zone():
    ctrl = make_ctrl([square(0, 0)])
    ctrl.set_mode("edit")
    ctrl.mouse_down((20, 20))
    ctrl.mouse_move((30, 25), dragging=True)
    ctrl.mouse_up((30, 25))
    assert ctrl.zones[0].points == [(10, 5), (50, 5), (50, 45), (10, 45)]
    ctrl.undo()
    assert ctrl.zones[0].points == [(0, 0), (40, 0), (40, 40), (0, 40)]


def test_edit_drag_vertex():
    ctrl = make_ctrl([square(0, 0)])
    ctrl.set_mode("edit")
    ctrl.handle_radius = 5.0
    ctrl.mouse_down((1, 1))              # grab vertex (0, 0)
    ctrl.mouse_move((-10, -10), dragging=True)
    ctrl.mouse_up((-10, -10))
    assert ctrl.zones[0].points[0] == (-10, -10)
    ctrl.undo()
    assert ctrl.zones[0].points[0] == (0, 0)


def test_edit_ctrl_drag_copies():
    ctrl = make_ctrl([square(0, 0, name="A")])
    ctrl.set_mode("edit")
    ctrl.mouse_down((20, 20), ctrl=True)
    ctrl.mouse_move((70, 20), dragging=True)
    ctrl.mouse_up((70, 20))
    assert len(ctrl.zones) == 2
    assert ctrl.zones[0].points == [(0, 0), (40, 0), (40, 40), (0, 40)]  # original untouched
    assert ctrl.zones[1].points == [(50, 0), (90, 0), (90, 40), (50, 40)]
    assert ctrl.selected == 1
    ctrl.undo()
    assert len(ctrl.zones) == 1


def test_body_drag_snaps_on_release():
    ctrl = make_ctrl([square(0, 0), square(100, 0)])
    ctrl.set_mode("edit")
    ctrl.snap_enabled = True
    ctrl.snap_radius = 12.0
    ctrl.mouse_down((120, 20))           # body of second square
    ctrl.mouse_move((65, 22), dragging=True)   # left edge lands near (45, 2)
    ctrl.mouse_up((65, 22))
    # snapped flush against the first square: (45,2) -> (40,0)
    assert ctrl.zones[1].points[0] == pytest.approx((40.0, 0.0))


def test_delete_and_undo_restore():
    ctrl = make_ctrl([square(0, 0, name="A"), square(100, 0, name="B")])
    ctrl.set_mode("edit")
    ctrl.key("n")                        # select A (index 0)
    assert ctrl.selected == 0
    ctrl.key("x")
    assert [z.zone_name for z in ctrl.zones] == ["B"]
    ctrl.undo()
    assert [z.zone_name for z in ctrl.zones] == ["A", "B"]
    assert ctrl.selected == 0


# -- attributes & numbering (Session 4) ---------------------------------------

def draw_square(ctrl, x=0, y=0, size=40):
    for p in [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]:
        ctrl.mouse_down(p)


def test_output_autoincrements_on_draw():
    zones = [square(0, 0)]
    zones[0].output_number = 33
    ctrl = make_ctrl(zones, numbered=True)
    draw_square(ctrl, 100, 0)
    draw_square(ctrl, 200, 0)
    assert [z.output_number for z in zones[1:]] == [34, 35]


def test_copy_bumps_output_and_trailing_number():
    zones = [square(0, 0, name="SBT Count 1")]
    zones[0].output_number = 34
    ctrl = make_ctrl(zones, numbered=True)
    ctrl.set_mode("edit")
    ctrl.mouse_down((20, 20), ctrl=True)
    ctrl.mouse_move((70, 20), dragging=True)
    ctrl.mouse_up((70, 20))
    assert zones[1].zone_name == "SBT Count 2"
    assert zones[1].output_number == 35


def test_bumped_name():
    assert bumped_name("SBT Count 1") == "SBT Count 2"
    assert bumped_name("Zone 9") == "Zone 10"
    assert bumped_name("Ph 4 Dilemma") == "Ph 4 Dilemma"
    assert bumped_name(None) == ""


def test_commit_fills_placeholder_slot_and_undo_restores_it():
    placeholder = EventZone(enable=0, zone_name="")
    zones = [placeholder, square(100, 0, name="real")]
    ctrl = make_ctrl(zones)
    draw_square(ctrl)
    assert len(zones) == 2                    # replaced, not appended
    assert zones[0].points and zones[0].enable
    ctrl.undo()
    assert zones[0] is placeholder
    assert is_placeholder(zones[0])


def test_cycle_and_preselect_skip_placeholders():
    zones = [EventZone(enable=0), square(0, 0, name="A"),
             EventZone(enable=0), square(100, 0, name="B"), EventZone(enable=0)]
    ctrl = make_ctrl(zones)
    ctrl.set_mode("edit")
    assert ctrl.selected == 3                 # last real zone
    ctrl.key("n")
    assert ctrl.selected == 1
    ctrl.key("n")
    assert ctrl.selected == 3


def test_next_output_ignores_placeholders():
    zones_a = [EventZone(enable=0), square(0, 0)]
    zones_a[1].output_number = 40
    zones_b = [square(100, 0)]
    zones_b[0].output_number = 17
    assert next_output_number([zones_a, zones_b]) == 41
    assert next_output_number([[]]) == 1


def test_retarget_switches_list_and_undo_survives():
    zones_a, zones_b = [], []
    ctrl = make_ctrl(zones_a)
    draw_square(ctrl)
    ctrl.retarget(zones_b)
    draw_square(ctrl, 100, 0)
    assert len(zones_a) == 1 and len(zones_b) == 1
    ctrl.undo()                               # undoes the add in zones_b
    assert zones_b == []
    ctrl.undo()                               # reaches back across the retarget
    assert zones_a == []


# -- arrow-key nudge (Session 5) ---------------------------------------------

def test_nudge_moves_selected_zone_by_calibrated_step():
    ctrl = make_ctrl([square(0, 0)])   # FT_PER_PX = 0.25 -> 0.5 ft == 2 px
    ctrl.set_mode("edit")
    assert ctrl.key("ArrowRight")
    assert ctrl.zones[0].points == pytest.approx(
        [(2, 0), (42, 0), (42, 40), (2, 40)])
    ctrl.key("ArrowDown")
    assert ctrl.zones[0].points == pytest.approx(
        [(2, 2), (42, 2), (42, 42), (2, 42)])


def test_nudge_uncalibrated_falls_back_to_fixed_px_step():
    ctrl = make_ctrl([square(0, 0)], calibrated=False)
    ctrl.set_mode("edit")
    ctrl.key("ArrowLeft")
    assert ctrl.zones[0].points[0] == pytest.approx((-2, 0))


def test_nudge_burst_coalesces_into_one_undo_step():
    ctrl = make_ctrl([square(0, 0)])
    ctrl.set_mode("edit")
    ctrl.key("ArrowRight")
    ctrl.key("ArrowRight")
    ctrl.key("ArrowDown")
    assert ctrl.zones[0].points[0] == pytest.approx((4, 2))
    ctrl.undo()
    assert ctrl.zones[0].points[0] == (0, 0)


def test_nudge_then_other_action_starts_a_new_undo_step():
    ctrl = make_ctrl([square(0, 0), square(100, 0)])
    ctrl.set_mode("edit")
    ctrl.key("n")                        # select first zone
    ctrl.key("ArrowRight")
    ctrl.key("n")                        # a different key breaks the coalesce
    ctrl.key("b")
    ctrl.key("ArrowRight")
    ctrl.undo()
    assert ctrl.zones[0].points[0] == pytest.approx((2, 0))  # only 2nd nudge undone


def test_nudge_without_selection_is_a_noop():
    ctrl = make_ctrl([square(0, 0)])
    ctrl.set_mode("edit")
    ctrl.selected = -1
    assert not ctrl.key("ArrowRight")


def test_status_line_reports_state():
    ctrl = make_ctrl()
    assert "draw" in ctrl.status()
    ctrl.mouse_down((0, 0))
    ctrl.mouse_move((10, 0))
    ctrl.key("1")
    assert "side 1" in ctrl.status()
    ctrl.key("Enter")
    assert "side 2" in ctrl.status()
    ctrl.key("Escape")
    ctrl.set_mode("edit")
    assert "edit" in ctrl.status()


# -- centerline (Session 7.2) -------------------------------------------------

def make_cl(calibrated=True):
    return CenterlineController(lambda: FT_PER_PX if calibrated else None)


def test_click_extends_the_polyline():
    ctrl = make_cl()
    ctrl.mouse_down((0, 0))
    ctrl.mouse_down((100, 0))
    ctrl.mouse_down((100, 50))
    assert ctrl.points == [(0, 0), (100, 0), (100, 50)]
    assert ctrl.selected == 2


def test_click_drag_positions_new_vertex_before_release():
    ctrl = make_cl()
    ctrl.mouse_down((0, 0))
    ctrl.mouse_move((5, 5), dragging=True)   # settle the first point
    ctrl.mouse_up((5, 5))
    ctrl.mouse_down((100, 0))
    ctrl.mouse_move((100, 40), dragging=True)
    ctrl.mouse_up((100, 40))
    assert ctrl.points == [(5, 5), (100, 40)]


def test_click_near_existing_vertex_selects_and_drags_it():
    ctrl = make_cl()
    ctrl.mouse_down((0, 0))
    ctrl.mouse_down((100, 0))
    ctrl.handle_radius = 5.0
    ctrl.mouse_down((1, 1))              # grabs the first vertex, not a new one
    ctrl.mouse_move((-10, -10), dragging=True)
    ctrl.mouse_up((-10, -10))
    assert ctrl.points == [(-10, -10), (100, 0)]
    assert ctrl.selected == 0


def test_delete_selected_vertex_and_undo():
    ctrl = make_cl()
    for p in [(0, 0), (100, 0), (100, 50)]:
        ctrl.mouse_down(p)
    ctrl.selected = 1
    assert ctrl.key("x")
    assert ctrl.points == [(0, 0), (100, 50)]
    ctrl.undo()
    assert ctrl.points == [(0, 0), (100, 0), (100, 50)]


def test_delete_without_selection_is_a_noop():
    ctrl = make_cl()
    ctrl.selected = -1
    assert not ctrl.key("x")
    assert "select" in ctrl.message


def test_escape_deselects():
    ctrl = make_cl()
    ctrl.mouse_down((0, 0))
    assert ctrl.selected == 0
    assert ctrl.key("Escape")
    assert ctrl.selected == -1
    assert not ctrl.key("Escape")  # nothing left to back out of


def test_station_readout_none_before_two_points():
    ctrl = make_cl()
    assert ctrl.station_readout((0, 0)) is None
    ctrl.mouse_down((0, 0))
    assert ctrl.station_readout((5, 5)) is None


def test_station_readout_reports_feet_and_side():
    ctrl = make_cl()   # FT_PER_PX = 0.25 -> 4 world px == 1 ft
    ctrl.mouse_down((0, 0))
    ctrl.mouse_down((100, 0))
    assert ctrl.station_readout((40, 4)) == "station 10.0 ft, offset 1.0 ft R"
    assert ctrl.station_readout((40, -4)) == "station 10.0 ft, offset 1.0 ft L"


def test_station_readout_falls_back_to_px_uncalibrated():
    ctrl = make_cl(calibrated=False)
    ctrl.mouse_down((0, 0))
    ctrl.mouse_down((100, 0))
    assert ctrl.station_readout((40, 4)) == "station 40.0 px, offset +4.0 px"


def test_centerline_status_messages():
    ctrl = make_cl()
    assert "station 0" in ctrl.status()
    ctrl.mouse_down((0, 0))
    assert "1 point" in ctrl.status()
    ctrl.mouse_down((100, 0))
    assert "2 points" in ctrl.status()


# -- centerline zone attachments (Session 7.5) --------------------------------

def cl_with_zone():
    """A straight centerline (0,0)->(100,0) with a 10x10 zone attached at
    stations 20..30, offsets 0..-10 (its placed points coincide)."""
    ctrl = make_cl()
    ctrl.mouse_down((0, 0))
    ctrl.mouse_down((100, 0))
    corners = [(20.0, 0.0), (20.0, -10.0), (30.0, -10.0), (30.0, 0.0)]
    zone = EventZone(enable=1, zone_name="A",
                     points=[(20, 0), (20, -10), (30, -10), (30, 0)])
    ctrl.attach(zone, corners)
    return ctrl, zone


def test_attached_zone_restations_on_vertex_drag_and_undo():
    ctrl, zone = cl_with_zone()
    orig = list(zone.points)
    # drag the stop-bar vertex 50 px back: every station shifts with it
    ctrl.mouse_down((0, 0))                    # grabs vertex 0
    ctrl.mouse_move((-50, 0), dragging=True)   # re-stations live
    ctrl.mouse_up((-50, 0))
    assert zone.points == [(-30, 0), (-30, -10), (-20, -10), (-20, 0)]
    ctrl.undo()  # snapshot restore re-stations too
    assert zone.points == orig


def test_attached_zone_follows_a_bend():
    ctrl, zone = cl_with_zone()
    # bend the far end down: the zone re-locates via the datum engine
    ctrl.mouse_down((100, 0))
    ctrl.mouse_move((100, 100), dragging=True)
    ctrl.mouse_up((100, 100))
    datum = geometry.Centerline(ctrl.points)
    expected = [datum.point_at(s, off)
                for s, off in [(20, 0), (20, -10), (30, -10), (30, 0)]]
    for (x, y), (ex, ey) in zip(zone.points, expected):
        assert x == pytest.approx(ex)
        assert y == pytest.approx(ey)


def test_reproject_keeps_manual_adjustment_through_later_edits():
    ctrl, zone = cl_with_zone()
    # the user slides the zone 5 px upstream; the GUI then reprojects
    zone.points = [(x + 5, y) for x, y in zone.points]
    ctrl.reproject()
    # a later centerline edit re-stations from the adjusted coords
    ctrl.mouse_down((0, 0))
    ctrl.mouse_move((-50, 0), dragging=True)
    ctrl.mouse_up((-50, 0))
    assert zone.points == [(-25, 0), (-25, -10), (-15, -10), (-15, 0)]


def test_reproject_untouched_zone_keeps_exact_placement_coords():
    ctrl, zone = cl_with_zone()
    corners = list(ctrl.attached[id(zone)][1])
    ctrl.reproject()  # points still match -> stored coords untouched
    assert ctrl.attached[id(zone)][1] == corners


def test_restation_noop_without_a_datum():
    ctrl = make_cl()
    ctrl.mouse_down((0, 0))
    zone = EventZone(enable=1, points=[(1, 1)])
    ctrl.attach(zone, [(0.0, 0.0)])
    ctrl.mouse_move((5, 5), dragging=True)  # single point: no datum yet
    assert zone.points == [(1, 1)]


# -- deriving attachments on open (Session 7.5 addendum) -----------------------

def placed_zones_on_bent_centerline():
    """The acceptance template placed along a bent centerline at 4 px/ft
    (so the 283.8 ft advance loops land past the bend), corners rounded to
    the vendor's 2 decimals as save/load would."""
    from model.templates import ApproachTemplate, Lane, expand_and_place_on_centerline
    cl_pts = [(0.0, 0.0), (0.0, -800.0), (-600.0, -1400.0)]
    t = ApproachTemplate(lanes=[Lane("L"), Lane("T"), Lane("T"), Lane("R")],
                         speed_mph=45.0)
    placed = expand_and_place_on_centerline(t, cl_pts, (2.0, 1.0), 4.0)
    zones = [EventZone(enable=1, zone_name=d.spec.name,
                       points=[(round(x, 2), round(y, 2)) for x, y in d.points])
             for d in placed]
    return cl_pts, zones


def test_derive_attachments_recognizes_engine_placed_zones():
    cl_pts, zones = placed_zones_on_bent_centerline()
    ctrl = make_cl()
    ctrl.points = list(cl_pts)
    assert derive_attachments([ctrl], [zones]) == len(zones) == 11
    # and the derived attachment actually re-stations: stretch the far leg
    before = [list(z.points) for z in zones]
    ctrl.selected = 2
    ctrl.points[2] = (-900.0, -1400.0)
    ctrl.restation()
    moved = sum(any(geometry.dist(p, q) > 1.0 for p, q in zip(a, z.points))
                for a, z in zip(before, zones))
    assert moved >= 2  # the past-the-bend advance loops followed


def test_derive_attachments_recognizes_zone_straddling_a_bend():
    """A dilemma zone whose corners sit on both legs of a bend: the
    concave-side corners project onto the wrong segment, so recognition
    must go through the per-segment candidate search."""
    from model.templates import ApproachTemplate, Lane, expand_and_place_on_centerline
    cl_pts = [(400.0, 500.0), (400.0, 420.0), (250.0, 150.0)]  # bend at 160 ft
    t = ApproachTemplate(lanes=[Lane("L"), Lane("T"), Lane("T"), Lane("R")],
                         speed_mph=45.0)  # dilemma 160..180 ft straddles it
    placed = expand_and_place_on_centerline(t, cl_pts, (395.0, 505.0), 0.5)
    zones = [EventZone(enable=1, zone_name=d.spec.name,
                       points=[(round(x, 2), round(y, 2)) for x, y in d.points])
             for d in placed]
    ctrl = make_cl()
    ctrl.points = list(cl_pts)
    assert derive_attachments([ctrl], [zones]) == len(zones) == 11


def test_derive_attachments_rejects_hand_drawn_shapes():
    ctrl = make_cl()
    ctrl.points = [(0.0, 0.0), (0.0, -800.0)]
    tilted = EventZone(enable=1, points=[  # rectangle, but 3 px off-axis
        (20, -100), (60, -103), (63, -143), (23, -140)])
    quad = EventZone(enable=1, points=[(0, -50), (40, -50), (50, -90), (0, -80)])
    triangle = EventZone(enable=1, points=[(0, -200), (40, -200), (20, -240)])
    assert derive_attachments([ctrl], [[tilted, quad, triangle]]) == 0


def test_derive_attachments_picks_laterally_nearest_centerline():
    # two parallel straight datums: an aligned rectangle matches both, so
    # the laterally nearest must win
    near, far = make_cl(), make_cl()
    near.points = [(0.0, 0.0), (0.0, -800.0)]
    far.points = [(500.0, 0.0), (500.0, -800.0)]
    zone = EventZone(enable=1, points=[(20, -100), (32, -100),
                                       (32, -140), (20, -140)])
    assert derive_attachments([near, far], [[zone]]) == 1
    assert id(zone) in near.attached
    assert id(zone) not in far.attached


def test_derive_attachments_skips_placeholders_and_disabled():
    ctrl = make_cl()
    ctrl.points = [(0.0, 0.0), (0.0, -800.0)]
    disabled = EventZone(enable=0, zone_name="off", points=[
        (20, -100), (32, -100), (32, -140), (20, -140)])
    assert derive_attachments([ctrl], [[EventZone(), disabled]]) == 0
