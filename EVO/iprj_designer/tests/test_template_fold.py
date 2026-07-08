"""Template folded into Draw › Event Zone + the unified CL dropdown (ROADMAP
Item 27).

Item 27 retired the standalone Template tool: template placement is now a
sub-state of Draw › Event Zone (`Viewer.template_placement_active`), driven by
the Event-Zone "template" picker, and the Item-19 follow-switch + pick-select
collapsed into one CL dropdown (`Viewer.event_cl_idx`). That dropdown governs
*every* event zone drawn here — a template places along the chosen centerline
and a plain drawn zone joins its membership group (Item 26). These tests drive
the GUI `Viewer` / `DrawingController` headlessly.
"""

import base64
import io
from pathlib import Path

from PIL import Image

from gui.app import Viewer
from gui.drawing import DrawingController, LOOP_KIND, next_output_number
from model.iprj_io import Background, EventZone, IgnoreZone, Project, Sensor

FT_PER_PX = 0.25


def _bg() -> Background:
    buf = io.BytesIO()
    Image.new("RGB", (600, 600), "gray").save(buf, format="PNG")
    return Background(image_base64=base64.b64encode(buf.getvalue()).decode("ascii"),
                     pos_x=0.0, pos_y=0.0, scale=100.0)


def _triangle(name: str = "det") -> EventZone:
    return EventZone(enable=1, zone_name=name,
                     points=[(210.0, 300.0), (250.0, 300.0), (230.0, 340.0)])


def make_viewer(zones=None) -> Viewer:
    sensor = Sensor()
    sensor.event_zones = list(zones or [])
    return Viewer(Project(background=_bg(), sensors=[sensor]), Path("/tmp/t.iprj"))


def _datumed_centerline(v: Viewer, name="N_CL"):
    cl = v.centerlines[0]
    cl.points = [(200.0, 200.0), (200.0, 500.0)]
    cl.name = name
    return cl


# ---------------------------------------------------------------------------
# template_placement_active — the Draw › Event Zone sub-state
# ---------------------------------------------------------------------------

def test_template_placement_needs_draw_event_zone_and_a_template():
    v = make_viewer()
    v.template = object()          # a picked template (sentinel; only `is None` matters)
    v.mode, v.draw_kind_name = "Draw", "Event Zone"
    assert v.template_placement_active()


def test_template_placement_off_without_a_template():
    v = make_viewer()
    v.mode, v.draw_kind_name = "Draw", "Event Zone"
    assert v.template is None
    assert not v.template_placement_active()


def test_template_placement_off_outside_event_zone_draw():
    v = make_viewer()
    v.template = object()
    v.mode, v.draw_kind_name = "Draw", "Ignore Zone"
    assert not v.template_placement_active()
    v.mode, v.draw_kind_name = "Edit", "Event Zone"   # Edit never drops templates
    assert not v.template_placement_active()


# ---------------------------------------------------------------------------
# template_target_centerline — one CL dropdown, no nearest/threshold auto
# ---------------------------------------------------------------------------

def test_target_centerline_is_the_picked_one():
    v = make_viewer()
    cl = _datumed_centerline(v)
    v.event_cl_idx = 0
    assert v.template_target_centerline() is cl


def test_target_centerline_none_when_blank():
    v = make_viewer()
    _datumed_centerline(v)
    v.event_cl_idx = None          # blank = aim-upstream, not "nearest"
    assert v.template_target_centerline() is None


def test_target_centerline_none_when_pick_has_no_datum():
    v = make_viewer()
    v.centerlines[0].points = []   # picked but empty -> not a usable datum
    v.event_cl_idx = 0
    assert v.template_target_centerline() is None


# ---------------------------------------------------------------------------
# on_zone_committed — a plain drawn event zone joins the picked CL's group
# ---------------------------------------------------------------------------

def test_drawn_event_zone_joins_picked_centerline():
    v = make_viewer()
    cl = _datumed_centerline(v)
    v.draw_kind_name, v.event_cl_idx = "Event Zone", 0
    zone = _triangle()
    v.on_zone_committed(zone)
    assert id(zone) in cl.attached
    assert v.membership_for(zone) is cl


def test_drawn_event_zone_takes_no_membership_when_cl_blank():
    v = make_viewer()
    _datumed_centerline(v)
    v.draw_kind_name, v.event_cl_idx = "Event Zone", None
    zone = _triangle()
    v.on_zone_committed(zone)
    assert v.membership_for(zone) is None


def test_non_event_zone_kinds_never_take_membership():
    v = make_viewer()
    _datumed_centerline(v)
    v.event_cl_idx = 0
    v.draw_kind_name = "Ignore Zone"   # the CL dropdown is Event-Zone only
    zone = IgnoreZone(enable=1, points=_triangle().points)
    v.on_zone_committed(zone)
    assert v.membership_for(zone) is None


# ---------------------------------------------------------------------------
# DrawingController.on_commit — the hook the Viewer wires membership through
# ---------------------------------------------------------------------------

def test_controller_on_commit_fires_once_per_free_draw():
    committed = []
    ctrl = DrawingController(
        [], lambda: FT_PER_PX, kind=LOOP_KIND,
        on_commit=committed.append)
    for p in [(0, 0), (40, 0), (40, 40), (0, 40)]:
        ctrl.mouse_down(p)
    assert committed == []              # not until the polygon finishes
    assert ctrl.finish_polygon()
    assert len(committed) == 1
    assert committed[0] is ctrl.zones[0]


def test_controller_on_commit_end_to_end_membership():
    # the real path: a free-draw commit routes through the Viewer's on_commit
    # hook and picks up the CL dropdown's membership (no manual attach call)
    v = make_viewer()
    cl = _datumed_centerline(v)
    v.mode, v.draw_kind_name, v.event_cl_idx = "Draw", "Event Zone", 0
    v.ctrl.set_mode("draw")
    for p in [(210, 300), (250, 300), (250, 340), (210, 340)]:
        v.ctrl.mouse_down(p)
    assert v.ctrl.finish_polygon()
    drawn = v.active_zones()[-1]
    assert v.membership_for(drawn) is cl
