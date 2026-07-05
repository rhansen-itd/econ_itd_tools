"""iprj Designer — NiceGUI shell (Sessions 2–5).

Scaled background viewer with zoom/pan, live cursor readout in feet, both
calibration methods, the drawing core (free 4-point loops, dimensioned
rectangles, snapping, edit mode with move/copy/delete and undo —
gui/drawing.py), the attribute layer (zone properties with conditions,
sensor placement/properties, active-sensor selection, Save/Save As to a
full .iprj), the Session 5 UX pass: icon toolbar with tooltips, a zone
table panel synced with canvas selection, and layer toggles
(background/zones/labels/sensors); and the Session 6.3 template tool: pick
an approach template, click the stop-bar reference point, aim upstream,
click again to expand and place every detector via the existing
DrawingController/insert_zone path; and the Session 7.2 Centerline tool:
draw/edit approach centerline polylines (station 0 at the stop bar) with
a live station/offset readout from model/geometry.py's Centerline engine.
Session 7.4 wires these through model/centerline.py: every centerline in
the opened project is reconstructed into its own CenterlineController, and
the current set is written back out as Lineals on save. Session 7.5 routes
template placement through the station/offset engine whenever a centerline
is drawn — detectors follow the approach curvature, and editing the
centerline afterward re-stations the zones placed along it. Phase 1 adds a
2-point Ruler tool for quick distance checks, an undo fix so a placed
template is removed as one unit, a background-visibility fix, and in-app
New/Open/Upload file management.

Phase 3.2b reorganizes the toolbar into two tiers per PHASE3_UI_PLAN.md
§3/§4/§5: a persistent chrome row (file menu, the 6-tool toggle, snap,
undo, layers, fit, zoom, zone-panel toggle) and a per-tool context row
whose contents are swapped by visibility toggling. **Pan is gone** as a
mode — Edit is the default tool, and panning is now an implicit gesture
(middle-button drag, or hold Space and drag) available under every tool;
an empty-canvas left-drag in Edit is a marquee multi-select instead.
Draw gained an Event Zone/Ignore Zone/Lineal sub-type toggle wired to the
`DrawKind` descriptors 3.2a built (gui/drawing.py).

Phase 3.2c (PHASE3_UI_PLAN.md §6) finishes multi-select: the zone table's
checkbox column now syncs a *set* of rows both ways with `ctrl.selection`
(scoped to one sensor, per §6.1 — a cross-sensor pick collapses to the last
row's sensor), and the Edit context bar's new Rotate button drives a
2-click pivot → commit workflow over `model/geometry.py`'s rotation math
(`ctrl.rotate_selection`); rotating an attached zone detaches it from its
centerline (§6.4). Properties is disabled for a multi-selection — bulk
edit is a later add (§8.2) — so Delete/Move/Rotate are the group tools.

Phase 4.3 wires the Phase 4.1 advanced template engine
(`model/templates.py`'s `expand_template`/`PlacementContext`) into the
Template tool: picking a template that leaves any of direction/thru
phase/LT phase/Base Output as a placeholder (`None`) opens a "placement
values" dialog for just those fields; the resulting `PlacementContext`
flows into every preview and placement call. A template with everything
baked in (the Session 6.3-era templates) places exactly as before, with no
dialog. The context-bar "placement values" button (pencil icon) reopens the
dialog to change values — e.g. a new Base Output — between placements of
the same template on different approaches.

The Template context bar's editor button (pencil-and-square icon) opens the
Phase 4.2 grid editor (`gui/templates_ui.py`) in a new browser tab. That
editor owns its own NiceGUI event loop, so it can't be built into this page
directly — the button spawns it as a subprocess on `--port` + 1000 the
first time it's used (reused after) and opens straight to whatever template
is currently picked in the Template tool, if any.

ROADMAP Item 1 reworks the old Measure tool: renamed to Background (2-point
and known-width/height calibration unchanged), plus an in-place
background-image upload for an already-open project (zones/sensors/
centerlines kept). Ruler moves out of Background's old sub-type toggle and
onto the persistent chrome row as an independent overlay (`ruler_active`)
that captures clicks over whatever tool is active, rather than a mode you
switch into — mirrors how space_pan already works in every tool. Marker
(`Viewer.markers`) is removed entirely.

Usage:
    python gui/app.py [site.iprj | background.png] [--port 8080]

Defaults to sites/Banks/banks.iprj. Open http://localhost:<port> in a
browser. Mouse wheel zooms at the cursor; drag pans with the middle
button, or hold Space and drag, in any tool. Use New/Open in the File menu
to switch projects without restarting the app, or the Background tool's
upload button to replace the current project's image in place.

Keys: d Draw · e Edit · t Template · c Centerline · s Sensor ·
r ruler (toggle, any tool) · (within Draw) z Event Zone · l Lineal ·
i Ignore Zone · g snap · u / Ctrl-Z undo · Esc cancel · digits + Enter
dimension entry (Event Zone/Ignore) · n/b cycle selection · arrows nudge ·
x/Del delete · Shift-click toggles a zone in/out of the selection ·
Ctrl-drag copies the selected zone · p / double-click zone properties ·
v insert vertex (single selection, Edit tool) · f fit view · Ctrl-S save.
Free-draw Event Zone/Ignore polygons take any number of corners; finish
with Enter or a double-click (ROADMAP Item 7).

Edit tool: click a zone to select it; Shift-click toggles membership in a
multi-selection; drag a body/corner to move; an empty-canvas drag marquees
every zone it touches. Arrows nudge and x/Del deletes the whole selection
as one undo step. The zone table's checkbox column mirrors the canvas
selection both ways (Event Zone kind only). Rotate (context bar) arms a 2-click
workflow: click to place the pivot, move to aim (live preview + angle
readout), click again to commit — Esc cancels. Rotating a zone that was
attached to a centerline detaches it. Properties opens only for a single
selection; use Delete/Move/Rotate for group edits. `v` inserts a vertex
into the single selected element, on the edge nearest the cursor.

Draw tool: the sub-type toggle (context bar) picks what a click places —
Event Zone, Ignore Zone, or Lineal (generic 2-point reference line). Event
Zone and Ignore Zone are 4-click/dimensioned polygons; Lineal is a 2-click
segment. The sub-type also retargets Edit — pick Ignore Zone or Lineal in
Draw to then select/edit that kind's elements.

Background tool: click two reference points then enter the known distance
between them (2-point calibration), or use the context bar's calibrate
button to enter a known image width/height instead. The context bar's
upload button replaces the open project's background image in place —
zones, sensors, and centerlines are kept; recalibrate afterward if the new
image is at a different scale.

Ruler: a persistent chrome-row toggle (r), not a tool — click to set the
first point, move to see the live distance in feet, click again (or
release a drag) to set the second, while whatever tool you're already in
(Draw, Edit, …) stays active underneath. "Clear ruler" next to it clears
the measurement; Esc cancels one in progress.

Template tool: pick a template from the context bar dropdown; if it leaves
any placement value unresolved, a dialog prompts for direction/thru
phase/LT phase/Base Output before you can place it (reopen it any time via
the "placement values" button). Then click the anchor reference point
(where the stop bar crosses the template's anchor lane line — by default
the line between the exclusive left-turn lanes and the thru lanes). With a
centerline drawn, that one click places the whole detector set along the
nearest centerline within a snap threshold (~40 ft laterally, Item 19); with
no centerline near (or the "along CL" toggle off), click again to aim
upstream and place along that straight line. The "pick CL" dropdown pins
placement to one specific centerline instead, bypassing the threshold.
Centerline-placed zones stay attached: reshaping the centerline re-stations
them. The .iprj cannot store the attachment itself, so reopening a project
re-derives it — zones that are still exact station/offset rectangles on a
centerline re-attach automatically (a notification reports how many).

Centerline tool: pick the active centerline from its selector (or add a new
one for another approach), then click along it starting at the stop bar
(station 0) and continuing upstream; click-drag repositions a vertex, x/Del
removes the selected one. Name the active centerline in the "name" box
(Item 20; session-only, e.g. N_CL for the north approach) — the name shows
in every centerline picker, including the template "pick CL" dropdown. The
status/position readouts show live station + offset while the tool is
active. All centerlines in the project render at once; only the active one
is editable.
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import base64
import io
import math
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nicegui import ui

from gui.drawing import (ARROWS, DIM_OFF, IGNORE_KIND, LINEAL_KIND, LOOP_KIND,
                         NUDGE_FT, CenterlineController, DrawingController,
                         derive_attachments, element_points, insert_zone,
                         is_placeholder, next_output_number)
from gui.viewport import MAX_SCALE, MIN_SCALE, Viewport
from model import domain, geometry, units
from model.centerline import (load_centerlines, load_lineals,
                              save_centerlines, save_lineals)
from model.iprj_io import (Background, Condition, EventZone, Project, Sensor,
                           load_iprj, save_iprj)
from model.multifile import (MAX_SENSORS, BackgroundMismatch,
                             check_background_match, is_multifile,
                             is_valid_pair, merge_pair, pair_paths,
                             pair_role, split_project)
from model.templates import (DIRECTIONS, PlacementContext, expand_and_place,
                             expand_and_place_on_centerline, load_template,
                             missing_placeholders)

REPO = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"

PHASE_COLORS = ["#d62728", "#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd",
                "#8c564b", "#e377c2", "#bcbd22", "#17becf"]

# How far (feet, laterally) the template anchor click may sit from a
# centerline and still snap "along" it (Item 19). The old behavior had no
# threshold — any click followed the nearest centerline however far away —
# which made snapping overwhelmingly strong. One approach's worth of lanes
# is a generous but bounded reach; beyond it, placement falls back to the
# aim-upstream click. Only consulted for the auto/nearest path; an explicitly
# picked centerline (the toolbar dropdown) ignores it.
CENTERLINE_SNAP_FT = 40.0

# Draw sub-types (PHASE3_UI_PLAN §4.1) shown in the Draw tool's context bar.
DRAW_KINDS = {"Event Zone": LOOP_KIND, "Ignore Zone": IGNORE_KIND, "Lineal": LINEAL_KIND}

# Vendor-confirmed ZoneType names (see model/domain.py): 0 Motion,
# 1 Presence, 2 Sidewalk.
ZONE_TYPE_NAMES = {int(t): f"{int(t)} — {name}"
                   for t, name in domain.ZONE_TYPE_NAMES.items()}

# Vendor-default condition factory moved to the model layer in Phase 2.
new_condition = domain.default_condition

# int-keyed copies of the enum-name maps (mirrors ZONE_TYPE_NAMES above) —
# plain-int keys serialize cleanly as ui.select options.
_VEHICLE_CLASS_OPTS = {int(k): v for k, v in domain.VEHICLE_CLASS_NAMES.items()}
_DIRECTION_OPTS = {int(k): v for k, v in domain.DIRECTION_NAMES.items()}

# Per-Condition-field widget specs, keyed by the domain.CONDITION_FIELDS names
# (Item 2 of ROADMAP.md) — which fields render in a condition row is decided
# by domain.condition_fields(zone.zone_type), not this dict; this only says
# *how* to render a field once it's selected.
_COND_FIELD_SPECS: dict[str, dict] = {
    "output_number": dict(label="output", kind="int"),
    "condition_class": dict(label="class", kind="select", options=_VEHICLE_CLASS_OPTS),
    "direction": dict(label="direction", kind="select", options=_DIRECTION_OPTS),
    "event_message_delay": dict(label="delay", kind="int"),
    "event_message_extend": dict(label="extend", kind="int"),
    "velocity_min": dict(label="v min (mph)", kind="float",
                         to_ui=units.kmh_to_mph, to_model=units.mph_to_kmh),
    "velocity_max": dict(label="v max (mph)", kind="float",
                         to_ui=units.kmh_to_mph, to_model=units.mph_to_kmh),
    "queuelength_min": dict(label="queue min (ft)", kind="float",
                            to_ui=units.m_to_ft, to_model=units.ft_to_m),
    "queuelength_max": dict(label="queue max (ft)", kind="float",
                            to_ui=units.m_to_ft, to_model=units.ft_to_m),
    "eta_min": dict(label="eta min (s)", kind="float"),
    "eta_max": dict(label="eta max (s)", kind="float"),
    "nr_pedest_min": dict(label="ped min", kind="int"),
    "nr_pedest_max": dict(label="ped max", kind="int"),
    "nr_cars_min": dict(label="cars min", kind="int"),
    "nr_cars_max": dict(label="cars max", kind="int"),
    "nr_small_trucks_min": dict(label="sm truck min", kind="int"),
    "nr_small_trucks_max": dict(label="sm truck max", kind="int"),
    "nr_big_trucks_min": dict(label="big truck min", kind="int"),
    "nr_big_trucks_max": dict(label="big truck max", kind="int"),
}


def open_project(path: Path) -> Project:
    if path.suffix.lower() == ".iprj":
        return load_iprj(path)
    # New project from a plain image: embed as PNG (the format all real
    # files use), identity placement, calibration left for the user.
    img = Image.open(path)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    bg = Background(image_base64=base64.b64encode(buf.getvalue()).decode("ascii"))
    return Project(background=bg)


def template_files() -> dict[str, str]:
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    return {str(p): p.name for p in sorted(TEMPLATES_DIR.glob("*.json"))}


def iprj_files() -> dict[str, str]:
    root = REPO / "sites"
    if not root.is_dir():
        return {}
    return {str(p): str(p.relative_to(root)) for p in sorted(root.glob("**/*.iprj"))}


# ---------------------------------------------------------------------------
# SVG overlay (image-pixel coordinate space)
# ---------------------------------------------------------------------------

def _polygon(points_img, **attrs) -> str:
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points_img)
    a = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return f'<polygon points="{pts}" {a}/>'


def _cross(x: float, y: float, size: float, color: str, width: float) -> str:
    return (f'<path d="M {x - size} {y} H {x + size} M {x} {y - size} V {y + size}" '
            f'stroke="{color}" stroke-width="{width}" fill="none"/>')


class Viewer:
    def __init__(self, project: Project, source: Path, pair: tuple[Path, Path] | None = None):
        self.project = project
        self.source = source
        # Item 9: (_1_2 path, _3_4 path) when this project spans two files —
        # either opened via overlay-merge or already saved as a pair. None
        # for an ordinary <=2-sensor single-file project.
        self.pair = pair
        self.bg = project.background
        # Serve the background as a PNG *file*, never a PIL object: NiceGUI
        # retains per-client state around PIL-sourced images (~2x the decoded
        # bitmap, ~60 MB for Banks, per page request) which OOMs the server;
        # a file source is streamed and costs nothing per client. Only the
        # dimensions are kept — the pixels are never decoded server-side.
        if self.bg.image_base64:
            png = units.decode_background_image(self.bg)
        else:
            buf = io.BytesIO()
            Image.new("RGB", (800, 600), "gray").save(buf, format="PNG")
            png = buf.getvalue()
        with Image.open(io.BytesIO(png)) as im:  # header only, lazy
            self.image_w, self.image_h = im.size
        fd, name = tempfile.mkstemp(prefix="iprj_bg_", suffix=".png")
        with os.fdopen(fd, "wb") as f:
            f.write(png)
        self.image_file = Path(name)
        atexit.register(lambda p=self.image_file: p.unlink(missing_ok=True))
        self.viewport = Viewport()
        # Phase 3.2b: 6 primary tools (Edit/Draw/Template/Centerline/
        # Sensor/Background) replace the old 9-entry flat toggle; Pan is gone
        # (PHASE3_UI_PLAN §5) — Edit is the default and panning is an
        # implicit gesture (space_pan / middle-drag) available everywhere.
        self.mode = "Edit"
        self.space_pan = False       # True while the space bar is held
        # Draw sub-type (Event Zone/Ignore Zone/Lineal, §4) also selects what
        # Edit operates on — the two tools share one DrawingController
        # pointed at one element list/kind at a time.
        self.draw_kind_name = "Event Zone"
        # Marquee multi-select (§6.2): set while an empty-canvas drag is
        # rubber-banding a selection rectangle in the Edit tool.
        self.marquee_anchor: tuple[float, float] | None = None  # world px
        self.marquee_cursor: tuple[float, float] | None = None  # world px
        self.marquee_additive = False
        # Rotate (§6.4): armed by the context-bar Rotate button, then a
        # 2-click pivot -> commit workflow. `rotate_pivot` is None until
        # click 1; `rotate_ray` freezes the first post-pivot cursor position
        # as the angle-measure's reference ray so `rotate_angle` tracks the
        # mouse live until click 2 commits via `ctrl.rotate_selection`.
        self.rotate_armed = False
        self.rotate_pivot: tuple[float, float] | None = None  # world px
        self.rotate_ray: tuple[float, float] | None = None    # world px
        self.rotate_angle = 0.0  # degrees, model.geometry convention
        self.show_zones = True     # layer toggles (background is CSS-only)
        self.show_labels = True
        self.show_sensors = True
        self.cal_points: list[tuple[float, float]] = []  # world px, pending 2-pt
        self.drag_anchor: tuple[float, float] | None = None
        self.sensor_drag: dict | None = None  # in-flight sensor move
        # Ruler (Item 1): an independent overlay toggle rather than a mode —
        # like space_pan, it captures canvas clicks over whatever tool is
        # active instead of living in the tool toggle/Background sub-type.
        # 2-point: click to start, click again (or a real drag-release) to
        # end; ruler_pending is true between the two.
        self.ruler_active = False
        self.ruler_start: tuple[float, float] | None = None  # world px
        self.ruler_end: tuple[float, float] | None = None    # world px
        self.ruler_pending = False
        # Generic (non-chain) Lineals: a project-wide pool the Lineal draw
        # kind targets, round-tripped via model/centerline.py's
        # load_lineals/save_lineals (PHASE3_UI_PLAN §4.3).
        self.lineals: list = load_lineals(project)
        # px per SVG unit shrinks as we zoom in; keep overlay strokes readable
        self.overlay_px = 2.0
        # template placement (Session 6.3): ref click -> aim click -> place
        self.template = None  # ApproachTemplate | None
        self.template_ref: tuple[float, float] | None = None  # world px
        self.template_cursor: tuple[float, float] | None = None  # world px
        # Phase 4.3: placement-time values for the template's placeholder
        # fields (direction/thru_phase/lt_phase/base_output — see
        # model.templates.PlacementContext). Reset whenever the template
        # selection changes; edited via the "placement values" dialog.
        self.template_context = PlacementContext()
        # Item 19: whether template placement follows a centerline at all, and
        # optionally which one. follow=True + idx=None is the default (snap to
        # the nearest centerline within CENTERLINE_SNAP_FT of the anchor,
        # else aim-upstream); follow=False forces aim-upstream; a non-None idx
        # pins placement to that specific centerline (no nearest/threshold).
        self.template_follow_centerline = True
        self.template_centerline_idx: int | None = None
        # approach centerlines (Session 7.2 draw/edit, Session 7.4
        # persistence): one CenterlineController per centerline found in the
        # project's Lineals, plus a fresh empty one ready to draw if there
        # were none; active_cli picks which is currently editable.
        self.centerlines: list[CenterlineController] = []
        for pts in load_centerlines(project):
            ctrl = CenterlineController(self.ft_per_px)
            ctrl.points = list(pts)
            self.centerlines.append(ctrl)
        if not self.centerlines:
            self.centerlines.append(CenterlineController(self.ft_per_px))
        self.active_cli = 0
        # drawing/editing operates on the active sensor's zones
        if not project.sensors:
            project.sensors.append(Sensor())
        self.active_si = 0
        self.ctrl = DrawingController(self.draw_zones(),
                                      self.ft_per_px, self.next_output)
        # self.mode defaults to "Edit" (ctrl.mode "edit"); a ui.toggle's on_change
        # fires only on a user-driven change, never for its initial value,
        # so the controller needs this nudge to start in step with the tool.
        self.ctrl.set_mode("edit")
        # Attachments don't persist in the .iprj, so re-derive them: zones
        # that are exact station/offset rectangles on a loaded centerline
        # follow centerline edits again after reopening the project.
        self.derived_attachments = derive_attachments(
            self.centerlines, [s.event_zones for s in project.sensors])

    def next_output(self) -> int:
        return next_output_number(s.event_zones for s in self.project.sensors)

    def active_zones(self):
        return self.project.sensors[self.active_si].event_zones

    def draw_zones(self) -> list:
        """The element list the active draw kind/Edit targets: the active
        sensor's event zones or ignore zones, or the project-wide lineal
        pool (PHASE3_UI_PLAN §4.1, §6.1 — one kind/list at a time)."""
        if self.draw_kind_name == "Event Zone":
            return self.active_zones()
        if self.draw_kind_name == "Ignore Zone":
            return self.project.sensors[self.active_si].ignore_zones
        return self.lineals

    def set_active_sensor(self, si: int) -> None:
        self.active_si = si
        self.ctrl.retarget(self.draw_zones())

    def set_draw_kind(self, name: str) -> None:
        """Switch the Draw sub-type (and what Edit operates on);
        retargeting clears the selection (§6.1)."""
        self.draw_kind_name = name
        self.ctrl.retarget(self.draw_zones(), DRAW_KINDS[name])

    @property
    def centerline_ctrl(self) -> CenterlineController:
        return self.centerlines[self.active_cli]

    def set_active_centerline(self, ci: int) -> None:
        self.centerlines[self.active_cli].end_drag()
        self.active_cli = ci

    def add_centerline(self) -> int:
        self.centerlines.append(CenterlineController(self.ft_per_px))
        self.active_cli = len(self.centerlines) - 1
        return self.active_cli

    def centerline_label(self, i: int) -> str:
        """Display name for centerline *i* — its session name (Item 20) or
        the positional C{n} fallback."""
        return self.centerlines[i].name or f"C{i + 1}"

    def centerline_for(self, p) -> CenterlineController | None:
        """The drawn centerline nearest world point *p* (smallest |offset|
        of its projection) *within CENTERLINE_SNAP_FT laterally* — the datum
        template placement snaps to — or None when none qualifies (no usable
        datum yet, or all of them are farther than the threshold). Item 19
        added the threshold; before it any click followed the nearest datum
        however far away."""
        fpp = self.ft_per_px()
        max_off = None if fpp is None else CENTERLINE_SNAP_FT / fpp
        datums = [ctrl.current() for ctrl in self.centerlines]
        i = geometry.nearest_centerline(datums, p, max_off)
        return None if i is None else self.centerlines[i]

    def template_target_centerline(self, p) -> CenterlineController | None:
        """Which centerline (if any) template placement should follow for an
        anchor click at world point *p*, honoring the Item 19 toolbar state:
        an explicitly picked centerline pins placement (no threshold); else,
        when following is on, the nearest within CENTERLINE_SNAP_FT; else
        None (aim-upstream placement)."""
        idx = self.template_centerline_idx
        if idx is not None and 0 <= idx < len(self.centerlines):
            ctrl = self.centerlines[idx]
            return ctrl if ctrl.current() is not None else None
        if not self.template_follow_centerline:
            return None
        return self.centerline_for(p)

    def reproject_attachments(self) -> None:
        """After a manual zone edit: let every centerline re-derive its
        attached zones' station/offset coords from their current points."""
        for cl in self.centerlines:
            cl.reproject()

    def sensor_at(self, p) -> int:
        """Index of the sensor within grab radius of world point p, or -1."""
        best, best_d = -1, None
        for i, s in enumerate(self.project.sensors):
            if s.position_x is None or s.position_y is None:
                continue
            d = math.dist(p, (s.position_x, s.position_y))
            if d <= self.ctrl.handle_radius * 1.5 and (best_d is None or d < best_d):
                best, best_d = i, d
        return best

    # -- coordinate helpers -------------------------------------------------

    def ft_per_px(self) -> float | None:
        try:
            return units.ft_per_px(self.bg)
        except ValueError:
            return None

    def describe(self, image_point) -> str:
        wx, wy = units.image_to_world(self.bg, image_point)
        fpp = self.ft_per_px()
        base = (f"{wx:.1f}, {wy:.1f} px (uncalibrated)" if fpp is None else
                f"{wx * fpp:.1f}, {wy * fpp:.1f} ft   ({wx:.1f}, {wy:.1f} px)")
        if self.mode == "Centerline":
            reading = self.centerline_ctrl.station_readout((wx, wy))
            if reading:
                return f"{base}   |   {reading}"
        if self.ruler_active and self.ruler_start is not None and self.ruler_pending:
            return f"{base}   |   distance: {self._ruler_reading(self.ruler_start, (wx, wy))}"
        if self.mode == "Edit" and self.rotate_armed and self.rotate_pivot is not None:
            return f"{base}   |   angle: {self.rotate_angle:+.1f}°"
        return base

    def _ruler_reading(self, p0, p1) -> str:
        d = math.dist(p0, p1)
        fpp = self.ft_per_px()
        return f"{d * fpp:.1f} ft" if fpp is not None else f"{d:.1f} px (uncalibrated)"

    def ruler_status(self) -> str:
        if self.ruler_start is None:
            return "mode: ruler | click to set the first point"
        if self.ruler_pending:
            return ("mode: ruler | drag or click to set the second point  "
                    "[Esc cancels]")
        return (f"mode: ruler | {self._ruler_reading(self.ruler_start, self.ruler_end)} "
                "| click to start a new measurement")

    def template_status(self) -> str:
        if self.template is None:
            return "mode: template | pick a template above"
        missing = missing_placeholders(self.template, self.template_context)
        if missing:
            return (f"mode: template | {self.template.name} | fill in "
                     f"placement values ({', '.join(missing)}) above before "
                     "placing")
        idx = self.template_centerline_idx
        if idx is not None and 0 <= idx < len(self.centerlines) \
                and self.centerlines[idx].current() is not None:
            return (f"mode: template | {self.template.name} | click the "
                    "anchor point (stop bar at the LT/thru lane line) — "
                    f"detectors follow {self.centerline_label(idx)}")
        if self.template_follow_centerline \
                and any(cl.current() is not None for cl in self.centerlines):
            return (f"mode: template | {self.template.name} | click the "
                    "anchor point (stop bar at the LT/thru lane line) — "
                    "detectors follow the nearest centerline within "
                    f"{CENTERLINE_SNAP_FT:.0f} ft, else aim upstream")
        if self.template_ref is None:
            return (f"mode: template | {self.template.name} | click the "
                    "anchor point (stop bar at the LT/thru lane line)")
        return (f"mode: template | {self.template.name} | aim upstream, "
                "click to place  [Esc cancels]")

    # -- overlay ------------------------------------------------------------

    def svg(self) -> str:
        bg = self.bg
        w2i = lambda p: units.world_to_image(bg, p)
        lw = self.overlay_px / max(self.viewport.scale, 0.05)
        font = 7 * lw
        parts = []
        # Whether the DrawingController is currently pointed at *zones* —
        # true for exactly one (sensor, kind) combination at a time
        # (PHASE3_UI_PLAN §6.1), so selection-set membership only means
        # anything for that one list.
        is_draw_target = lambda zones: self.ctrl.mode == "edit" and self.ctrl.zones is zones
        for si, sensor in enumerate(self.project.sensors):
            targeted = is_draw_target(sensor.event_zones)
            for zi, zone in enumerate(sensor.event_zones):
                if not self.show_zones or not zone.enable or len(zone.points) < 3:
                    continue
                color = PHASE_COLORS[(zone.phase_number or 0) % len(PHASE_COLORS)]
                pts = [w2i(p) for p in zone.points]
                selected = targeted and zi in self.ctrl.selection
                if selected:
                    parts.append(_polygon(pts, fill=color, fill_opacity="0.35",
                                          stroke="white", stroke_width=2 * lw))
                    for x, y in pts:
                        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" '
                                     f'r="{3 * lw:.1f}" fill="white" '
                                     f'stroke="black" stroke-width="{lw / 2}"/>')
                else:
                    parts.append(_polygon(pts, fill=color, fill_opacity="0.35",
                                          stroke=color, stroke_width=lw))
                if not self.show_labels:
                    continue
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
                name = escape(zone.zone_name or "")
                parts.append(f'<text x="{cx:.1f}" y="{cy:.1f}" fill="white" '
                             f'font-size="{font:.1f}" text-anchor="middle" '
                             f'paint-order="stroke" stroke="black" '
                             f'stroke-width="{font / 6:.2f}">{name}</text>')
            ig_targeted = is_draw_target(sensor.ignore_zones)
            for ii, zone in enumerate(sensor.ignore_zones):
                if not self.show_zones or not zone.enable or len(zone.points) < 3:
                    continue
                selected = ig_targeted and ii in self.ctrl.selection
                parts.append(_polygon(
                    [w2i(p) for p in zone.points], fill="none",
                    stroke="white" if selected else "#ffd54f",
                    stroke_width=(2 if selected else 1) * lw,
                    stroke_dasharray=f"{4 * lw} {3 * lw}"))
            if self.show_sensors and sensor.position_x is not None:
                x, y = w2i((sensor.position_x, sensor.position_y))
                s = 6 * lw
                fill = "#00e5ff" if si == self.active_si else "white"
                parts.append(_polygon([(x, y - s), (x - s, y + s), (x + s, y + s)],
                                      fill=fill, stroke="black", stroke_width=lw / 2))
                parts.append(f'<text x="{x:.1f}" y="{y + s + font:.1f}" fill="white" '
                             f'font-size="{font:.1f}" text-anchor="middle" '
                             f'paint-order="stroke" stroke="black" '
                             f'stroke-width="{font / 6:.2f}">S{si + 1}</text>')
        # generic Lineals (§4.1 LINEAL_KIND): thin gray, distinct from the
        # green centerlines above so the two never read as the same thing.
        lin_targeted = is_draw_target(self.lineals)
        for li, lineal in enumerate(self.lineals):
            pts = [w2i(p) for p in element_points(lineal)]
            if not self.show_zones or not lineal.enable or len(pts) != 2:
                continue
            selected = lin_targeted and li in self.ctrl.selection
            color = "white" if selected else "#9e9e9e"
            width = (2 if selected else 1) * lw
            parts.append(f'<line x1="{pts[0][0]:.1f}" y1="{pts[0][1]:.1f}" '
                         f'x2="{pts[1][0]:.1f}" y2="{pts[1][1]:.1f}" '
                         f'stroke="{color}" stroke-width="{width:.2f}"/>')
        for ci, cl in enumerate(self.centerlines):
            cl_pts = [w2i(p) for p in cl.points]
            active = ci == self.active_cli
            color = "#39ff14" if active else "#1f9c0c"
            if len(cl_pts) >= 2:
                coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in cl_pts)
                parts.append(f'<polyline points="{coords}" fill="none" '
                             f'stroke="{color}" stroke-width="{1.5 * lw:.2f}" '
                             f'stroke-dasharray="{4 * lw} {2 * lw}"/>')
            for i, (x, y) in enumerate(cl_pts):
                selected = self.mode == "Centerline" and active and i == cl.selected
                r = (4 if i == 0 else 3) * lw
                fill = "white" if selected else color
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" '
                             f'fill="{fill}" stroke="black" stroke-width="{lw / 2:.2f}"/>')
                if i == 0:
                    parts.append(f'<text x="{x:.1f}" y="{y - 6 * lw:.1f}" fill="{color}" '
                                 f'font-size="{font:.1f}" text-anchor="middle" '
                                 f'paint-order="stroke" stroke="black" '
                                 f'stroke-width="{font / 6:.2f}">0</text>')
        if bg.ref0_x is not None and bg.ref1_x is not None:
            p0, p1 = w2i((bg.ref0_x, bg.ref0_y)), w2i((bg.ref1_x, bg.ref1_y))
            parts.append(f'<line x1="{p0[0]:.1f}" y1="{p0[1]:.1f}" x2="{p1[0]:.1f}" '
                         f'y2="{p1[1]:.1f}" stroke="red" stroke-width="{lw / 2}" '
                         f'stroke-dasharray="{2 * lw} {2 * lw}"/>')
            for p in (p0, p1):
                parts.append(_cross(p[0], p[1], 5 * lw, "red", lw))
        for wp in self.cal_points:
            x, y = w2i(wp)
            parts.append(_cross(x, y, 6 * lw, "magenta", lw))
        if self.ruler_start is not None and self.ruler_end is not None:
            p0, p1 = w2i(self.ruler_start), w2i(self.ruler_end)
            parts.append(f'<line x1="{p0[0]:.1f}" y1="{p0[1]:.1f}" x2="{p1[0]:.1f}" '
                         f'y2="{p1[1]:.1f}" stroke="#ffab00" stroke-width="{lw}" '
                         f'stroke-dasharray="{3 * lw} {2 * lw}"/>')
            for p in (p0, p1):
                parts.append(_cross(p[0], p[1], 4 * lw, "#ffab00", lw))
            label = self._ruler_reading(self.ruler_start, self.ruler_end)
            mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
            parts.append(f'<text x="{mx:.1f}" y="{my - 5 * lw:.1f}" fill="#ffab00" '
                         f'font-size="{font:.1f}" text-anchor="middle" '
                         f'paint-order="stroke" stroke="black" '
                         f'stroke-width="{font / 6:.2f}">{label}</text>')
        if self.marquee_anchor is not None and self.marquee_cursor is not None:
            a, b = w2i(self.marquee_anchor), w2i(self.marquee_cursor)
            x0, x1 = sorted((a[0], b[0]))
            y0, y1 = sorted((a[1], b[1]))
            parts.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" '
                         f'width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" '
                         f'fill="#00e5ff" fill-opacity="0.08" stroke="#00e5ff" '
                         f'stroke-width="{lw}" stroke-dasharray="{3 * lw} {2 * lw}"/>')
        # rotate (§6.4): pivot cross (seeded at the selection centroid before
        # click 1 places it explicitly) plus a live rotated-outline preview
        # of every selected element once the user is aiming past the pivot.
        if self.mode == "Edit" and self.rotate_armed:
            pivot = self.rotate_pivot or self.ctrl.selection_centroid()
            if pivot is not None:
                px, py = w2i(pivot)
                parts.append(_cross(px, py, 6 * lw, "#ff4081", lw))
                if self.rotate_pivot is not None and self.rotate_angle:
                    for i in self.ctrl.selection:
                        if i >= len(self.ctrl.zones):
                            continue
                        pts = geometry.rotate_points(
                            element_points(self.ctrl.zones[i]),
                            self.rotate_angle, pivot)
                        img_pts = [w2i(pt) for pt in pts]
                        if len(img_pts) >= 3:
                            parts.append(_polygon(
                                img_pts, fill="none", stroke="#ff4081",
                                stroke_width=lw, stroke_dasharray=f"{3 * lw} {2 * lw}"))
                        elif len(img_pts) == 2:
                            parts.append(
                                f'<line x1="{img_pts[0][0]:.1f}" y1="{img_pts[0][1]:.1f}" '
                                f'x2="{img_pts[1][0]:.1f}" y2="{img_pts[1][1]:.1f}" '
                                f'stroke="#ff4081" stroke-width="{lw}" '
                                f'stroke-dasharray="{3 * lw} {2 * lw}"/>')
        # in-progress drawing: clicked corners, rubber-band preview, snap dot
        preview = self.ctrl.preview_polygon()
        if preview and len(preview) >= 2:
            pts = [w2i(p) for p in preview]
            coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
            tag = "polygon" if len(pts) >= 3 else "polyline"
            parts.append(f'<{tag} points="{coords}" fill="#00e5ff" '
                         f'fill-opacity="0.15" stroke="#00e5ff" '
                         f'stroke-width="{lw}" '
                         f'stroke-dasharray="{3 * lw} {2 * lw}"/>')
        for wp in self.ctrl.pending:
            x, y = w2i(wp)
            parts.append(_cross(x, y, 4 * lw, "#00e5ff", lw))
        if self.ctrl.snap_indicator is not None:
            x, y = w2i(self.ctrl.snap_indicator)
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{4 * lw:.1f}" '
                         f'fill="none" stroke="orange" stroke-width="{lw}"/>')
        # template placement: reference marker, aim line, live detector preview.
        # With a usable centerline the preview follows it at the hover point
        # (single click places); otherwise the legacy ref-then-aim flow.
        if self.mode == "Template" and self.template is not None:
            cursor = self.template_cursor
            # mirror place_template's target so the preview matches what the
            # click will actually do (Item 19 toggle/pick/threshold state)
            cl_ctrl = (self.template_target_centerline(cursor)
                       if cursor is not None else None)
            placed = []
            fpp = self.ft_per_px()
            if cl_ctrl is not None:
                cx, cy = w2i(cursor)
                parts.append(_cross(cx, cy, 5 * lw, "#00e5ff", lw))
                if fpp is not None:
                    try:
                        placed = expand_and_place_on_centerline(
                            self.template, cl_ctrl.points, cursor, 1.0 / fpp,
                            self.template_context)
                    except ValueError:
                        placed = []
            elif self.template_ref is not None:
                rx, ry = w2i(self.template_ref)
                parts.append(_cross(rx, ry, 5 * lw, "#00e5ff", lw))
                if cursor is not None:
                    cx, cy = w2i(cursor)
                    parts.append(f'<line x1="{rx:.1f}" y1="{ry:.1f}" x2="{cx:.1f}" '
                                 f'y2="{cy:.1f}" stroke="#00e5ff" stroke-width="{lw}" '
                                 f'stroke-dasharray="{3 * lw} {2 * lw}"/>')
                    upstream = (cursor[0] - self.template_ref[0],
                               cursor[1] - self.template_ref[1])
                    if fpp is not None and math.hypot(*upstream) > 1e-6:
                        try:
                            placed = expand_and_place(self.template, self.template_ref,
                                                      upstream, 1.0 / fpp,
                                                      self.template_context)
                        except ValueError:
                            placed = []
            for det in placed:
                parts.append(_polygon([w2i(pt) for pt in det.points],
                                      fill="#00e5ff", fill_opacity="0.12",
                                      stroke="#00e5ff", stroke_width=lw,
                                      stroke_dasharray=f"{3 * lw} {2 * lw}"))
        return "".join(parts)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

# Client-side wheel-zoom (Item 14). The freeze on large-background/many-loop
# files was a per-event server round-trip: every wheel tick re-ran the Python
# handler, re-sent the whole SVG overlay, and — the expensive part — made the
# browser re-parse that overlay (interactive_image.updated() → innerHTML) and
# re-composite the scaled 9.6 MP background. Unthrottled, a fast scroll fires
# 60–120 events/s and saturates the browser main thread; the missed socket
# heartbeat drops the connection, and the fit-on-reload snaps back to the
# zoomed-out view. Doing the CSS transform in JS makes zooming a GPU-cheap
# local update with no content re-parse, and the (throttled) emit only syncs
# *absolute* viewport state so the server can refresh overlay stroke-widths
# and the status label. Absolute state (not deltas) keeps it idempotent: a
# dropped or reordered sync just means last-write-wins, never lost zoom.
# `emit` is captured from NiceGUI's event closure, so this must stay an inline
# arrow (a head-defined global couldn't see `emit`). getComputedStyle re-reads
# the live matrix each tick, so server-driven pan/fit stay authoritative
# between gestures. e.offsetX/Y are the img's untransformed local coords
# (= image pixels), exactly what the old server handler consumed.
_WHEEL_ZOOM_JS = f"""(e) => {{
  const el = e.currentTarget;
  const cs = getComputedStyle(el).transform;
  let s = 1, tx = 0, ty = 0;
  if (cs && cs !== 'none') {{
    const m = cs.match(/matrix\\(([^)]+)\\)/);
    if (m) {{ const p = m[1].split(',').map(Number); s = p[0]; tx = p[4]; ty = p[5]; }}
  }}
  const ns = Math.min({MAX_SCALE}, Math.max({MIN_SCALE}, s * Math.pow(0.9, e.deltaY / 100)));
  const k = ns / s;
  tx += s * e.offsetX * (1 - k);
  ty += s * e.offsetY * (1 - k);
  s = ns;
  el.style.transformOrigin = '0 0';
  el.style.transform = `translate(${{tx}}px, ${{ty}}px) scale(${{s}})`;
  emit({{scale: s, tx: tx, ty: ty}});
}}"""


def build_ui(viewer: Viewer, state: dict) -> None:
    v = viewer

    # interactive_image's <img> sets opacity via an inline Vue :style
    # binding, which always wins over a class selector — !important is
    # required for .bg-off to actually hide it.
    ui.add_head_html(
        "<style>body { background: #222; } "
        ".bg-off img { opacity: 0 !important; }</style>"
        # keep Ctrl-S for project save instead of the browser's save dialog
        "<script>document.addEventListener('keydown', e => {"
        " if ((e.ctrlKey || e.metaKey) && e.key === 's') e.preventDefault();"
        " });</script>")

    def refresh_overlay():
        ii.content = v.svg()

    def apply_transform():
        ii.style(v.viewport.css())
        # snap/grab radii feel constant on screen regardless of zoom
        f = units.image_scale_factor(v.bg) / max(v.viewport.scale, 0.05)
        v.ctrl.snap_radius = 12.0 * f
        v.ctrl.handle_radius = 10.0 * f
        for cl in v.centerlines:
            cl.handle_radius = 10.0 * f
        refresh_overlay()  # stroke widths track zoom level

    def status_scale() -> str:
        fpp = v.ft_per_px()
        cal = f"{fpp:.3f} ft/px" if fpp is not None else "UNCALIBRATED"
        return f"{cal} | zoom {v.viewport.scale:.2f}x"

    # -- calibration flows ---------------------------------------------------

    def finish_two_point():
        with ui.dialog() as dialog, ui.card():
            ui.label("Distance between the two points:")
            dist = ui.number("feet", value=100.0, min=0.1)

            def apply():
                units.calibrate_two_points(v.bg, v.cal_points[0], v.cal_points[1],
                                           float(dist.value))
                v.cal_points.clear()
                dialog.close()
                scale_label.set_text(status_scale())
                refresh_overlay()
                ui.notify(f"Calibrated: {v.ft_per_px():.4f} ft/px")

            def cancel():
                v.cal_points.clear()
                dialog.close()
                refresh_overlay()

            with ui.row():
                ui.button("Apply", on_click=apply)
                ui.button("Cancel", on_click=cancel)
        dialog.open()

    def calibrate_by_size():
        f = units.image_scale_factor(v.bg)
        with ui.dialog() as dialog, ui.card():
            ui.label("Known image dimension (fill either):")
            width = ui.number("image width (ft)", min=1)
            height = ui.number("image height (ft)", min=1)

            def apply():
                if width.value:
                    units.calibrate_image_width(v.bg, v.image_w * f,
                                                float(width.value))
                elif height.value:
                    units.calibrate_image_height(v.bg, v.image_h * f,
                                                 float(height.value))
                else:
                    ui.notify("enter a width or a height", type="warning")
                    return
                dialog.close()
                scale_label.set_text(status_scale())
                refresh_overlay()
                ui.notify(f"Calibrated: {v.ft_per_px():.4f} ft/px")

            with ui.row():
                ui.button("Apply", on_click=apply)
                ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    # -- zone properties -------------------------------------------------------

    def zone_properties(si: int | None = None, zi: int | None = None):
        if si is None:  # toolbar/keyboard path: current canvas selection
            if v.mode != "Edit" or v.draw_kind_name != "Event Zone":
                ui.notify("select an event zone in the Edit tool first", type="warning")
                return
            if len(v.ctrl.selection) > 1:
                # bulk edit is a v1 follow-up (PHASE3_UI_PLAN §8.2) — the
                # floor is disabling single-zone Properties for a group
                ui.notify("select exactly one zone for properties",
                          type="warning")
                return
            si, zi = v.active_si, v.ctrl.selected
        zones = v.project.sensors[si].event_zones
        if not (0 <= zi < len(zones)) or is_placeholder(zones[zi]):
            ui.notify("select a zone first", type="warning")
            return
        zone = zones[zi]
        sensor_opts = {i: f"S{i + 1}" for i in range(len(v.project.sensors))}
        type_opts = dict(ZONE_TYPE_NAMES)
        if (zone.zone_type or 0) not in type_opts:
            type_opts[zone.zone_type] = str(zone.zone_type)

        with ui.dialog() as dialog, ui.card().style("min-width: 640px"):
            ui.label("Zone properties").classes("text-lg")
            with ui.row().classes("w-full items-center"):
                enable = ui.checkbox("Enabled", value=bool(zone.enable))
                name = ui.input("Name", value=zone.zone_name or "").classes("grow")
            with ui.row().classes("items-center"):
                phase = ui.number("Phase", value=zone.phase_number or 0,
                                  min=0, precision=0).classes("w-20")
                output = ui.number("Output", value=zone.output_number or 0,
                                   min=0, precision=0).classes("w-20")
                ztype = ui.select(type_opts, value=zone.zone_type or 0,
                                  label="Type").classes("w-36")
                delay = ui.number("Delay", value=zone.event_message_delay or 0,
                                  min=0, precision=0).classes("w-20")
                extend = ui.number("Extend", value=zone.event_message_extend or 0,
                                   min=0, precision=0).classes("w-20")
                sensor_to = ui.select(sensor_opts, value=si,
                                      label="Sensor").classes("w-24")

            ui.separator()
            cond_rows: list[dict] = []
            # Which Condition fields this zone's type exposes (Item 2 of
            # ROADMAP.md) — fixed to the zone's saved type when the dialog
            # opens, not reactive to the Type select above (see
            # DESIGN_HISTORY.md for why: this dialog's Type field changes
            # zone.zone_type on Apply, not live).
            cond_fields = domain.condition_fields(zone.zone_type)

            def add_cond_row(cond: Condition):
                with conds_col, ui.row().classes("items-center gap-2 flex-wrap") as row_el:
                    entry = {"cond": cond, "en": ui.checkbox(value=bool(cond.enable))}
                    for fname in cond_fields:
                        spec = _COND_FIELD_SPECS[fname]
                        raw = getattr(cond, fname) or 0
                        if spec["kind"] == "select":
                            entry[fname] = ui.select(
                                spec["options"], value=int(raw),
                                label=spec["label"]).classes("w-36")
                        elif spec["kind"] == "float":
                            entry[fname] = ui.number(
                                spec["label"], precision=1,
                                value=round(spec["to_ui"](raw), 1)
                                if "to_ui" in spec else raw).classes("w-28")
                        else:  # int
                            entry[fname] = ui.number(
                                spec["label"], value=int(raw),
                                min=0, precision=0).classes("w-20")
                    ui.button(icon="delete",
                              on_click=lambda e=entry, r=row_el:
                              (cond_rows.remove(e), conds_col.remove(r))) \
                        .props("flat dense")
                cond_rows.append(entry)

            with ui.row().classes("w-full items-center"):
                ui.label("Conditions").classes("text-base")
                add_cond_btn = ui.button(
                    "Add condition",
                    on_click=lambda: add_cond_row(
                        new_condition(int(output.value or 0))))
                if not domain.conditions_allowed(zone.zone_type):
                    add_cond_btn.props("disable")
            conds_col = ui.column().classes("w-full max-h-72 overflow-y-auto")
            for c in zone.conditions:
                add_cond_row(c)

            def apply():
                zone.enable = int(enable.value)
                zone.zone_name = name.value or ""
                zone.phase_number = int(phase.value or 0)
                zone.output_number = int(output.value or 0)
                zone.zone_type = int(ztype.value or 0)
                zone.event_message_delay = int(delay.value or 0)
                zone.event_message_extend = int(extend.value or 0)
                conds = []
                for r in cond_rows:
                    c = r["cond"]
                    c.enable = int(r["en"].value)
                    # Only fields rendered for this zone type are written
                    # back — a hidden field (e.g. a Presence zone's stray
                    # velocity from before this fix) keeps whatever value it
                    # already had rather than being silently zeroed.
                    for fname in cond_fields:
                        spec = _COND_FIELD_SPECS[fname]
                        w = r[fname]
                        if spec["kind"] == "float":
                            val = float(w.value or 0.0)
                            setattr(c, fname,
                                    spec["to_model"](val) if "to_model" in spec else val)
                        else:
                            setattr(c, fname, int(w.value or 0))
                    conds.append(c)
                zone.conditions = conds
                if sensor_to.value != si:
                    zones.pop(zi)
                    if si == v.active_si:  # keep canvas selection consistent
                        if v.ctrl.selected == zi:
                            v.ctrl.selected = -1
                        elif v.ctrl.selected > zi:
                            v.ctrl.selected -= 1
                    tgt = v.project.sensors[sensor_to.value].event_zones
                    insert_zone(tgt, zone)
                    ui.notify(f"moved {zone.zone_name or 'zone'} to S{sensor_to.value + 1}")
                else:
                    ui.notify(f"updated {zone.zone_name or 'zone'}")
                dialog.close()
                refresh_overlay()
                refresh_status()

            with ui.row():
                ui.button("Apply", on_click=apply)
                ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    # -- move along centerline (Item 8) -----------------------------------------

    def attached_centerline_for(zone) -> CenterlineController | None:
        """The centerline *zone* is registered on, or None if it isn't
        attached to any of them."""
        for cl in v.centerlines:
            if id(zone) in cl.attached:
                return cl
        return None

    def move_along_centerline():
        if v.mode != "Edit" or v.draw_kind_name != "Event Zone":
            ui.notify("select an event zone in the Edit tool first", type="warning")
            return
        if len(v.ctrl.selection) != 1:
            ui.notify("select exactly one zone", type="warning")
            return
        zi = v.ctrl.selected
        zone = v.active_zones()[zi]
        cl = attached_centerline_for(zone)
        if cl is None:
            ui.notify("this zone isn't attached to a centerline", type="warning")
            return
        fpp = v.ft_per_px()
        if fpp is None:
            ui.notify("calibrate the background before moving by station",
                      type="warning")
            return
        cur_station_ft = cl.zone_station(zone) * fpp

        with ui.dialog() as dialog, ui.card():
            ui.label(f"Move {zone.zone_name or 'zone'} along centerline") \
                .classes("text-lg")
            ui.label(f"current station: {cur_station_ft:.1f} ft")
            with ui.row().classes("items-center"):
                station = ui.number("Absolute station (ft)",
                                    value=round(cur_station_ft, 1),
                                    precision=1).classes("w-40")
                ui.button("Set", on_click=lambda: apply_move(
                    station=float(station.value or 0.0) / fpp))
            with ui.row().classes("items-center"):
                delta = ui.number("Move by (ft, + upstream)", value=0.0,
                                  precision=1).classes("w-40")
                ui.button("Move", on_click=lambda: apply_move(
                    delta=float(delta.value or 0.0) / fpp))

            def apply_move(*, station: float | None = None,
                           delta: float | None = None):
                old = cl.move_attached(zone, station=station, delta=delta)
                if old is None:
                    ui.notify("move failed — zone no longer attached",
                              type="warning")
                    dialog.close()
                    return
                v.ctrl.record_points_undo(zone, old)
                new_station_ft = cl.zone_station(zone) * fpp
                dialog.close()
                refresh_overlay()
                refresh_status()
                ui.notify(f"moved to station {new_station_ft:.1f} ft")

            ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    # -- sensors ---------------------------------------------------------------

    def sensor_properties(si: int):
        s = v.project.sensors[si]
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Sensor S{si + 1}").classes("text-lg")
            with ui.row().classes("items-center"):
                azimuth = ui.number("Azimuth (deg)", value=s.azimuth_angle or 0.0,
                                    precision=2).classes("w-28")
                elevation = ui.number("Elevation (deg)",
                                      value=s.elevation_angle or 0.0,
                                      precision=2).classes("w-28")
                height = ui.number("Height (ft)", min=0, precision=1,
                                   value=round(units.m_to_ft(
                                       s.installation_height or 0.0), 1)).classes("w-28")
            with ui.row().classes("items-center"):
                lat = ui.number("GPS lat", value=s.gps_lat or 0.0,
                                precision=6).classes("w-36")
                lng = ui.number("GPS lng", value=s.gps_lng or 0.0,
                                precision=6).classes("w-36")

            def apply():
                s.azimuth_angle = float(azimuth.value or 0.0)
                s.elevation_angle = float(elevation.value or 0.0)
                s.installation_height = units.ft_to_m(float(height.value or 0.0))
                s.gps_lat = float(lat.value or 0.0)
                s.gps_lng = float(lng.value or 0.0)
                dialog.close()
                refresh_overlay()
                ui.notify(f"updated S{si + 1}")

            with ui.row():
                ui.button("Apply", on_click=apply)
                ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    def update_sensor_options():
        sensor_sel.set_options(
            {i: f"S{i + 1}" for i in range(len(v.project.sensors))},
            value=v.active_si)

    def change_active_sensor(e):
        if e.value is None or e.value == v.active_si:
            return
        cancel_rotate()  # retarget clears the controller's selection
        v.set_active_sensor(e.value)
        refresh_overlay()
        refresh_status()

    def add_sensor():
        if len(v.project.sensors) >= MAX_SENSORS:
            ui.notify(f"max {MAX_SENSORS} sensors (two-file limit)", type="warning")
            return
        s = Sensor()
        s.position_x, s.position_y = units.image_to_world(
            v.bg, (v.image_w / 2, v.image_h / 2))
        v.project.sensors.append(s)
        v.set_active_sensor(len(v.project.sensors) - 1)
        update_sensor_options()
        tool.value = "Sensor"
        refresh_overlay()
        refresh_status()
        ui.notify(f"S{len(v.project.sensors)} placed at image center — drag to position")

    def nudge_sensor(ux: float, uy: float):
        s = v.project.sensors[v.active_si]
        if s.position_x is None or s.position_y is None:
            return
        fpp = v.ft_per_px()
        step = NUDGE_FT / fpp if fpp else 2.0
        s.position_x += ux * step
        s.position_y += uy * step
        refresh_overlay()

    def delete_sensor():
        if len(v.project.sensors) <= 1:
            ui.notify("can't delete the only sensor", type="warning")
            return
        si = v.active_si
        s = v.project.sensors[si]
        real_zones = [z for z in s.event_zones if not is_placeholder(z)]
        real_ignores = [z for z in s.ignore_zones if not is_placeholder(z)]
        other_opts = {i: f"S{i + 1}" for i in range(len(v.project.sensors)) if i != si}

        def finish(reassign_to: int | None):
            if reassign_to is not None:
                tgt = v.project.sensors[reassign_to]
                for z in real_zones:
                    insert_zone(tgt.event_zones, z)
                for z in real_ignores:
                    insert_zone(tgt.ignore_zones, z)
            v.project.sensors.pop(si)
            v.set_active_sensor(min(si, len(v.project.sensors) - 1))
            update_sensor_options()
            dialog.close()
            refresh_overlay()
            refresh_status()
            msg = f"deleted S{si + 1}"
            if reassign_to is not None:
                msg += f", reassigned its zones to S{reassign_to + 1}"
            ui.notify(msg)

        with ui.dialog() as dialog, ui.card():
            ui.label(f"Delete S{si + 1}?").classes("text-lg")
            zone_count = len(real_zones) + len(real_ignores)
            if zone_count:
                ui.label(f"{zone_count} zone(s) are on this sensor — reassign "
                         "them to another sensor, or delete them with it.")
                reassign_sel = ui.select(
                    other_opts, value=next(iter(other_opts)),
                    label="Reassign to").classes("w-32")
                with ui.row():
                    ui.button("Reassign & Delete",
                             on_click=lambda: finish(reassign_sel.value))
                    ui.button("Delete Zones Too",
                             on_click=lambda: finish(None)).props("color=negative")
                    ui.button("Cancel", on_click=dialog.close)
            else:
                ui.label("No zones on this sensor.")
                with ui.row():
                    ui.button("Delete", on_click=lambda: finish(None)) \
                        .props("color=negative")
                    ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    # -- centerlines ---------------------------------------------------------

    def centerline_options() -> dict:
        return {i: v.centerline_label(i) for i in range(len(v.centerlines))}

    def update_centerline_options():
        centerline_sel.set_options(centerline_options(), value=v.active_cli)
        centerline_name_in.value = v.centerline_ctrl.name
        update_template_centerline_options()  # Item 19 dropdown uses the names

    def change_active_centerline(e):
        if e.value is None or e.value == v.active_cli:
            return
        v.set_active_centerline(e.value)
        centerline_name_in.value = v.centerline_ctrl.name
        refresh_overlay()
        refresh_status()

    def rename_centerline(e):
        """Item 20: session-only rename of the active centerline; refreshes
        every picker that shows centerline labels."""
        v.centerline_ctrl.name = (e.value or "").strip()
        update_centerline_options()

    def add_centerline():
        v.add_centerline()
        update_centerline_options()
        tool.value = "Centerline"
        refresh_overlay()
        refresh_status()
        ui.notify(f"{v.centerline_label(len(v.centerlines) - 1)} ready — "
                  "click the stop bar to start it")

    # -- template placement along centerlines (Item 19) ----------------------

    def update_template_centerline_options():
        """Options for the "along" dropdown: only centerlines with a usable
        datum (a specific pick bypasses the nearest/threshold logic, so an
        empty one would be a dead choice). Preserves the current pick when it
        still resolves; otherwise clears back to auto/nearest."""
        opts = {i: v.centerline_label(i) for i in range(len(v.centerlines))
                if v.centerlines[i].current() is not None}
        keep = v.template_centerline_idx if v.template_centerline_idx in opts else None
        v.template_centerline_idx = keep
        template_cl_sel.set_options(opts, value=keep)

    def toggle_template_follow(e):
        v.template_follow_centerline = bool(e.value)
        refresh_status()

    def change_template_centerline(e):
        v.template_centerline_idx = e.value  # int index, or None for auto/nearest
        refresh_status()

    # -- template placement ------------------------------------------------------

    def template_prompt_fields(template) -> list[str]:
        """Which of PLACEHOLDER_FIELDS this template needs a placement value
        for, regardless of what's already in v.template_context — the set
        the "placement values" dialog should show (usage-aware: e.g.
        lt_phase only if some row carries the "lt" role)."""
        return missing_placeholders(template, None)

    def edit_placement_values(auto: bool):
        """Prompt for the template's placeholder fields (direction/thru
        phase/lt phase/Base Output) into v.template_context. `auto` marks
        the just-picked-a-template call (silently skipped when the template
        is fully baked) vs. the manual "placement values" button (always
        opens, so values can be reviewed/changed between placements)."""
        fields = template_prompt_fields(v.template)
        if not fields and auto:
            return
        ctx = v.template_context
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Placement values — {v.template.name}").classes("text-lg")
            if not fields:
                ui.label("This template has no placeholders — every value "
                         "is baked in.").classes("text-sm text-gray-500")
            widgets = {}
            if "direction" in fields:
                widgets["direction"] = ui.select(
                    list(DIRECTIONS), label="Approach direction",
                    value=ctx.direction).classes("w-48")
            if "thru_phase" in fields:
                widgets["thru_phase"] = ui.number(
                    "Thru phase", min=1, precision=0, value=ctx.thru_phase)
            if "lt_phase" in fields:
                widgets["lt_phase"] = ui.number(
                    "LT phase", min=1, precision=0, value=ctx.lt_phase)
            if "base_output" in fields:
                widgets["base_output"] = ui.number(
                    "Base Output", min=0, precision=0, value=ctx.base_output)

            def as_int(name: str):
                w = widgets.get(name)
                return int(w.value) if w is not None and w.value not in (None, "") \
                    else None

            def apply():
                v.template_context = PlacementContext(
                    direction=widgets["direction"].value
                    if "direction" in widgets and widgets["direction"].value else None,
                    thru_phase=as_int("thru_phase"),
                    lt_phase=as_int("lt_phase"),
                    base_output=as_int("base_output"))
                dialog.close()
                refresh_overlay()
                refresh_status()

            with ui.row():
                ui.button("Apply", on_click=apply)
                ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    def change_template(e):
        if not e.value:
            v.template = None
        else:
            try:
                v.template = load_template(e.value)
            except (ValueError, OSError) as exc:
                ui.notify(f"failed to load template: {exc}", type="negative")
                v.template = None
        v.template_ref = None
        v.template_cursor = None
        v.template_context = PlacementContext()
        update_context_bar()
        refresh_overlay()
        refresh_status()
        if v.template is not None:
            edit_placement_values(auto=True)

    def place_template(pw):
        fpp = v.ft_per_px()
        if fpp is None:
            ui.notify("calibrate the background before placing a template",
                      type="warning")
            v.template_ref = None
            refresh_overlay()
            refresh_status()
            return
        cl_ctrl = v.template_target_centerline(pw)
        try:
            if cl_ctrl is not None:
                # curvilinear (Session 7.5): the click is the anchor reference;
                # direction and curvature come from the nearest centerline
                placed = expand_and_place_on_centerline(v.template, cl_ctrl.points,
                                                        pw, 1.0 / fpp,
                                                        v.template_context)
            else:
                upstream = (pw[0] - v.template_ref[0], pw[1] - v.template_ref[1])
                if math.hypot(*upstream) < 1e-6:
                    ui.notify("click a point away from the reference to aim",
                              type="warning")
                    return
                placed = expand_and_place(v.template, v.template_ref, upstream,
                                          1.0 / fpp, v.template_context)
        except ValueError as exc:
            # unresolved placeholder fields shouldn't reach here (the click
            # handler prompts first), but guard the model's contract anyway
            ui.notify(f"cannot place template: {exc}", type="warning")
            return
        zones = [EventZone(
            enable=1, zone_name=det.spec.name,
            zone_type=int(domain.ZoneType.PRESENCE if det.spec.kind == "stop_bar"
                          else domain.ZoneType.MOTION),
            phase_number=det.spec.phase, output_number=det.spec.output_number,
            points=[(float(x), float(y)) for x, y in det.points])
            for det in placed]
        # one undo op for the whole template, not one per detector
        v.ctrl.insert_many(zones)
        if cl_ctrl is not None:
            for zone, det in zip(zones, placed):
                if det.corners_so is not None:
                    cl_ctrl.attach(zone, det.corners_so)
        v.template_ref = None
        v.template_cursor = None
        refresh_overlay()
        refresh_status()
        along = (f" along {v.centerline_label(v.centerlines.index(cl_ctrl))}"
                 if cl_ctrl is not None else "")
        ui.notify(f"placed {len(placed)} detectors from {v.template.name}{along} "
                  f"(outputs {placed[0].spec.output_number}-"
                  f"{placed[-1].spec.output_number})")

    # -- save --------------------------------------------------------------------

    def do_save(path: Path):
        """path is always the _1_2 target for a multi-file (3-4 sensor)
        project — the single-file path otherwise (Item 9 §6)."""
        v.project.date = time.strftime("%Y_%m_%d_%H:%M:%S")
        save_centerlines(v.project, [cl.points for cl in v.centerlines])
        # after save_centerlines, so the endpoint-coincidence guard sees the
        # final chain vertices (model/centerline.py's save_lineals docstring)
        skipped = save_lineals(v.project, v.lineals)
        if skipped:
            ui.notify(f"{len(skipped)} lineal(s) not saved — they touch a "
                      "centerline or another lineal's endpoint", type="warning")
        if not is_multifile(v.project):
            save_iprj(v.project, path)
            v.source = path
            v.pair = None
            title_label.set_text(f"iprj Designer — {path.name}")
            ui.notify(f"saved {path}")
            return
        primary, secondary = split_project(v.project)
        p12, p34 = pair_paths(path)
        save_iprj(primary, p12)
        save_iprj(secondary, p34)
        v.pair = (p12, p34)
        v.source = p12
        title_label.set_text(f"iprj Designer — {p12.name} + {p34.name}")
        ui.notify(f"saved {p12.name} + {p34.name}")

    def save():
        if not is_multifile(v.project):
            if v.source.suffix.lower() == ".iprj":
                do_save(v.source)
            else:
                save_as()
        elif v.pair and is_valid_pair(*v.pair):
            do_save(v.pair[0])  # writes both files of the pair
        else:
            save_as()  # no legal pair name yet — force the user to choose one

    def save_as():
        multi = is_multifile(v.project)
        with ui.dialog() as dialog, ui.card():
            ui.label("Save project as:")
            default = str((v.pair[0] if v.pair else v.source).with_suffix(".iprj"))

            def update_preview(value: str):
                p = Path(value or default).expanduser()
                p12, p34 = pair_paths(p if p.suffix else p.with_suffix(".iprj"))
                preview.set_text(f"3-4 sensors → writes {p12.name} + {p34.name}")

            path_in = ui.input(
                "path", value=default,
                on_change=(lambda e: update_preview(e.value)) if multi else None,
            ).style("min-width: 420px")
            preview = ui.label().classes("text-xs text-gray-500")
            if multi:
                update_preview(default)

            def apply():
                p = Path(path_in.value).expanduser()
                if p.suffix.lower() != ".iprj":
                    p = p.with_suffix(".iprj")
                p.parent.mkdir(parents=True, exist_ok=True)
                do_save(p)
                dialog.close()

            with ui.row():
                ui.button("Save", on_click=apply)
                ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    # -- file management (New / Open / Upload background) ----------------------
    # No file is currently open in the browser, so switching projects can't
    # just mutate `v` in place — a fresh Viewer needs a fresh element tree
    # (image size, SVG viewBox, etc). `state["viewer"]` is what the root page
    # function (`main()`) hands to `build_ui` on each page load, so swapping
    # it and reloading the client picks up the new project without
    # restarting the server process.

    def swap_viewer(new_viewer: Viewer):
        state["viewer"] = new_viewer
        ui.navigate.reload()

    def new_project():
        with ui.dialog() as dialog, ui.card().style("min-width: 420px"):
            def start_blank():
                dialog.close()
                swap_viewer(Viewer(Project(background=Background()),
                                   Path("untitled.png")))

            async def start_from_upload(e):
                try:
                    img = Image.open(io.BytesIO(await e.file.read()))
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, format="PNG")
                except Exception as exc:  # noqa: BLE001 — surface any decode error
                    ui.notify(f"couldn't read image: {exc}", type="negative")
                    return
                bg = Background(image_base64=base64.b64encode(buf.getvalue())
                                .decode("ascii"))
                dialog.close()
                swap_viewer(Viewer(Project(background=bg), Path(e.file.name)))

            ui.label("New project").classes("text-lg")
            ui.button("Blank canvas", on_click=start_blank).classes("w-full")
            ui.separator()
            ui.label("…or start from an uploaded background image:") \
                .classes("text-xs text-gray-500")
            ui.upload(auto_upload=True, on_upload=start_from_upload) \
                .props('accept=".png,.jpg,.jpeg,.bmp"').classes("w-full")
            ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    def open_existing():
        with ui.dialog() as dialog, ui.card().style("min-width: 480px"):
            ui.label("Open project").classes("text-lg")
            found = iprj_files()
            if found:
                ui.select(found, label="known sites",
                          on_change=lambda e: path_in.set_value(e.value)) \
                    .classes("w-full").props("dense clearable")
            path_in = ui.input("path to .iprj", value=str(v.source)) \
                .classes("w-full")

            def apply():
                p = Path(path_in.value).expanduser()
                if not p.is_file():
                    ui.notify(f"not found: {p}", type="negative")
                    return
                try:
                    project = load_iprj(p)
                except Exception as exc:  # noqa: BLE001 — surface any parse error
                    ui.notify(f"failed to load {p}: {exc}", type="negative")
                    return
                dialog.close()
                swap_viewer(Viewer(project, p))

            with ui.row():
                ui.button("Open", on_click=apply)
                ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    def open_second_pair_file():
        """Item 9: merge a second sensor-pair (_3_4, usually) file's sensors
        into the currently open project, up to the 4-sensor two-file cap."""
        with ui.dialog() as dialog, ui.card().style("min-width: 480px"):
            ui.label("Open second sensor-pair file (overlay)").classes("text-lg")
            ui.label("Merges another file's sensors into this project. This "
                     "project's background, lineals, and text labels are "
                     "kept; the other file contributes only its sensors.") \
                .classes("text-xs text-gray-500")
            found = iprj_files()
            if found:
                ui.select(found, label="known sites",
                          on_change=lambda e: path_in.set_value(e.value)) \
                    .classes("w-full").props("dense clearable")
            path_in = ui.input("path to second .iprj").classes("w-full")

            def apply():
                p = Path(path_in.value).expanduser()
                if not p.is_file():
                    ui.notify(f"not found: {p}", type="negative")
                    return
                try:
                    other = load_iprj(p)
                except Exception as exc:  # noqa: BLE001 — surface any parse error
                    ui.notify(f"failed to load {p}: {exc}", type="negative")
                    return
                dialog.close()
                _resolve_pair_orientation(v.source, v.project, p, other)

            with ui.row():
                ui.button("Open", on_click=apply)
                ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    def _resolve_pair_orientation(cur_path, cur_proj, other_path, other_proj):
        """Which of the two open files is the _1_2 (primary)? Filenames
        decide when they follow the naming convention; otherwise ask."""
        cur_role, other_role = pair_role(cur_path), pair_role(other_path)
        if cur_role == "1_2" and other_role == "3_4":
            _confirm_and_merge(cur_path, cur_proj, other_path, other_proj)
            return
        if cur_role == "3_4" and other_role == "1_2":
            _confirm_and_merge(other_path, other_proj, cur_path, cur_proj)
            return

        with ui.dialog() as dialog, ui.card():
            ui.label("Which file is the 1-2 (primary) file?").classes("text-lg")
            ui.label("Neither filename follows the _1_2/_3_4 convention — "
                     "pick which one holds sensors 1-2.") \
                .classes("text-xs text-gray-500")

            def pick(cur_is_primary: bool):
                dialog.close()
                if cur_is_primary:
                    _confirm_and_merge(cur_path, cur_proj, other_path, other_proj)
                else:
                    _confirm_and_merge(other_path, other_proj, cur_path, cur_proj)

            with ui.column().classes("gap-1"):
                ui.button(f"{cur_path.name} = 1-2", on_click=lambda: pick(True))
                ui.button(f"{other_path.name} = 1-2", on_click=lambda: pick(False))
            ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    def _confirm_and_merge(primary_path, primary_proj, secondary_path, secondary_proj):
        match = check_background_match(primary_proj.background, secondary_proj.background)
        if not match.ok:
            ui.notify(match.reason, type="negative")
            return

        def do_merge(allow_soft: bool):
            try:
                merged = merge_pair(primary_proj, secondary_proj, allow_soft=allow_soft)
            except (BackgroundMismatch, ValueError) as exc:
                ui.notify(str(exc), type="negative")
                return
            swap_viewer(Viewer(merged, primary_path, pair=(primary_path, secondary_path)))

        if match.warn:
            with ui.dialog() as confirm, ui.card():
                ui.label("Background mismatch").classes("text-lg")
                ui.label(match.reason).classes("text-xs text-gray-500")

                def merge_anyway():
                    confirm.close()
                    do_merge(True)

                with ui.row():
                    ui.button("Merge anyway", on_click=merge_anyway)
                    ui.button("Cancel", on_click=confirm.close)
            confirm.open()
        else:
            do_merge(False)

    async def upload_background(e):
        """Replace the open project's background image in place (Item 1) —
        zones, sensors, and centerlines are untouched; only image_base64 and
        the derived image_w/image_h change. Reuses the decode/embed and
        served-PNG-file logic new_project's upload path and Viewer.__init__
        already have."""
        try:
            img = Image.open(io.BytesIO(await e.file.read()))
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="PNG")
        except Exception as exc:  # noqa: BLE001 — surface any decode error
            ui.notify(f"couldn't read image: {exc}", type="negative")
            return
        v.bg.image_base64 = base64.b64encode(buf.getvalue()).decode("ascii")
        png = units.decode_background_image(v.bg)
        with Image.open(io.BytesIO(png)) as im:  # header only, lazy
            v.image_w, v.image_h = im.size
        old_file = v.image_file
        fd, name = tempfile.mkstemp(prefix="iprj_bg_", suffix=".png")
        with os.fdopen(fd, "wb") as f:
            f.write(png)
        v.image_file = Path(name)
        atexit.register(lambda p=v.image_file: p.unlink(missing_ok=True))
        old_file.unlink(missing_ok=True)
        ui.notify(f"background image replaced ({v.image_w}x{v.image_h})")
        ui.navigate.reload()  # picks up the new image_file/image_w/image_h

    def upload_background_dialog():
        with ui.dialog() as dialog, ui.card():
            ui.label("Replace background image").classes("text-lg")
            ui.label("Zones, sensors, and centerlines are kept — only the "
                     "image changes. Recalibrate afterward if needed.") \
                .classes("text-xs text-gray-500")

            async def do_upload(e):
                dialog.close()
                await upload_background(e)

            ui.upload(auto_upload=True, on_upload=do_upload) \
                .props('accept=".png,.jpg,.jpeg,.bmp"').classes("w-full")
            ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    # -- template editor (standalone NiceGUI app, spawned on demand) -----------
    # gui/templates_ui.py owns its own event loop/port (a second NiceGUI
    # `ui.run` can't share this process's), so the Template context bar's
    # editor button starts it as a subprocess the first time it's needed and
    # reuses it after — tracked on `state`, not `v`, so it survives a
    # New/Open Viewer swap.

    async def open_template_editor():
        proc = state.get("template_editor_proc")
        port = state["template_editor_port"]
        if proc is None or proc.poll() is not None:
            script = Path(__file__).with_name("templates_ui.py")
            # if a template is currently picked in the Template tool, open
            # straight to it instead of a blank form
            current = template_sel.value if v.mode == "Template" else None
            cmd = [sys.executable, str(script)]
            if current:
                cmd.append(current)
            cmd += ["--port", str(port)]
            proc = subprocess.Popen(cmd)
            state["template_editor_proc"] = proc
            atexit.register(proc.terminate)
            ui.notify("starting template editor…")
            for _ in range(50):  # ~5s of polling for the port to come up
                await asyncio.sleep(0.1)
                try:
                    with socket.create_connection(("localhost", port), timeout=0.2):
                        break
                except OSError:
                    continue
            else:
                ui.notify("template editor is slow to start — try again "
                          "in a moment", type="warning")
                return
        ui.navigate.to(f"http://localhost:{port}/", new_tab=True)

    # -- mouse handling (offsetX/Y == image px: element kept at natural size)

    def rotate_status() -> str:
        if v.rotate_pivot is None:
            return "mode: rotate | click to place the pivot  [Esc cancels]"
        return (f"mode: rotate | angle {v.rotate_angle:+.1f}° | "
                "move to aim, click to commit  [Esc cancels]")

    def refresh_status():
        if v.ruler_active:
            # overlay: takes over the status line (and clicks) regardless of
            # whatever tool is underneath — same priority as rotate_armed.
            status_label.set_text(v.ruler_status())
        elif v.mode == "Edit" and v.rotate_armed:
            status_label.set_text(rotate_status())
        elif v.mode in ("Draw", "Edit"):
            status_label.set_text(v.ctrl.status())
        elif v.mode == "Sensor":
            status_label.set_text(
                f"mode: sensor | S{v.active_si + 1} active | "
                "drag a sensor to move it, click one for properties")
        elif v.mode == "Template":
            status_label.set_text(v.template_status())
        elif v.mode == "Centerline":
            status_label.set_text(f"C{v.active_cli + 1}/{len(v.centerlines)} | "
                                  f"{v.centerline_ctrl.status()}")
        elif v.mode == "Background":
            status_label.set_text(
                "mode: calibrate 2-pt | click two reference points, "
                "then enter the known distance")
        else:
            status_label.set_text(f"mode: {v.mode.lower()}")
        snap_switch.set_value(v.ctrl.snap_enabled)  # no-op when already equal
        select_count_label.set_text(
            f"{len(v.ctrl.selection)} selected" if v.mode == "Edit" else "")
        # bulk edit is out of scope for v1 (PHASE3_UI_PLAN §8.2) — the floor
        # is disabling single-zone Properties once more than one is selected
        properties_btn.set_enabled(len(v.ctrl.selection) <= 1)
        zones = v.active_zones()
        move_station_btn.set_enabled(
            v.mode == "Edit" and v.draw_kind_name == "Event Zone"
            and len(v.ctrl.selection) == 1 and 0 <= v.ctrl.selected < len(zones)
            and attached_centerline_for(zones[v.ctrl.selected]) is not None)
        refresh_zone_table()

    # -- zone table panel (synced with canvas selection) -----------------------

    def zone_rows() -> list[dict]:
        rows = []
        for si, s in enumerate(v.project.sensors):
            for zi, z in enumerate(s.event_zones):
                if is_placeholder(z):
                    continue
                rows.append({"key": f"{si}:{zi}", "sensor": f"S{si + 1}",
                             "on": "✓" if z.enable else "",
                             "name": z.zone_name or "",
                             "phase": z.phase_number or 0,
                             "output": z.output_number or 0,
                             "type": z.zone_type or 0})
        return rows

    def refresh_zone_table():
        rows = zone_rows()
        zone_table.rows = rows
        sel_keys = set()
        if v.mode == "Edit" and v.draw_kind_name == "Event Zone":
            n = len(v.active_zones())
            sel_keys = {f"{v.active_si}:{zi}" for zi in v.ctrl.selection if zi < n}
        zone_table.selected = [r for r in rows if r["key"] in sel_keys]
        zone_table.update()

    def select_zone_key(key: str):
        """Plain row click: select just this one zone (mirrors a plain
        canvas click), overriding whatever the checkbox column had set."""
        si, zi = (int(x) for x in key.split(":"))
        if v.draw_kind_name != "Event Zone":
            draw_kind_toggle.set_value("Event Zone")  # on_change retargets to Event Zone
        if si != v.active_si:
            sensor_sel.set_value(si)  # on_change retargets the controller
        if v.mode != "Edit":
            tool.value = "Edit"     # on_change syncs the controller mode
        v.ctrl.selected = zi
        refresh_overlay()
        refresh_status()

    def on_table_select(e):
        """Checkbox-column multi-select (PHASE3_UI_PLAN §6.5): syncs the
        table's selected rows back into `ctrl.selection`. Selection is
        scoped to one sensor's list at a time (§6.1), so a selection
        spanning sensors keeps only the last row's sensor — mirroring how a
        plain click elsewhere already collapses to a single list."""
        keys = [r["key"] for r in e.selection]
        if not keys:
            if v.mode == "Edit" and v.ctrl.selection:
                v.ctrl.select_many([])
                refresh_overlay()
                refresh_status()
            return
        si = int(keys[-1].split(":")[0])
        zis = [int(k.split(":")[1]) for k in keys if int(k.split(":")[0]) == si]
        if v.draw_kind_name != "Event Zone":
            draw_kind_toggle.set_value("Event Zone")
        if si != v.active_si:
            sensor_sel.set_value(si)
        if v.mode != "Edit":
            tool.value = "Edit"
        v.ctrl.select_many(zis)
        refresh_overlay()
        refresh_status()

    def on_table_row_click(e):
        select_zone_key(e.args[1]["key"])

    def on_table_row_dblclick(e):
        si, zi = (int(x) for x in e.args[1]["key"].split(":"))
        zone_properties(si, zi)

    # -- toolbar actions & layer toggles ---------------------------------------

    def toggle_snap(e):
        if bool(e.value) == v.ctrl.snap_enabled:
            return  # echo of refresh_status syncing the switch
        v.ctrl.snap_enabled = bool(e.value)
        if not v.ctrl.snap_enabled:
            v.ctrl.snap_indicator = None
        refresh_overlay()
        refresh_status()

    def do_undo():
        v.ctrl.undo()  # ops carry their zone lists, so any mode is fine
        v.reproject_attachments()
        refresh_overlay()
        refresh_status()

    def do_delete():
        if v.mode != "Edit":
            ui.notify("switch to the Edit tool to delete", type="warning")
            return
        v.ctrl.delete_selected()
        refresh_overlay()
        refresh_status()

    def start_rotate():
        if v.mode != "Edit" or not v.ctrl.selection:
            ui.notify("select one or more zones first", type="warning")
            return
        v.rotate_armed = True
        v.rotate_pivot = None
        v.rotate_ray = None
        v.rotate_angle = 0.0
        refresh_overlay()
        refresh_status()

    def cancel_rotate():
        if not v.rotate_armed:
            return
        v.rotate_armed = False
        v.rotate_pivot = None
        v.rotate_ray = None
        v.rotate_angle = 0.0

    def commit_rotate(pivot, angle):
        zones = v.ctrl.rotate_selection(angle, pivot)
        v.rotate_armed = False
        v.rotate_pivot = None
        v.rotate_ray = None
        v.rotate_angle = 0.0
        if not zones:
            return
        # an attached zone is oriented by the centerline (restation derives
        # it from station/offset + local tangent); a hand-rotate is a
        # deliberate override, so it detaches (PHASE3_UI_PLAN §6.4) rather
        # than getting reprojected back onto the datum.
        detached = 0
        for cl in v.centerlines:
            for zone in zones:
                if cl.attached.pop(id(zone), None) is not None:
                    detached += 1
        msg = f"rotated {len(zones)} zone" + ("" if len(zones) == 1 else "s")
        if detached:
            msg += f" — detached {detached} from its centerline"
        ui.notify(msg)

    def notify_ctrl_warning():
        """Surface a vendor-cap ValueError (10 ignore zones / 100 lineals /
        64 loops) the controller recorded on the last insert attempt."""
        if v.ctrl.warning:
            ui.notify(v.ctrl.warning, type="warning")
            v.ctrl.warning = ""

    def set_layer(attr: str, on: bool):
        setattr(v, attr, bool(on))
        refresh_overlay()

    def set_bg_visible(on: bool):
        ii.classes(remove="bg-off") if on else ii.classes(add="bg-off")

    def toggle_zone_panel():
        zone_panel.set_visibility(not zone_panel.visible)

    def clear_ruler():
        v.ruler_start = None
        v.ruler_end = None
        v.ruler_pending = False
        refresh_overlay()
        refresh_status()

    def on_down(e):
        p = (e.args["offsetX"], e.args["offsetY"])
        button = e.args.get("button", 0)
        if button == 1 or (button == 0 and v.space_pan):
            v.drag_anchor = p
        elif button == 0 and v.ruler_active:
            # overlay tool (Item 1): captures the click regardless of the
            # active main tool, same as pan above.
            pw = units.image_to_world(v.bg, p)
            if v.ruler_start is None or not v.ruler_pending:
                v.ruler_start = pw
                v.ruler_end = pw
                v.ruler_pending = True
            else:
                v.ruler_end = pw
                v.ruler_pending = False
            refresh_overlay()
            refresh_status()
        elif button == 0 and v.mode == "Background":
            v.cal_points.append(units.image_to_world(v.bg, p))
            refresh_overlay()
            if len(v.cal_points) == 2:
                finish_two_point()
        elif button == 0 and v.mode == "Sensor":
            pw = units.image_to_world(v.bg, p)
            si = v.sensor_at(pw)
            if si != -1:
                s = v.project.sensors[si]
                v.sensor_drag = {"si": si, "anchor": pw, "moved": False,
                                 "orig": (s.position_x, s.position_y)}
                if si != v.active_si:
                    sensor_sel.set_value(si)  # on_change retargets
        elif button == 0 and v.mode == "Draw":
            v.ctrl.mouse_down(units.image_to_world(v.bg, p),
                              ctrl=bool(e.args.get("ctrlKey")))
            notify_ctrl_warning()
            refresh_overlay()
            refresh_status()
        elif button == 0 and v.mode == "Edit" and v.rotate_armed:
            pw = units.image_to_world(v.bg, p)
            if v.rotate_pivot is None:
                v.rotate_pivot = pw  # click 1: place the pivot
            else:
                commit_rotate(v.rotate_pivot, v.rotate_angle)  # click 2
            refresh_overlay()
            refresh_status()
        elif button == 0 and v.mode == "Edit":
            pw = units.image_to_world(v.bg, p)
            shift = bool(e.args.get("shiftKey"))
            sel_before, anchor_before = list(v.ctrl.selection), v.ctrl.anchor
            v.ctrl.mouse_down(pw, ctrl=bool(e.args.get("ctrlKey")), shift=shift)
            # nothing under the cursor (no drag started, selection/anchor
            # unchanged) -> this is the start of a marquee, not a click
            # (PHASE3_UI_PLAN §5/§6.2)
            if not v.ctrl.dragging and v.ctrl.selection == sel_before \
                    and v.ctrl.anchor == anchor_before:
                v.marquee_anchor = pw
                v.marquee_cursor = pw
                v.marquee_additive = shift
            notify_ctrl_warning()
            refresh_overlay()
            refresh_status()
        elif button == 0 and v.mode == "Template":
            if v.template is None:
                ui.notify("pick a template first", type="warning")
                return
            if missing_placeholders(v.template, v.template_context):
                ui.notify("fill in the placement values first", type="warning")
                edit_placement_values(auto=False)
                return
            pw = units.image_to_world(v.bg, p)
            if v.template_target_centerline(pw) is not None:
                place_template(pw)  # curvilinear: one click, no aim needed
            elif v.template_ref is None:
                v.template_ref = pw
                refresh_overlay()
                refresh_status()
            else:
                place_template(pw)
        elif button == 0 and v.mode == "Centerline":
            v.centerline_ctrl.mouse_down(units.image_to_world(v.bg, p))
            refresh_overlay()
            refresh_status()

    def on_move(e):
        p = (e.args["offsetX"], e.args["offsetY"])
        pos_label.set_text(v.describe(p))
        pw = units.image_to_world(v.bg, p)
        if v.drag_anchor is not None and e.args.get("buttons", 0):
            v.viewport.drag_to(v.drag_anchor, p)
            apply_transform()
        elif v.sensor_drag is not None and e.args.get("buttons", 0) & 1:
            d = v.sensor_drag
            s = v.project.sensors[d["si"]]
            s.position_x = d["orig"][0] + pw[0] - d["anchor"][0]
            s.position_y = d["orig"][1] + pw[1] - d["anchor"][1]
            if math.dist(pw, d["anchor"]) > v.ctrl.handle_radius / 3:
                d["moved"] = True
            refresh_overlay()
        elif v.ruler_active:
            if v.ruler_pending:
                v.ruler_end = pw
                refresh_overlay()
        elif v.mode == "Draw":
            dragging = bool(e.args.get("buttons", 0) & 1)
            v.ctrl.mouse_move(pw, dragging)
            # only redraw while something tracks the mouse
            if v.ctrl.pending or dragging or v.ctrl.snap_enabled:
                refresh_overlay()
        elif v.mode == "Edit" and v.rotate_armed:
            if v.rotate_pivot is not None:
                if v.rotate_ray is None:
                    v.rotate_ray = pw  # freeze the angle-measure reference ray
                else:
                    v.rotate_angle = geometry.rotation_angle_deg(
                        v.rotate_pivot, v.rotate_ray, pw)
            refresh_overlay()
        elif v.mode == "Edit":
            dragging = bool(e.args.get("buttons", 0) & 1)
            v.ctrl.mouse_move(pw, dragging)
            if v.marquee_anchor is not None and dragging:
                v.marquee_cursor = pw
            if dragging or v.ctrl.snap_enabled or v.marquee_anchor is not None:
                refresh_overlay()
        elif v.mode == "Template" and v.template is not None:
            # cursor tracked from the first hover: with a centerline the
            # preview follows the mouse before any click
            v.template_cursor = pw
            refresh_overlay()
        elif v.mode == "Centerline":
            dragging = bool(e.args.get("buttons", 0) & 1)
            v.centerline_ctrl.mouse_move(pw, dragging)
            if dragging:
                refresh_overlay()

    def on_up(e):
        v.drag_anchor = None
        p = (e.args["offsetX"], e.args["offsetY"])
        pw = units.image_to_world(v.bg, p)
        if v.sensor_drag is not None:
            d, v.sensor_drag = v.sensor_drag, None
            if not d["moved"]:
                sensor_properties(d["si"])
        elif v.ruler_active:
            # a real click-drag-release finishes the measurement in one
            # gesture; a plain click leaves it pending for a second click
            if v.ruler_pending and math.dist(pw, v.ruler_start) > v.ctrl.handle_radius / 3:
                v.ruler_end = pw
                v.ruler_pending = False
                refresh_overlay()
                refresh_status()
        elif v.mode == "Draw":
            v.ctrl.mouse_up(pw)
            v.reproject_attachments()  # a drag may have moved an attached zone
            refresh_overlay()
            refresh_status()
        elif v.mode == "Edit":
            v.ctrl.mouse_up(pw)
            if v.marquee_anchor is not None:
                v.ctrl.marquee_select(v.marquee_anchor, pw,
                                      additive=v.marquee_additive)
                v.marquee_anchor = None
                v.marquee_cursor = None
            v.reproject_attachments()  # a drag may have moved an attached zone
            refresh_overlay()
            refresh_status()
        elif v.mode == "Centerline":
            v.centerline_ctrl.mouse_up(pw)
            refresh_overlay()
            refresh_status()

    def on_dblclick(e):
        # the two mousedowns already selected the zone under the cursor
        if v.mode == "Edit":
            zone_properties()
        elif v.mode == "Draw" and v.ctrl.finish_polygon():
            notify_ctrl_warning()
            refresh_overlay()
            refresh_status()

    # top-level tool + Draw sub-type accelerators (PHASE3_UI_PLAN §2.1):
    # handled here with an early return, before delegating to the
    # controller, so gui/drawing.py never sees these as mode keys.
    # No accelerator for Background: every unused letter that reads as a
    # mnemonic ("b") is already `n`/`b` cycle-selection in gui/drawing.py's
    # edit-mode keys — click the tool toggle instead. `v` is no longer a
    # tool alias (ROADMAP Item 5) — it falls through to ctrl.key() below as
    # the Edit-tool insert-vertex action.
    TOOL_KEYS = {"d": "Draw", "e": "Edit",
                "t": "Template", "c": "Centerline", "s": "Sensor"}
    DRAW_SUBTYPE_KEYS = {"z": "Event Zone", "l": "Lineal", "i": "Ignore Zone"}

    async def on_key(e):
        name = e.key.name
        if e.key.space:
            v.space_pan = e.action.keydown
            return
        if not e.action.keydown:
            return
        if e.action.repeat and name != "Backspace" \
                and not name.startswith("Arrow"):
            return
        if e.modifiers.ctrl and name == "s":
            save()
            return
        if name == "f":
            await fit_view()
            return
        if name == "r":
            toggle_ruler()
            return
        if name in TOOL_KEYS:
            tool.value = TOOL_KEYS[name]  # on_change syncs the controller
            return
        if name in DRAW_SUBTYPE_KEYS and not e.modifiers.ctrl:
            # `z` is also Ctrl-Z undo; the modifier above tells them apart.
            if tool.value != "Draw":
                tool.value = "Draw"
            draw_kind_toggle.set_value(DRAW_SUBTYPE_KEYS[name])
            return
        if name in ("p", "Enter") and v.mode == "Edit" \
                and v.ctrl.dim_stage == DIM_OFF:
            zone_properties()
            return
        if name == "Escape" and v.rotate_armed:
            cancel_rotate()
            refresh_overlay()
            refresh_status()
            return
        if name == "Escape" and v.mode == "Template" and v.template_ref is not None:
            v.template_ref = None
            v.template_cursor = None
            refresh_overlay()
            refresh_status()
            return
        if name == "Escape" and v.ruler_active and v.ruler_pending:
            v.ruler_start = None
            v.ruler_end = None
            v.ruler_pending = False
            refresh_overlay()
            refresh_status()
            return
        if v.mode in ("Draw", "Edit") and v.ctrl.key(name, e.modifiers.ctrl):
            notify_ctrl_warning()
            v.reproject_attachments()  # nudge/undo may have moved attached zones
            refresh_overlay()
            refresh_status()
        elif v.mode == "Centerline" and v.centerline_ctrl.key(name, e.modifiers.ctrl):
            refresh_overlay()
            refresh_status()
        elif v.mode == "Sensor" and name in ARROWS:
            nudge_sensor(*ARROWS[name])
        elif v.mode == "Sensor" and name in ("Delete", "x"):
            delete_sensor()

    def change_tool(e):
        v.mode = e.value
        if e.value == "Draw":
            v.ctrl.set_mode("draw")
        elif e.value == "Edit":
            v.ctrl.set_mode("edit")
        else:
            v.ctrl.set_mode("draw")  # clears any pending loop/dimension entry
        if e.value != "Template":
            v.template_ref = None
            v.template_cursor = None
        if e.value != "Centerline":
            v.centerline_ctrl.end_drag()
        if e.value != "Edit":
            cancel_rotate()
        v.marquee_anchor = None
        v.marquee_cursor = None
        update_context_bar()
        refresh_overlay()
        refresh_status()

    def change_draw_kind(e):
        cancel_rotate()  # retarget clears the controller's selection
        v.set_draw_kind(e.value)
        refresh_overlay()
        refresh_status()

    def set_ruler_active(on: bool):
        v.ruler_active = on
        if not on and v.ruler_pending:
            v.ruler_start = None
            v.ruler_end = None
            v.ruler_pending = False
        ruler_btn.classes(add="text-cyan-400" if on else "",
                          remove="" if on else "text-cyan-400")
        refresh_overlay()
        refresh_status()

    def toggle_ruler():
        set_ruler_active(not v.ruler_active)

    def update_context_bar():
        """Row-2 context controls per tool (PHASE3_UI_PLAN §3): built once,
        shown/hidden by visibility rather than rebuilt on every switch, so
        widget state (selector values) survives a tool change."""
        sensor_sel.set_visibility(v.mode in ("Draw", "Edit", "Sensor"))
        add_sensor_btn.set_visibility(v.mode == "Sensor")
        delete_sensor_btn.set_visibility(v.mode == "Sensor")
        draw_kind_toggle.set_visibility(v.mode == "Draw")
        select_count_label.set_visibility(v.mode == "Edit")
        properties_btn.set_visibility(v.mode == "Edit")
        rotate_btn.set_visibility(v.mode == "Edit")
        move_station_btn.set_visibility(v.mode == "Edit")
        delete_btn.set_visibility(v.mode == "Edit")
        calibrate_size_btn.set_visibility(v.mode == "Background")
        upload_bg_btn.set_visibility(v.mode == "Background")
        template_sel.set_visibility(v.mode == "Template")
        template_values_btn.set_visibility(
            v.mode == "Template" and v.template is not None)
        template_editor_btn.set_visibility(v.mode == "Template")
        template_follow_switch.set_visibility(v.mode == "Template")
        template_cl_sel.set_visibility(v.mode == "Template")
        if v.mode == "Template":  # refresh which centerlines are pickable
            update_template_centerline_options()
        centerline_sel.set_visibility(v.mode == "Centerline")
        add_centerline_btn.set_visibility(v.mode == "Centerline")
        centerline_name_in.set_visibility(v.mode == "Centerline")

    def on_wheel(e):
        # The visual zoom already happened client-side (_WHEEL_ZOOM_JS); this
        # throttled sync just adopts the browser's absolute viewport so the
        # overlay stroke-widths and status label catch up. apply_transform
        # re-asserts the same transform on ii.style, keeping the server's
        # known style consistent with the DOM for the next Vue re-render.
        a = e.args
        try:
            v.viewport.scale = min(MAX_SCALE, max(MIN_SCALE, float(a["scale"])))
            v.viewport.tx = float(a["tx"])
            v.viewport.ty = float(a["ty"])
        except (KeyError, TypeError, ValueError):
            return
        apply_transform()
        scale_label.set_text(status_scale())

    async def fit_view():
        size = await ui.run_javascript(
            "[document.getElementById('viewport').clientWidth,"
            " document.getElementById('viewport').clientHeight]")
        v.viewport.fit((v.image_w, v.image_h), tuple(size))
        apply_transform()
        scale_label.set_text(status_scale())

    # -- layout ---------------------------------------------------------------
    # Two-tier toolbar (PHASE3_UI_PLAN §3): row 1 is persistent chrome that
    # never depends on the active tool, so it never scrolls; row 2 is a
    # single context bar whose controls are built once and individually
    # shown/hidden per tool by update_context_bar() (visibility toggling,
    # not rebuilding, so selector state survives a tool switch).

    with ui.row().classes("w-full items-center gap-2 px-2 no-wrap overflow-x-auto"):
        _title = (f"{v.pair[0].name} + {v.pair[1].name}" if v.pair
                  else v.source.name)
        title_label = ui.label(f"iprj Designer — {_title}") \
            .classes("text-lg text-white whitespace-nowrap")
        with ui.button(icon="folder").props("flat dense"):
            ui.tooltip("file")
            with ui.menu():
                ui.menu_item("New…", on_click=new_project)
                ui.menu_item("Open…", on_click=open_existing)
                ui.menu_item("Open second sensor-pair file (overlay)…",
                             on_click=open_second_pair_file)
                ui.separator()
                ui.menu_item("Save", on_click=save)
                ui.menu_item("Save As…", on_click=save_as)
        ui.separator().props("vertical")
        tool = ui.toggle(["Edit", "Draw", "Template", "Centerline", "Sensor",
                          "Background"], value="Edit",
                         on_change=change_tool).props("dense")
        with tool:
            ui.tooltip("accelerators: d draw · e edit · t template · "
                       "c centerline · s sensor · space+drag / "
                       "middle-drag pans · Esc cancel")
        ui.separator().props("vertical")
        ruler_btn = ui.button(icon="straighten", on_click=toggle_ruler) \
            .props("flat dense")
        with ruler_btn:
            ui.tooltip("ruler (r) — measures distance in any tool, "
                       "independent of the active tool")
        with ui.button(icon="clear", on_click=clear_ruler) \
                .props("flat dense"):
            ui.tooltip("clear ruler")
        ui.space()
        snap_switch = ui.switch("snap", on_change=toggle_snap).props("dense")
        with snap_switch:
            ui.tooltip("vertex/midpoint snapping (g)")
        with ui.button(icon="undo", on_click=do_undo).props("flat dense"):
            ui.tooltip("undo (u / Ctrl-Z)")
        with ui.button(icon="layers").props("flat dense"):
            ui.tooltip("layer visibility")
            with ui.menu():
                with ui.column().classes("px-3 py-2 gap-0"):
                    ui.switch("Background", value=True, on_change=lambda e:
                              set_bg_visible(e.value)).props("dense")
                    ui.switch("Zones", value=True, on_change=lambda e:
                              set_layer("show_zones", e.value)).props("dense")
                    ui.switch("Labels", value=True, on_change=lambda e:
                              set_layer("show_labels", e.value)).props("dense")
                    ui.switch("Sensors", value=True, on_change=lambda e:
                              set_layer("show_sensors", e.value)).props("dense")
        with ui.button(icon="fit_screen", on_click=fit_view).props("flat dense"):
            ui.tooltip("fit image to window (f)")
        with ui.button(icon="save", on_click=save).props("flat dense"):
            ui.tooltip("save (Ctrl-S)")
        with ui.button(icon="view_sidebar", on_click=toggle_zone_panel) \
                .props("flat dense"):
            ui.tooltip("show/hide the zone table")

    with ui.row().classes("w-full items-center gap-2 px-2 no-wrap overflow-x-auto"):
        sensor_sel = ui.select(
            {i: f"S{i + 1}" for i in range(len(v.project.sensors))},
            value=v.active_si, label="sensor",
            on_change=change_active_sensor).classes("w-24").props("dense")
        add_sensor_btn = ui.button(icon="add_circle", on_click=add_sensor) \
            .props("flat dense")
        with add_sensor_btn:
            ui.tooltip("add a sensor at image center")
        delete_sensor_btn = ui.button(icon="delete", on_click=delete_sensor) \
            .props("flat dense")
        with delete_sensor_btn:
            ui.tooltip("delete active sensor (x / Del) — prompts to reassign "
                       "or delete its zones")

        draw_kind_toggle = ui.toggle(["Event Zone", "Ignore Zone", "Lineal"],
                                     value="Event Zone",
                                     on_change=change_draw_kind).props("dense")
        with draw_kind_toggle:
            ui.tooltip("draw sub-type: z Event Zone · l Lineal · i Ignore Zone — "
                       "also picks what Edit operates on")

        select_count_label = ui.label("").classes("text-white font-mono")
        properties_btn = ui.button(icon="tune", on_click=lambda: zone_properties()) \
            .props("flat dense")
        with properties_btn:
            ui.tooltip("zone properties (p / Enter / double-click) — "
                       "single selection only")
        rotate_btn = ui.button(icon="rotate_right", on_click=start_rotate) \
            .props("flat dense")
        with rotate_btn:
            ui.tooltip("rotate selection: click to place the pivot, "
                       "move to aim, click again to commit (Esc cancels)")
        move_station_btn = ui.button(icon="timeline",
                                     on_click=move_along_centerline) \
            .props("flat dense")
        with move_station_btn:
            ui.tooltip("move along centerline — set an absolute station or "
                       "nudge by a delta (centerline-attached zones only)")
        delete_btn = ui.button(icon="delete", on_click=do_delete).props("flat dense")
        with delete_btn:
            ui.tooltip("delete selected (x / Del)")

        calibrate_size_btn = ui.button(icon="aspect_ratio", on_click=calibrate_by_size) \
            .props("flat dense")
        with calibrate_size_btn:
            ui.tooltip("calibrate by known image width/height")
        upload_bg_btn = ui.button(icon="image",
                                  on_click=upload_background_dialog) \
            .props("flat dense")
        with upload_bg_btn:
            ui.tooltip("upload a new background image (keeps zones/sensors/"
                       "centerlines)")

        template_sel = ui.select(template_files(), label="template",
                                 on_change=change_template) \
            .classes("w-48").props("dense clearable")
        with template_sel:
            ui.tooltip("approach template to place (click the anchor point "
                       "— stop bar at the LT/thru lane line — follows the "
                       "nearest centerline, or a second aim click without "
                       "one)")
        template_values_btn = ui.button(
            icon="edit_note", on_click=lambda: edit_placement_values(auto=False)) \
            .props("flat dense")
        with template_values_btn:
            ui.tooltip("placement values — direction, thru/LT phase, "
                       "Base Output")
        template_editor_btn = ui.button(
            icon="edit_square", on_click=open_template_editor).props("flat dense")
        with template_editor_btn:
            ui.tooltip("open the template editor (new tab)")
        template_follow_switch = ui.switch(
            "along CL", value=v.template_follow_centerline,
            on_change=toggle_template_follow).props("dense")
        with template_follow_switch:
            ui.tooltip(f"place along the nearest centerline within "
                       f"{CENTERLINE_SNAP_FT:.0f} ft of the anchor click; "
                       "off = always aim upstream with a second click")
        template_cl_sel = ui.select(
            {}, label="pick CL", on_change=change_template_centerline) \
            .classes("w-28").props("dense clearable")
        with template_cl_sel:
            ui.tooltip("place along one specific centerline instead of the "
                       "nearest (blank = nearest); ignores the distance "
                       "threshold")

        centerline_sel = ui.select(
            centerline_options(),
            value=v.active_cli, label="centerline",
            on_change=change_active_centerline).classes("w-28").props("dense")
        add_centerline_btn = ui.button(icon="add_road", on_click=add_centerline) \
            .props("flat dense")
        with add_centerline_btn:
            ui.tooltip("add a new centerline (another approach)")
        centerline_name_in = ui.input(
            "name", value=v.centerline_ctrl.name,
            on_change=rename_centerline).classes("w-32").props("dense clearable")
        with centerline_name_in:
            ui.tooltip("session-only name for this centerline (e.g. N_CL for "
                       "the north approach); shown in the centerline pickers")

    update_context_bar()

    ui.keyboard(on_key=on_key)  # ignores keys typed into dialogs/inputs

    with ui.row().classes("w-full no-wrap gap-0"):
        with ui.element("div").props("id=viewport").classes("grow overflow-hidden") \
                .style("height: calc(100vh - 120px); position: relative; "
                       "background: #111; cursor: crosshair;"):
            ii = ui.interactive_image(v.image_file, content=v.svg(), cross="#00e5ff")
            ii.style(f"width: {v.image_w}px; height: {v.image_h}px; "
                     f"max-width: none; position: absolute;")
            ii.on("mousedown", on_down,
                  ["offsetX", "offsetY", "button", "buttons", "ctrlKey", "shiftKey"])
            ii.on("mousemove", on_move, ["offsetX", "offsetY", "buttons"],
                  throttle=0.03)
            ii.on("mouseup", on_up, ["offsetX", "offsetY"])
            ii.on("dblclick", on_dblclick, ["offsetX", "offsetY"])
            # js_handler zooms locally every tick; the emit (throttled, so it
            # can't flood the socket) syncs absolute viewport state to on_wheel.
            ii.on("wheel.prevent", on_wheel, args=None,
                  js_handler=_WHEEL_ZOOM_JS, throttle=0.05)
        with ui.column().classes("w-96 px-1 overflow-y-auto") \
                .style("height: calc(100vh - 120px);") as zone_panel:
            zone_table = ui.table(
                columns=[
                    {"name": "sensor", "label": "S", "field": "sensor",
                     "align": "left", "sortable": True},
                    {"name": "on", "label": "On", "field": "on", "align": "center"},
                    {"name": "name", "label": "Name", "field": "name",
                     "align": "left", "sortable": True},
                    {"name": "phase", "label": "Ph", "field": "phase",
                     "align": "right", "sortable": True},
                    {"name": "output", "label": "Out", "field": "output",
                     "align": "right", "sortable": True},
                    {"name": "type", "label": "Type", "field": "type",
                     "align": "right", "sortable": True},
                ],
                rows=zone_rows(), row_key="key", selection="multiple",
                on_select=on_table_select, pagination=0) \
                .classes("w-full").props("dense flat hide-bottom")
            zone_table.on("rowClick", on_table_row_click)
            zone_table.on("rowDblclick", on_table_row_dblclick)
            ui.label("click: select one · checkbox: multi-select · "
                     "double-click: properties") \
                .classes("text-xs text-gray-500 px-1")

    with ui.row().classes("w-full justify-between px-2"):
        status_label = ui.label("mode: edit").classes("text-white font-mono")
        pos_label = ui.label("—").classes("text-white font-mono")
        scale_label = ui.label(status_scale()).classes("text-white font-mono")

    refresh_status()
    ui.timer(0.3, fit_view, once=True)
    if v.derived_attachments:
        ui.timer(0.8, lambda: ui.notify(
            f"{v.derived_attachments} zone"
            f"{'s' if v.derived_attachments != 1 else ''} re-attached to "
            "centerlines (will follow centerline edits)"), once=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", nargs="?", type=Path,
                    default=REPO / "sites/Banks/banks.iprj")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    # Load once, then hand ui.run a *root page function*. Without it,
    # NiceGUI 3's script mode re-executes this whole script — argparse,
    # load_iprj, Viewer, everything — on every page request via
    # runpy.run_path, retaining a full project copy per client (~11 MB per
    # GET on Banks; the pre-3.x behavior this code was written against
    # built the page once). The Viewer stays shared across clients
    # (single-user by design until Session 8.1); only the element tree is
    # rebuilt per client. `state["viewer"]` is looked up fresh on every page
    # load rather than captured once, so New/Open (Phase 1) can swap in a
    # different Viewer and reload the client to pick it up — no server
    # restart required.
    state = {
        "viewer": Viewer(open_project(args.path), args.path),
        # The Template context bar's editor button spawns gui/templates_ui.py
        # as a subprocess on its own port (a second NiceGUI app can't share
        # this process's event loop) the first time it's opened, and reuses
        # it after.
        "template_editor_proc": None,
        "template_editor_port": args.port + 1000,
    }
    ui.run(lambda: build_ui(state["viewer"], state), port=args.port,
           title="iprj Designer", reload=False, show=False, dark=True)


if __name__ in {"__main__", "__mp_main__"}:
    main()
