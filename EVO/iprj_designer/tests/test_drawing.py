import pytest

from gui.drawing import (DIM_LENGTH1, DIM_LENGTH2, DIM_OFF, IGNORE_KIND,
                         LINEAL_KIND, CenterlineController, DrawingController,
                         bumped_name, derive_attachments, is_placeholder,
                         next_output_number)
from model import domain, geometry
from model.iprj_io import EventZone, IgnoreZone, Lineal

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

def test_free_draw_commits_on_explicit_finish():
    ctrl = make_ctrl()
    for p in [(0, 0), (40, 0), (40, 40), (0, 40)]:
        ctrl.mouse_down(p)
    assert ctrl.zones == []                  # no auto-commit at 4 points
    assert ctrl.finish_polygon()
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
    ctrl.finish_polygon()
    ctrl.undo()
    assert ctrl.zones == []


def test_free_draw_continues_past_four_points():
    ctrl = make_ctrl()
    pts = [(0, 0), (40, 0), (60, 20), (40, 40), (0, 40), (-20, 20)]
    for p in pts:
        ctrl.mouse_down(p)
    assert ctrl.zones == [] and ctrl.pending == pts
    assert ctrl.finish_polygon()
    assert ctrl.zones[0].points == pts
    ctrl.undo()                              # whole shape, one step
    assert ctrl.zones == []


def test_enter_key_finishes_free_draw():
    ctrl = make_ctrl()
    for p in [(0, 0), (40, 0), (40, 40), (0, 40), (-10, 20)]:
        ctrl.mouse_down(p)
    assert ctrl.key("Enter")
    assert len(ctrl.zones) == 1 and len(ctrl.zones[0].points) == 5


def test_finish_needs_three_corners_and_keeps_pending():
    ctrl = make_ctrl()
    ctrl.mouse_down((0, 0))
    ctrl.mouse_down((40, 0))
    assert ctrl.finish_polygon()             # handled: feedback, no commit
    assert ctrl.zones == [] and ctrl.pending == [(0, 0), (40, 0)]
    assert "3 corners" in ctrl.message
    ctrl.mouse_down((40, 40))
    assert ctrl.finish_polygon()
    assert ctrl.zones[0].points == [(0, 0), (40, 0), (40, 40)]


def test_finish_folds_double_click_duplicate_points():
    # the double-click gesture's own two clicks land as pending points
    # before the GUI's dblclick handler calls finish_polygon()
    ctrl = make_ctrl()
    for p in [(0, 0), (40, 0), (40, 40), (0, 40), (0.5, 40.5)]:
        ctrl.mouse_down(p)
    assert ctrl.finish_polygon()
    assert ctrl.zones[0].points == [(0, 0), (40, 0), (40, 40), (0, 40)]


def test_finish_is_a_noop_outside_free_polygon_draw():
    ctrl = make_ctrl([square(0, 0)])
    assert not ctrl.finish_polygon()         # nothing pending
    ctrl.set_mode("edit")
    assert not ctrl.finish_polygon()         # edit mode
    ctrl.set_mode("draw")
    ctrl.mouse_down((0, 200))
    ctrl.mouse_move((100, 200))
    ctrl.key("1")                            # dimension entry owns Enter
    assert not ctrl.finish_polygon()
    seg = make_kind_ctrl(LINEAL_KIND)
    seg.mouse_down((0, 0))
    assert not seg.finish_polygon()          # segment kind


def test_preview_follows_cursor_past_four_points():
    ctrl = make_ctrl()
    for p in [(0, 0), (40, 0), (40, 40), (0, 40)]:
        ctrl.mouse_down(p)
    ctrl.mouse_move((-20, 20))
    assert ctrl.preview_polygon() == [(0, 0), (40, 0), (40, 40), (0, 40),
                                      (-20, 20)]


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
    ctrl.finish_polygon()


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


def test_insert_many_is_one_undoable_batch():
    placeholder = EventZone(enable=0, zone_name="")
    zones = [placeholder, square(100, 0, name="existing")]
    ctrl = make_ctrl(zones)
    template_zones = [square(0, 0, name="T1"), square(50, 0, name="T2"),
                      square(200, 0, name="T3")]
    ctrl.insert_many(template_zones)
    # first fills the placeholder slot, the rest append
    assert [z.zone_name for z in zones] == ["T1", "existing", "T2", "T3"]
    assert len(ctrl._undo) == 1 and ctrl._undo[-1][0] == "batch"
    ctrl.undo()
    # the placeholder slot comes back (not removed), the appended ones do
    assert len(zones) == 2
    assert zones[0] is placeholder
    assert is_placeholder(zones[0])
    assert zones[1].zone_name == "existing"


def test_insert_many_undo_does_not_disturb_earlier_undo_steps():
    zones = [square(0, 0, name="manual")]
    ctrl = make_ctrl(zones)
    ctrl._insert(square(300, 0, name="manual-2"))
    ctrl.insert_many([square(400, 0, name="T1"), square(450, 0, name="T2")])
    assert [z.zone_name for z in zones] == ["manual", "manual-2", "T1", "T2"]
    ctrl.undo()  # undoes the whole template batch, not one detector
    assert [z.zone_name for z in zones] == ["manual", "manual-2"]
    ctrl.undo()  # then the earlier single insert
    assert [z.zone_name for z in zones] == ["manual"]


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


# -- rotate (Phase 3.2c) ------------------------------------------------------

def test_selection_centroid_of_one_square():
    ctrl = make_ctrl([square(0, 0, size=40)])
    ctrl.set_mode("edit")
    ctrl.selected = 0
    assert ctrl.selection_centroid() == pytest.approx((20, 20))


def test_selection_centroid_none_without_selection():
    ctrl = make_ctrl([square(0, 0)])
    assert ctrl.selection_centroid() is None


def test_rotate_selection_90deg_about_its_own_centroid():
    ctrl = make_ctrl([square(0, 0, size=40)])
    ctrl.set_mode("edit")
    ctrl.selected = 0
    pivot = ctrl.selection_centroid()
    rotated = ctrl.rotate_selection(90, pivot)
    assert rotated == [ctrl.zones[0]]
    assert ctrl.zones[0].points == pytest.approx(
        geometry.rotate_points([(0, 0), (40, 0), (40, 40), (0, 40)], 90, pivot))


def test_rotate_selection_is_one_batch_undo_step():
    ctrl = make_ctrl([square(0, 0), square(100, 0)])
    ctrl.select_many([0, 1])
    orig = [list(ctrl.zones[0].points), list(ctrl.zones[1].points)]
    ctrl.rotate_selection(45, (50, 20))
    assert ctrl.zones[0].points != orig[0]
    assert ctrl.zones[1].points != orig[1]
    ctrl.undo()
    assert ctrl.zones[0].points == orig[0]
    assert ctrl.zones[1].points == orig[1]


def test_rotate_selection_zero_angle_is_a_noop_and_not_undoable():
    ctrl = make_ctrl([square(0, 0)])
    ctrl.selected = 0
    orig = list(ctrl.zones[0].points)
    assert ctrl.rotate_selection(0.0, (20, 20)) == []
    assert ctrl.zones[0].points == orig
    ctrl.undo()  # nothing was pushed onto the undo stack
    assert ctrl.message == "nothing to undo"


def test_rotate_selection_without_selection_is_a_noop():
    ctrl = make_ctrl([square(0, 0)])
    assert ctrl.rotate_selection(90, (20, 20)) == []


# -- insert vertex (ROADMAP Item 5) ----------------------------------------------

def test_insert_vertex_on_nearest_edge():
    ctrl = make_ctrl([square(0, 0, size=40)])
    ctrl.set_mode("edit")
    ctrl.selected = 0
    assert ctrl.insert_vertex((20, -5))     # nearest the (0,0)->(40,0) edge
    assert ctrl.zones[0].points == [
        (0, 0), (20.0, 0.0), (40, 0), (40, 40), (0, 40)]
    assert "added vertex" in ctrl.message


def test_insert_vertex_closing_edge_appends():
    ctrl = make_ctrl([square(0, 0, size=40)])
    ctrl.set_mode("edit")
    ctrl.selected = 0
    assert ctrl.insert_vertex((-5, 20))     # (0,40)->(0,0) wrap-around edge
    assert ctrl.zones[0].points == [
        (0, 0), (40, 0), (40, 40), (0, 40), (0.0, 20.0)]


def test_insert_vertex_defaults_to_cursor():
    ctrl = make_ctrl([square(0, 0, size=40)])
    ctrl.set_mode("edit")
    ctrl.selected = 0
    ctrl.mouse_move((20, -5))
    assert ctrl.insert_vertex()
    assert len(ctrl.zones[0].points) == 5
    # no cursor yet and no explicit point: refused
    ctrl2 = make_ctrl([square(0, 0)])
    ctrl2.set_mode("edit")
    ctrl2.selected = 0
    assert not ctrl2.insert_vertex()
    assert len(ctrl2.zones[0].points) == 4


def test_insert_vertex_is_one_undo_step():
    ctrl = make_ctrl([square(0, 0, size=40)])
    ctrl.set_mode("edit")
    ctrl.selected = 0
    orig = list(ctrl.zones[0].points)
    ctrl.insert_vertex((20, -5))
    ctrl.undo()
    assert ctrl.zones[0].points == orig


def test_insert_vertex_requires_single_selection_in_edit_mode():
    ctrl = make_ctrl([square(0, 0), square(100, 0)])
    assert not ctrl.insert_vertex((20, -5))      # draw mode
    ctrl.set_mode("edit")
    ctrl.selected = -1
    assert not ctrl.insert_vertex((20, -5))      # nothing selected
    ctrl.select_many([0, 1])
    assert not ctrl.insert_vertex((20, -5))      # multi-select
    assert all(len(z.points) == 4 for z in ctrl.zones)


def test_insert_vertex_refuses_lineals():
    lineals = [domain.new_lineal((0, 0), (100, 0))]
    ctrl = make_kind_ctrl(LINEAL_KIND, lineals)
    ctrl.set_mode("edit")
    ctrl.selected = 0
    assert not ctrl.insert_vertex((50, 5))
    assert lineals[0].point_0 == (0.0, 0.0)
    assert lineals[0].point_1 == (100.0, 0.0)
    assert "lineal" in ctrl.message


def test_insert_vertex_breaks_nudge_coalescing():
    ctrl = make_ctrl([square(0, 0, size=40)])
    ctrl.set_mode("edit")
    ctrl.selected = 0
    ctrl.key("ArrowRight")
    ctrl.insert_vertex((20, -5))
    ctrl.key("ArrowRight")                       # must not merge into the first nudge
    ctrl.undo()                                  # second nudge only
    assert len(ctrl.zones[0].points) == 5
    ctrl.undo()                                  # the inserted vertex
    assert len(ctrl.zones[0].points) == 4
    ctrl.undo()                                  # first nudge
    assert ctrl.zones[0].points == [(0, 0), (40, 0), (40, 40), (0, 40)]


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


# -- move along centerline (Item 8) --------------------------------------------

def test_zone_station_is_the_downstream_edge():
    ctrl, zone = cl_with_zone()  # stations 20..30
    assert ctrl.zone_station(zone) == 20.0


def test_zone_station_unattached_zone_is_none():
    ctrl = make_cl()
    ctrl.mouse_down((0, 0))
    ctrl.mouse_down((100, 0))
    zone = EventZone(enable=1, points=[(1, 1), (2, 1), (2, 2), (1, 2)])
    assert ctrl.zone_station(zone) is None


def test_move_attached_by_relative_delta():
    ctrl, zone = cl_with_zone()  # corners at stations 20..30, offset 0..-10
    old = ctrl.move_attached(zone, delta=40.0)
    assert old == [(20, 0), (20, -10), (30, -10), (30, 0)]
    assert ctrl.zone_station(zone) == 60.0
    assert zone.points == [(60, 0), (60, -10), (70, -10), (70, 0)]


def test_move_attached_to_absolute_station():
    ctrl, zone = cl_with_zone()
    ctrl.move_attached(zone, station=100.0)
    assert ctrl.zone_station(zone) == 100.0
    assert zone.points == [(100, 0), (100, -10), (110, -10), (110, 0)]


def test_move_attached_preserves_shape_through_a_bend():
    ctrl, zone = cl_with_zone()
    ctrl.mouse_down((100, 0))
    ctrl.mouse_move((100, 100), dragging=True)
    ctrl.mouse_up((100, 100))  # bend at station 100
    ctrl.move_attached(zone, station=90.0)  # straddles the bend
    datum = geometry.Centerline(ctrl.points)
    expected = [datum.point_at(s, off)
                for s, off in [(90, 0), (90, -10), (100, -10), (100, 0)]]
    for (x, y), (ex, ey) in zip(zone.points, expected):
        assert x == pytest.approx(ex)
        assert y == pytest.approx(ey)


def test_move_attached_rejects_ambiguous_or_missing_args():
    ctrl, zone = cl_with_zone()
    with pytest.raises(ValueError):
        ctrl.move_attached(zone)
    with pytest.raises(ValueError):
        ctrl.move_attached(zone, station=1.0, delta=1.0)


def test_move_attached_unattached_zone_returns_none():
    ctrl = make_cl()
    ctrl.mouse_down((0, 0))
    ctrl.mouse_down((100, 0))
    zone = EventZone(enable=1, points=[(1, 1), (2, 1), (2, 2), (1, 2)])
    assert ctrl.move_attached(zone, delta=10.0) is None


def test_move_attached_without_a_datum_returns_none():
    ctrl = make_cl()
    ctrl.mouse_down((0, 0))
    zone = EventZone(enable=1, points=[(1, 1)])
    ctrl.attach(zone, [(0.0, 0.0)])
    assert ctrl.move_attached(zone, delta=10.0) is None


def test_move_attached_undo_restores_via_record_points_undo():
    """Mirrors how the GUI drives this: DrawingController.record_points_undo
    captures the pre-move points, and its own undo() restores them."""
    zones = []
    ctrl, zone = cl_with_zone()
    zones.append(zone)
    dctrl = make_ctrl(zones)
    old = ctrl.move_attached(zone, delta=40.0)
    dctrl.record_points_undo(zone, old)
    assert zone.points == [(60, 0), (60, -10), (70, -10), (70, 0)]
    dctrl.undo()
    assert zone.points == [(20, 0), (20, -10), (30, -10), (30, 0)]


# -- deriving attachments on open (Session 7.5 addendum) -----------------------

def placed_zones_on_bent_centerline():
    """The acceptance template placed along a bent centerline at 4 px/ft
    (so the 283.8 ft advance loops land past the bend), corners rounded to
    the vendor's 2 decimals as save/load would."""
    from model.templates import ApproachTemplate, Lane, expand_and_place_on_centerline
    cl_pts = [(0.0, 0.0), (0.0, -800.0), (-600.0, -1400.0)]
    t = ApproachTemplate(lanes=[Lane("L"), Lane("T"), Lane("T"), Lane("R")],
                         speed_mph=45.0, direction="N", thru_phase=4,
                         lt_phase=7, base_output=1)
    placed = expand_and_place_on_centerline(t, cl_pts, (2.0, 1.0), 4.0)
    zones = [EventZone(enable=1, zone_name=d.spec.name,
                       points=[(round(x, 2), round(y, 2)) for x, y in d.points])
             for d in placed]
    return cl_pts, zones


def test_derive_attachments_recognizes_engine_placed_zones():
    cl_pts, zones = placed_zones_on_bent_centerline()
    ctrl = make_cl()
    ctrl.points = list(cl_pts)
    assert derive_attachments([ctrl], [zones]) == len(zones) == 13
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
                         speed_mph=45.0, direction="N", thru_phase=4,
                         lt_phase=7, base_output=1)  # dilemma 165..185 straddles it
    placed = expand_and_place_on_centerline(t, cl_pts, (395.0, 505.0), 0.5)
    zones = [EventZone(enable=1, zone_name=d.spec.name,
                       points=[(round(x, 2), round(y, 2)) for x, y in d.points])
             for d in placed]
    ctrl = make_cl()
    ctrl.points = list(cl_pts)
    assert derive_attachments([ctrl], [zones]) == len(zones) == 13


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


# -- draw kinds (Phase 3.2a) ----------------------------------------------------

def make_kind_ctrl(kind, items=None, numbered=False):
    items = items if items is not None else []
    return DrawingController(
        items, lambda: FT_PER_PX,
        next_output=(lambda: 99) if numbered else None, kind=kind)


def ignore_square(x=0.0, y=0.0, size=40.0):
    return domain.new_ignore_zone(
        [(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def test_ignore_kind_draws_into_ignore_list():
    ignores: list = []
    ctrl = make_kind_ctrl(IGNORE_KIND, ignores)
    for p in [(0, 0), (40, 0), (40, 40), (0, 40)]:
        ctrl.mouse_down(p)
    ctrl.finish_polygon()
    assert len(ignores) == 1
    assert isinstance(ignores[0], IgnoreZone)
    assert ignores[0].enable == 1
    assert ignores[0].zone_name == "Ignore 1"
    assert ignores[0].points == [(0, 0), (40, 0), (40, 40), (0, 40)]


def test_ignore_kind_fills_placeholder_and_undo_restores_it():
    placeholder = IgnoreZone(enable=0)
    ignores = [placeholder]
    ctrl = make_kind_ctrl(IGNORE_KIND, ignores)
    draw_square(ctrl)
    assert len(ignores) == 1 and ignores[0] is not placeholder
    ctrl.undo()
    assert ignores[0] is placeholder


def test_ignore_kind_cap_sets_warning_not_exception():
    ignores = [ignore_square(x=50.0 * i) for i in range(10)]
    ctrl = make_kind_ctrl(IGNORE_KIND, ignores)
    draw_square(ctrl, 600, 0)
    assert len(ignores) == 10                 # nothing added
    assert "10" in ctrl.warning
    ctrl.undo()
    assert len(ignores) == 10                 # no undo op was recorded


def test_ignore_kind_gets_dimensioned_draw_for_free():
    ignores: list = []
    ctrl = make_kind_ctrl(IGNORE_KIND, ignores)
    ctrl.mouse_down((100, 100))
    ctrl.mouse_move((200, 100))
    for k in "10":
        ctrl.key(k)
    ctrl.key("Enter")
    ctrl.mouse_move((150, 300))
    for k in "20":
        ctrl.key(k)
    ctrl.key("Enter")
    assert ignores[0].points == pytest.approx(
        [(100, 100), (140, 100), (140, 180), (100, 180)])


def test_ignore_kind_with_next_output_does_not_number():
    ignores: list = []
    ctrl = make_kind_ctrl(IGNORE_KIND, ignores, numbered=True)
    draw_square(ctrl)                          # would raise if it tried
    assert not hasattr(ignores[0], "output_number")


def test_lineal_kind_commits_after_two_clicks():
    lineals: list = []
    ctrl = make_kind_ctrl(LINEAL_KIND, lineals)
    ctrl.mouse_down((0, 0))
    assert lineals == [] and ctrl.pending == [(0, 0)]
    ctrl.mouse_down((100, 50))
    assert len(lineals) == 1 and ctrl.pending == []
    assert isinstance(lineals[0], Lineal) and lineals[0].enable == 1
    assert lineals[0].point_0 == (0.0, 0.0)
    assert lineals[0].point_1 == (100.0, 50.0)
    ctrl.undo()
    assert lineals == []


def test_lineal_kind_preview_is_a_segment():
    ctrl = make_kind_ctrl(LINEAL_KIND)
    ctrl.mouse_down((0, 0))
    ctrl.mouse_move((60, 30))
    assert ctrl.preview_polygon() == [(0, 0), (60, 30)]


def test_lineal_kind_has_no_dimension_entry():
    ctrl = make_kind_ctrl(LINEAL_KIND)
    ctrl.mouse_down((0, 0))
    ctrl.mouse_move((100, 0))
    assert not ctrl.key("1")
    assert ctrl.dim_stage == DIM_OFF


def test_lineal_kind_never_snaps():
    lineals = [domain.new_lineal((0, 0), (100, 0))]
    ctrl = make_kind_ctrl(LINEAL_KIND, lineals)
    ctrl.key("g")                              # snap on
    ctrl.snap_radius = 12.0
    ctrl.mouse_down((97, 3))                   # near (100, 0) — must NOT snap
    assert ctrl.pending == [(97, 3)]
    assert ctrl.snap_indicator is None


def test_lineal_kind_cap_sets_warning():
    lineals = [domain.new_lineal((0, 10.0 * i), (50, 10.0 * i))
               for i in range(domain.MAX_LINEALS)]
    ctrl = make_kind_ctrl(LINEAL_KIND, lineals)
    ctrl.mouse_down((0, -50))
    ctrl.mouse_down((50, -50))
    assert len(lineals) == domain.MAX_LINEALS
    assert "100" in ctrl.warning


def test_lineal_edit_drag_endpoint_and_undo():
    lineals = [domain.new_lineal((0, 0), (100, 0))]
    ctrl = make_kind_ctrl(LINEAL_KIND, lineals)
    ctrl.set_mode("edit")
    assert ctrl.selected == 0                  # preselected
    ctrl.handle_radius = 5.0
    ctrl.mouse_down((99, 1))                   # grab endpoint (100, 0)
    ctrl.mouse_move((120, 30), dragging=True)
    ctrl.mouse_up((120, 30))
    assert lineals[0].point_1 == (120, 30)
    ctrl.undo()
    assert lineals[0].point_1 == (100, 0)


def test_lineal_edit_body_drag_moves_both_endpoints():
    lineals = [domain.new_lineal((0, 0), (100, 0))]
    ctrl = make_kind_ctrl(LINEAL_KIND, lineals)
    ctrl.set_mode("edit")
    ctrl.mouse_down((50, 2))                   # on the segment body
    ctrl.mouse_move((60, 22), dragging=True)
    ctrl.mouse_up((60, 22))
    assert lineals[0].point_0 == (10, 20)
    assert lineals[0].point_1 == (110, 20)


def test_retarget_switches_kind_and_undo_reaches_across():
    zones, lineals = [], []
    ctrl = make_ctrl(zones)
    draw_square(ctrl)
    ctrl.retarget(lineals, kind=LINEAL_KIND)
    ctrl.mouse_down((0, 0))
    ctrl.mouse_down((100, 0))
    assert len(zones) == 1 and len(lineals) == 1
    ctrl.undo()
    assert lineals == []
    ctrl.undo()
    assert zones == []


def test_retarget_without_kind_keeps_kind():
    ctrl = make_kind_ctrl(IGNORE_KIND, [])
    ctrl.retarget([])
    assert ctrl.kind is IGNORE_KIND


# -- multi-select (Phase 3.2a) --------------------------------------------------

def three_squares_ctrl():
    zones = [square(0, 0, name="A"), square(100, 0, name="B"),
             square(200, 0, name="C")]
    ctrl = make_ctrl(zones)
    ctrl.set_mode("edit")
    return ctrl, zones


def test_selected_property_mirrors_selection():
    ctrl, _ = three_squares_ctrl()
    ctrl.selected = 1
    assert ctrl.selection == [1] and ctrl.anchor == 1
    ctrl.selected = -1
    assert ctrl.selection == [] and ctrl.selected == -1


def test_shift_click_toggles_membership():
    ctrl, _ = three_squares_ctrl()
    ctrl.mouse_down((20, 20))                  # plain click selects A only
    ctrl.mouse_up((20, 20))
    assert ctrl.selection == [0]
    ctrl.mouse_down((120, 20), shift=True)     # shift-click adds B
    assert ctrl.selection == [0, 1] and ctrl.anchor == 1
    ctrl.mouse_down((120, 20), shift=True)     # shift-click removes B
    assert ctrl.selection == [0] and ctrl.anchor == 0


def test_plain_click_on_unselected_zone_collapses_group():
    ctrl, _ = three_squares_ctrl()
    ctrl.select_many([0, 1])
    ctrl.mouse_down((220, 20))                 # body of C
    ctrl.mouse_up((220, 20))
    assert ctrl.selection == [2]


def test_marquee_selects_every_intersecting_zone():
    ctrl, _ = three_squares_ctrl()
    hits = ctrl.marquee_select((-5, -5), (150, 50))
    assert hits == [0, 1]
    assert ctrl.selection == [0, 1] and ctrl.anchor == 1
    ctrl.marquee_select((195, -5), (250, 50), additive=True)
    assert ctrl.selection == [0, 1, 2]


def test_marquee_skips_placeholders_and_disabled():
    zones = [square(0, 0, name="A"), EventZone(enable=0),
             square(100, 0, name="off")]
    zones[2].enable = 0
    ctrl = make_ctrl(zones)
    ctrl.set_mode("edit")
    assert ctrl.marquee_select((-5, -5), (300, 50)) == [0]


def test_group_drag_moves_all_selected_as_one_undo():
    ctrl, zones = three_squares_ctrl()
    ctrl.select_many([0, 1])
    ctrl.mouse_down((20, 20))                  # grab a selected member
    ctrl.mouse_move((30, 25), dragging=True)
    ctrl.mouse_up((30, 25))
    assert zones[0].points[0] == (10, 5)
    assert zones[1].points[0] == (110, 5)
    assert zones[2].points[0] == (200, 0)      # unselected zone untouched
    assert ctrl.selection == [0, 1] and ctrl.anchor == 0
    ctrl.undo()
    assert zones[0].points[0] == (0, 0)
    assert zones[1].points[0] == (100, 0)
    assert "group move" in ctrl.message


def test_group_delete_is_one_undoable_batch():
    ctrl, zones = three_squares_ctrl()
    ctrl.select_many([0, 2])
    ctrl.delete_selected()
    assert [z.zone_name for z in zones] == ["B"]
    assert ctrl.selection == []
    ctrl.undo()
    assert [z.zone_name for z in zones] == ["A", "B", "C"]


def test_group_nudge_coalesces_into_one_undo():
    ctrl, zones = three_squares_ctrl()
    ctrl.select_many([0, 1])
    ctrl.key("ArrowRight")
    ctrl.key("ArrowRight")
    assert zones[0].points[0] == pytest.approx((4, 0))
    assert zones[1].points[0] == pytest.approx((104, 0))
    ctrl.undo()
    assert zones[0].points[0] == (0, 0)
    assert zones[1].points[0] == (100, 0)


def test_escape_clears_multi_selection():
    ctrl, _ = three_squares_ctrl()
    ctrl.select_many([0, 1, 2])
    assert ctrl.key("Escape")
    assert ctrl.selection == []


def test_cycle_collapses_selection_to_one():
    ctrl, _ = three_squares_ctrl()
    ctrl.select_many([0, 1])
    ctrl.key("n")
    assert len(ctrl.selection) == 1


def test_retarget_clears_selection():
    ctrl, _ = three_squares_ctrl()
    ctrl.select_many([0, 1])
    ctrl.retarget([])
    assert ctrl.selection == []


def test_status_reports_selection_count():
    ctrl, _ = three_squares_ctrl()
    ctrl.select_many([0, 1])
    assert "2 zones" in ctrl.status()


# -- accelerator seam (PHASE3_UI_PLAN §2.1) -------------------------------------

def test_controller_no_longer_owns_mode_shortcuts():
    ctrl = make_ctrl([square(0, 0)])
    assert not ctrl.key("e")
    assert ctrl.mode == "draw"
    assert not ctrl.key("l")
    assert ctrl.mode == "draw"
    ctrl.set_mode("edit")
    assert not ctrl.key("e")
    assert ctrl.mode == "edit"


def test_d_no_longer_starts_dimension_entry():
    ctrl = make_ctrl()
    ctrl.mouse_down((0, 0))
    ctrl.mouse_move((100, 0))
    assert not ctrl.key("d")
    assert ctrl.dim_stage == DIM_OFF
    assert ctrl.key("1")                       # digits still do
    assert ctrl.dim_stage == DIM_LENGTH1
