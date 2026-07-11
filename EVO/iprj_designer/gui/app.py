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
i Ignore Zone · a Text Label · g snap · u / Ctrl-Z undo · Esc cancel ·
digits + Enter dimension entry (Event Zone/Ignore) · n/b cycle selection ·
arrows nudge · x/Del delete · Shift-click toggles a zone in/out of the
selection · Ctrl-drag copies the selected zone · p / double-click properties
(zone or text label) ·
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
Event Zone, Ignore Zone, Lineal (generic 2-point reference line), or Text
Label (a single-click point label). Event Zone and Ignore Zone are
4-click/dimensioned polygons; Lineal is a 2-click segment; Text Label commits
on one click. The sub-type also retargets Edit — pick another kind in Draw to
then select/edit that kind's elements. For the owned kinds (Lineal, Text
Label) and centerlines, a General/Active-sensor toggle (ROADMAP Item 22)
chooses the vendor index band the element is saved into, so it travels to the
right file on the 2-file split. Text Label draw mode also shows an inline
editor bar (text / size / color / B·I·U / rotation) whose current values are
what a click places — the draft ghosts at the cursor before you click; the
properties dialog edits a placed label the same way.

Background tool: click two reference points then enter the known distance
between them (2-point calibration), or use the context bar's calibrate
button to enter a known image width/height instead. The context bar's
upload button replaces the open project's background image in place —
zones, sensors, and centerlines are kept; recalibrate afterward if the new
image is at a different scale.

Ruler: a chrome-row toggle (r) — click to set the first point, move to see
the live distance in feet, click again (or release a drag) to set the
second. It captures clicks over whatever tool is active underneath, but
selecting another tool or Draw sub-kind turns it off (so a picked tool is
usable immediately, not blocked by a forgotten ruler). "Clear ruler" next to
it clears the measurement; Esc cancels one in progress.

Templates (Item 27: folded into Draw › Event Zone, no separate tool): in
Draw with the Event Zone sub-kind, pick a template from the context-bar
"template" dropdown to switch clicks from free-draw to template drops; leave
it blank to free-draw a plain event zone. If a picked template leaves any
placement value unresolved, a dialog prompts for direction/thru phase/LT
phase/Base Output before you can place it (reopen it any time via the
"placement values" button). Then click the anchor reference point (where the
stop bar crosses the template's anchor lane line — by default the line
between the exclusive left-turn lanes and the thru lanes). The one "along CL"
dropdown (Item 27, replacing the Item-19 follow-switch + pick-select) governs
every event zone drawn here: pick a centerline and that one click places the
whole detector set along it (and a plain drawn zone joins its membership
group, Item 26); leave it blank to click again and aim upstream, placing
along that straight line with no group. Centerline-placed zones stay
attached: reshaping the centerline re-stations them. Membership is persisted
explicitly (Item 26), so reopening a project restores it without re-deriving
from geometry; pre-Item-26 files fall back to the geometric re-derivation
(a notification reports how many zones re-attached).

Centerline tool: pick the active centerline from its selector (or add a new
one for another approach), then click along it starting at the stop bar
(station 0) and continuing upstream; click-drag repositions a vertex, x/Del
removes the selected one. Name the active centerline in the "name" box
(Item 20; session-only, e.g. N_CL for the north approach) — the name shows
in every centerline picker, including the Event-Zone "along CL" dropdown. The
status/position readouts show live station + offset while the tool is
active. All centerlines in the project render at once; only the active one
is editable.
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import base64
import collections
import io
import math
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nicegui import ui

from gui.drawing import (ARROWS, DIM_OFF, IGNORE_KIND, LABEL_KIND, LINEAL_KIND,
                         LOOP_KIND, NUDGE_FT, CenterlineController,
                         DrawingController, bulk_reassign, derive_attachments,
                         element_owner, element_points, insert_zone,
                         is_placeholder, next_output_number, set_element_owner)
from gui.viewport import MAX_SCALE, MIN_SCALE, Viewport
from model import domain, geometry, units
from model.bands import Owner, resolve_owner, sensor_owner
from model.centerline import (load_centerlines_owned, load_lineals_owned,
                              save_centerlines_owned, save_lineals_owned)
from model.labels import (format_membership_label, load_labels_owned,
                          match_name_labels, parse_membership_label,
                          save_labels_owned)
from model.iprj_io import (Background, Condition, EventZone, Project, Sensor,
                           TextLabel, load_iprj, save_iprj)
from model.multifile import (MAX_SENSORS, BackgroundMismatch,
                             check_background_match, is_multifile,
                             is_valid_pair, merge_pair, pair_paths,
                             pair_role, split_project)
from model.calibration import (IDENTITY, AlignmentTransform, Placement,
                               RigidDelta, build_alignment, calibrate,
                               commit_alignment, nudged_delta, rotated_about,
                               translated, world_delta)
from model.replay import (Frame, LiveAligner, Recording, load_recording,
                          marker_color, realign, short_id)
from model.fusion import fuse, fused_frame_markers, frame_times_s
from model.zonefit import ZoneFit
from model.templates import (DIRECTIONS, PlacementContext, expand_and_place,
                             expand_and_place_on_centerline, load_template,
                             missing_placeholders)
from capture.hosts import known_hosts
from capture.recorder import RecordingSession

REPO = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"

# Live overlay (ROADMAP Item 35, LIVE_OVERLAY_PLAN.md §§3/5): if no new aligned
# frame reaches the slot within this window the marker layer clears, so a stalled
# or silently dropped stream fades instead of freezing its last markers on screen.
LIVE_STALE_TIMEOUT = 2.0

PHASE_COLORS = ["#d62728", "#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd",
                "#8c564b", "#e377c2", "#bcbd22", "#17becf"]

# (ROADMAP Item 27 retired the nearest-centerline snap threshold that used to
# live here — template placement now follows an explicitly picked centerline
# or aims upstream, never an auto/nearest datum. `geometry.nearest_centerline`
# still backs the on-load geometric membership fallback in derive_attachments.)

# Where a centerline's membership label parks (ROADMAP Item 26): stacked near
# the image's top-left, in image px, converted to world on placement. The tie
# is re-derived from the label's Text, not its position, so this is purely
# cosmetic — a tidy spot out of the way of the geometry.
MEMBERSHIP_MARGIN_PX = 16.0
MEMBERSHIP_STEP_PX = 22.0

# Centerline-select sentinels for the properties/bulk dialogs (Item 26): a real
# centerline is a 0-based index, so these stay out of that range.
_CL_NONE = -1        # "— none —" (detach from any centerline)
_CL_UNCHANGED = -2   # bulk editor: leave each zone's membership as-is
_SENSOR_UNCHANGED = -1  # bulk editor: leave each zone's sensor as-is

# Draw sub-types (PHASE3_UI_PLAN §4.1) shown in the Draw tool's context bar.
# "Text Label" is the ROADMAP Item 22 point entity.
DRAW_KINDS = {"Event Zone": LOOP_KIND, "Ignore Zone": IGNORE_KIND,
              "Lineal": LINEAL_KIND, "Text Label": LABEL_KIND}

# Which draw sub-types are band-owned project-wide pools (route to a sensor
# file by index band) rather than a sensor's own zone list (ROADMAP Item 22).
OWNED_KINDS = {"Lineal", "Text Label"}

# Draw sub-kinds that aren't element-drawing kinds but fold into the Draw tool
# as their own effective modes (ROADMAP Item 24). draw_kind_toggle carries them
# alongside DRAW_KINDS; the Viewer's draw_kind_name stays the last *drawing*
# kind (so draw_zones()/DRAW_KINDS lookups remain valid) while these are active.
MODE_SUBKINDS = ("Centerline", "Sensor")

# Sentinel option key for "General" in the unified Owner/Sensor dropdown
# (Item 24); sensor options use plain int indices, so a non-int key is unambiguous.
_GENERAL_KEY = "G"


def effective_mode(tool_val: str, kind_val: str, overlay_kind_val: str = "Replay") -> str:
    """The effective mode the drawing state machine branches on (ROADMAP
    Item 24), derived from the top-level tool (Draw/Edit/Background/Overlay)
    plus the Draw sub-kind or, for Overlay, the Overlay sub-kind. Sensor and
    Centerline sub-kinds resolve to their own modes; everything else under
    Draw is "Draw". Template (Item 27) is a sub-state of "Draw" › Event Zone,
    not an effective mode, so it never resolves here. Overlay (ROADMAP
    Item 37) folds Record/Replay/Live into one top-level tool whose
    Record/Replay/Live sub-kind *is* the effective mode — the three modes
    themselves are unchanged from Items 30/31/35, only their entry point
    moved. Align (ROADMAP Item 40) is a fourth Overlay sub-kind: an
    interactive-alignment mode where the overlay persists over an editable
    canvas and drag/rotate moves ghost copies of the sensors together with
    their tracks — a proposed sensor move, committable into the iprj (plan
    §4, reframed 2026-07-11)."""
    if tool_val == "Edit":
        return "Edit"
    if tool_val == "Background":
        return "Background"
    if tool_val == "Overlay":
        return overlay_kind_val  # "Record" | "Replay" | "Live" | "Align"
    if kind_val == "Centerline":
        return "Centerline"
    if kind_val == "Sensor":
        return "Sensor"
    return "Draw"


def marker_source(mode_val: str, has_replay: bool, live_running: bool) -> str:
    """Which painter drives the shared track-marker layer (ROADMAP Item 40,
    owner fix 2026-07-11). The Overlay sub-modes each own their painter
    ("replay"/"live"/"align"; Record is blank — it captures, nothing to
    overlay). Every *other* mode — Draw, Edit, Sensor, Centerline,
    Background — persists whatever overlay source is running instead of
    clearing: this is Item 40's relaxed read-only invariant, so the tracks
    stay on screen (and animating — see _enter_mode) while the user draws or
    edits under them. A running live feed wins over a loaded recording, the
    same precedence align_source_frame() uses. Pure, so the routing is
    testable headless; refresh_marker_layer just dispatches on it."""
    if mode_val in ("Replay", "Live", "Align"):
        return mode_val.lower()
    if mode_val == "Record":
        return ""
    if live_running:
        return "live"
    if has_replay:
        return "replay"
    return ""


def general_offered(mode: str, draw_kind: str) -> bool:
    """Whether "General" is a valid owner in the given mode/sub-kind (Item 24,
    §3.3): owned annotations (Lineal/Text Label) and centerlines may be General.
    Zones and sensor picking must name a sensor; Edit only scopes the active
    sensor (it never sets an owner), so it offers sensors only too."""
    if mode == "Centerline":
        return True
    if mode == "Draw":
        return draw_kind in OWNED_KINDS
    return False  # Edit, Sensor, Background

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


def sensor_boresight_deg(azimuth_angle: float | None) -> float:
    """Canvas polar angle (y-down, atan2(dy,dx) convention) a sensor's beam
    points along, from its iprj ``AzimuthAngle``. The mapping ``-az - 90`` was
    read off the real sites (2026-07-11): a sensor's event zones sit downstream
    of its boresight, and this fit the zone-cluster direction to within a few
    degrees across every surveyed site. ``world_to_image`` is a pure
    translate+scale (no rotation), so the same angle holds in canvas space."""
    return -(azimuth_angle or 0.0) - 90.0


def _sensor_glyph(cx, cy, boresight_deg, r, *, fill, stroke, stroke_width,
                  fill_opacity=None, dash=None) -> str:
    """Directional "radio wedge" sensor glyph: a pizza-slice fanning from the
    sensor point out to an arc, with two concentric signal arcs beyond it, the
    whole thing aimed along *boresight_deg* (canvas polar angle). The curved
    side — the wedge's one unique edge — centres on the aim direction, so the
    glyph reads as "this sensor looks that way". Replaces the old rotationless
    triangle; the Align ghost reuses it at its proposed azimuth."""
    th = math.radians(boresight_deg)
    a = math.radians(40.0)   # wedge half-angle
    b = math.radians(32.0)   # signal-arc half-angle (a touch narrower)

    def pt(rad, ang):
        return (cx + rad * math.cos(th + ang), cy + rad * math.sin(th + ang))

    common = f'stroke="{stroke}" stroke-width="{stroke_width:.2f}"'
    if dash:
        common += f' stroke-dasharray="{dash}"'
    fo = f' fill-opacity="{fill_opacity}"' if fill_opacity is not None else ""
    # Wedge: apex at the sensor, sweeping the short way (large-arc-flag 0,
    # sweep-flag 1 = increasing angle = clockwise in y-down) to the far arc.
    p0, p1 = pt(r, -a), pt(r, a)
    wedge = (f'M {cx:.1f} {cy:.1f} L {p0[0]:.1f} {p0[1]:.1f} '
             f'A {r:.1f} {r:.1f} 0 0 1 {p1[0]:.1f} {p1[1]:.1f} Z')
    parts = [f'<path d="{wedge}" fill="{fill}"{fo} {common} '
             f'stroke-linejoin="round"/>']
    for k in (1.34, 1.68):   # concentric signal ripples beyond the wedge
        rk = r * k
        q0, q1 = pt(rk, -b), pt(rk, b)
        parts.append(f'<path d="M {q0[0]:.1f} {q0[1]:.1f} '
                     f'A {rk:.1f} {rk:.1f} 0 0 1 {q1[0]:.1f} {q1[1]:.1f}" '
                     f'fill="none" {common} stroke-linecap="round"/>')
    return "".join(parts)


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
        # Item 25: the drawing surface is an oversized canvas — 2x the background
        # each way, background centered inside it — so zones/lineals/labels/
        # sensors can be placed *off* the image. World coordinates are untouched
        # (saved .iprj coords never shift): world<->image stays anchored to the
        # bg-pixel origin, and the canvas offset is applied only at the render /
        # mouse boundary via world_to_canvas / canvas_to_world.
        self._recompute_canvas()
        self.viewport = Viewport()
        # ROADMAP Item 24: the top-level tool toggle is now Draw/Edit/Background
        # only; Sensor and Centerline fold into Draw sub-kinds (draw_kind_toggle).
        # `self.mode` stays the *effective* mode the drawing state machine
        # branches on — "Draw"/"Edit"/"Background"/"Centerline"/"Sensor" —
        # derived from tool + sub-kind by effective_mode(). Item 27 folded
        # template placement into Draw › Event Zone: it is not its own mode but
        # a sub-state of "Draw" (see template_placement_active()), live when a
        # template is picked in the Event-Zone bar. (History: Phase 3.2b had six
        # top-level tools; Pan is gone since PHASE3_UI_PLAN §5 — Edit is the
        # default and panning is space_pan / middle-drag everywhere.)
        self.mode = "Edit"
        # Zone-table panel visibility (Item 24, §5): "Auto" shows it only when a
        # zone kind is the active target, "On" always, "Off" never.
        self.zone_panel_mode = "Auto"
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
        # Replay (ROADMAP Item 30): a loaded EVO Recording animated over the
        # overlay in the read-only "Replay" mode (plan §4). The engine (Item 29)
        # emits world-feet; the marker layer renders them through the same
        # feet -> world-px -> canvas path as every other overlay object, so they
        # register against the background at any zoom/pan. `replay_pos` is a
        # fractional frame accumulator so sub-1x speeds advance smoothly.
        self.replay: Recording | None = None
        self.replay_path: Path | None = None
        self.replay_frame = 0
        self.replay_pos = 0.0
        self.replay_playing = False
        self.replay_speed = 1.0
        self.replay_labels = True
        # Fusion overlay (ROADMAP Item 43): a raw↔fused toggle over the Replay
        # markers. Fused view runs the Item 42 batch stitcher over the loaded
        # recording and renders one marker/id per real vehicle (cross-sensor
        # dedup + within-sensor stitch), instead of the raw per-sensor points.
        # The result is expensive to compute over a whole recording, so it is
        # cached, keyed by (recording identity, calibrated?) — recomputed only
        # when the recording or its calibration state changes. Fusion is
        # batch-only (FUSION_PLAN §5), so Live always shows raw.
        self.fused_view = False
        self._fusion = None            # cached FusionResult
        self._fusion_frames: tuple = ()  # per-frame {fused_id: (x_ft, y_ft)}
        self._fusion_key = None        # (id(recording), calibrated) of the cache
        # Record (ROADMAP Item 31, plan §5): live capture sessions keyed by
        # host, so the Record dialog can be reopened to check on / stop a
        # capture started earlier without losing it. Single-host minimum
        # per plan §5; nothing stops a second host running concurrently.
        self.record_sessions: dict[str, RecordingSession] = {}
        # Live overlay (ROADMAP Item 35, plan §§3-5): a read-only "Live" mode
        # that taps a RecordingSession's message stream (the Item 34 feed-tap),
        # runs the Item 33 streaming LiveAligner per message, and drives the
        # Item 30 marker layer. `live_frame` is the single "latest aligned frame"
        # slot (frame + monotonic stamp) the capture callback overwrites and the
        # ui.timer reads — drop-to-latest, so socket rate never floods the redraw
        # (plan §3). Bounded: only ever the newest frame, never a growing list.
        self.live_session: RecordingSession | None = None
        self.live_aligner: LiveAligner | None = None
        self.live_cb = None  # the subscribed callback, kept so we can unsubscribe
        self.live_frame: tuple[Frame, float] | None = None
        self.live_labels = True
        # Rolling buffer of live frames (Item 40): auto-calibrate needs many
        # frames' worth of vehicle pairs (the statistical fit needs volume,
        # plan §2c/§7), but the live path keeps only the newest slot for the
        # drop-to-latest render. This bounded deque retains recent live frames
        # so "Auto-calibrate" has real data on a live overlay too, not only a
        # loaded recording. Bounded, so a long live session can't grow it.
        self.live_history: collections.deque = collections.deque(maxlen=3000)
        # Interactive alignment (ROADMAP Item 40, CALIBRATION_ALIGNMENT_PLAN.md
        # §4): the overlay's composed transform is authored here, in-memory and
        # reversible (plan §5a — the Project is untouched until an explicit
        # Commit). `align_placement` is the group transform G a locked drag/
        # rotate edits as a rigid body; `align_calib` is the per-sensor
        # calibration {Cᵢ} an Auto-calibrate solves and holds *locked* beneath G
        # (unlock to hand-adjust one sensor). Markers in Align mode render by
        # live-applying current_alignment() to each point's raw meters, so a
        # drag re-seats the tracks in real time (marker-layer-only, plan §6).
        self.align_placement: ZoneFit | Placement | None = None
        self.align_calib: dict[int, RigidDelta] = {}
        self.align_calibration = None  # last Calibration solve, for the readout
        self.align_locked = True   # locked: drag → G; unlocked: drag → active Cᵢ
        self.align_labels = True
        self.align_rotate_armed = False  # group-rotate 2-click, like Edit rotate
        self.align_drag: dict | None = None  # in-flight group / per-sensor drag
        # The *baseline* mapping (owner reframing, 2026-07-11): the automatic,
        # uncalibrated fit consistent with the sensors' stored iprj placement.
        # Ghost sensors render at world_delta(align_base, current, slot) applied
        # to each mapped sensor — "where the sensor would be if it were moved so
        # its stream lands where the overlay now shows it" — and Commit writes
        # exactly that. Seeded once per authoring session; re-based to the
        # committed transform on Commit so ghosts collapse onto the moved
        # sensors instead of double-counting.
        self.align_base: AlignmentTransform | None = None
        # Pre-commit snapshot {"sensors": {si: (azimuth, x_px, y_px)},
        # "base": AlignmentTransform} for the commit undo (plan §5d): None
        # until a commit, restored by the align Undo button.
        self.align_commit_snapshot: dict | None = None
        # Generic (non-chain) Lineals: a project-wide pool the Lineal draw
        # kind targets, round-tripped via model/centerline.py's
        # load_lineals/save_lineals (PHASE3_UI_PLAN §4.3). Each carries its
        # band Owner as a transient `_owner` (ROADMAP Item 22).
        self.lineals: list = []
        for owner, lin in load_lineals_owned(project):
            set_element_owner(lin, owner)
            self.lineals.append(lin)
        # Text labels (ROADMAP Item 22): the same working-pool model as
        # lineals — enabled TextLabels, owner-tagged, saved back into bands.
        self.labels: list = []
        for owner, lbl in load_labels_owned(project):
            set_element_owner(lbl, owner)
            self.labels.append(lbl)
        # Ownership assignment for newly drawn owned annotations (lineals /
        # labels / centerlines): when True they go to the GENERAL band (both
        # files); when False they follow the active sensor's file band
        # (S1/S2 -> _1_2, S3/S4 -> _3_4). Defaults to General, matching
        # Item 21's "everything defaults to the general band".
        self.assign_general = True
        # Draft text label edited in the Draw-mode editor bar (ROADMAP Item 22
        # follow-up): a click in Text Label draw mode places a copy of this,
        # anchored at the click. The bar's controls write its fields live.
        self.label_draft: TextLabel = domain.new_label((0.0, 0.0), "Label")
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
        # Item 27: one CL dropdown for Event-Zone drawing (was the Item 19
        # follow-switch + pick-select). A chosen centerline index ⇒ templates
        # place *along* it and a plain drawn zone joins its membership group
        # (Item 26); None ⇒ aim-upstream template placement / no membership.
        self.event_cl_idx: int | None = None
        # approach centerlines (Session 7.2 draw/edit, Session 7.4
        # persistence): one CenterlineController per centerline found in the
        # project's Lineals, plus a fresh empty one ready to draw if there
        # were none; active_cli picks which is currently editable.
        self.centerlines: list[CenterlineController] = []
        for owner, pts in load_centerlines_owned(project):
            ctrl = CenterlineController(self.ft_per_px)
            ctrl.points = list(pts)
            ctrl.owner = owner
            self.centerlines.append(ctrl)
        if not self.centerlines:
            self.centerlines.append(CenterlineController(self.ft_per_px))
        self.active_cli = 0
        # Re-derive each centerline's name from a no-rotation label sitting at
        # its far end (ROADMAP Item 22) — the .iprj carries no association tag,
        # the way derive_attachments reconstructs zone/centerline links. The
        # adopted label becomes that centerline's managed name_label.
        self._derive_centerline_names()
        # drawing/editing operates on the active sensor's zones
        if not project.sensors:
            project.sensors.append(Sensor())
        self.active_si = 0
        self.ctrl = DrawingController(self.draw_zones(),
                                      self.ft_per_px, self.next_output,
                                      owner_supplier=self.current_owner,
                                      label_draft=lambda: self.label_draft,
                                      on_commit=self.on_zone_committed)
        # self.mode defaults to "Edit" (ctrl.mode "edit"); a ui.toggle's on_change
        # fires only on a user-driven change, never for its initial value,
        # so the controller needs this nudge to start in step with the tool.
        self.ctrl.set_mode("edit")
        # Centerline membership (ROADMAP Item 26) is explicit and persisted as
        # a per-centerline label; reconstruct it from those labels — no
        # geometry. Only when the project carries none (a pre-Item-26 file) do
        # we fall back to the old geometric derivation, which re-attaches zones
        # that are exact station/offset rectangles on a loaded centerline.
        self._derive_membership()
        self.derived_attachments = 0 if self._has_membership_labels else \
            derive_attachments(
                self.centerlines, [s.event_zones for s in project.sensors])

    def next_output(self) -> int:
        return next_output_number(s.event_zones for s in self.project.sensors)

    def active_zones(self):
        return self.project.sensors[self.active_si].event_zones

    def draw_zones(self) -> list:
        """The element list the active draw kind/Edit targets: the active
        sensor's event zones or ignore zones, or the project-wide lineal or
        text-label pool (PHASE3_UI_PLAN §4.1, §6.1 — one kind/list at a time)."""
        if self.draw_kind_name == "Event Zone":
            return self.active_zones()
        if self.draw_kind_name == "Ignore Zone":
            return self.project.sensors[self.active_si].ignore_zones
        if self.draw_kind_name == "Text Label":
            return self.labels
        return self.lineals

    def current_owner(self) -> Owner:
        """The band Owner a newly drawn owned annotation gets (ROADMAP
        Item 22): GENERAL when 'assign to General' is on, else the active
        sensor's file band."""
        return Owner.GENERAL if self.assign_general else sensor_owner(self.active_si)

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
        ctrl = CenterlineController(self.ft_per_px)
        ctrl.owner = self.current_owner()
        self.centerlines.append(ctrl)
        self.active_cli = len(self.centerlines) - 1
        return self.active_cli

    def centerline_label(self, i: int) -> str:
        """Display name for centerline *i* — its session name (Item 20) or
        the positional C{n} fallback."""
        return self.centerlines[i].name or f"C{i + 1}"

    # -- centerline-name labels (ROADMAP Item 22) ---------------------------

    def _label_index(self, lbl) -> int:
        """Index of *lbl* in the label pool by identity (TextLabel is an
        eq-comparing dataclass, so `in`/`index` would match a twin)."""
        for i, x in enumerate(self.labels):
            if x is lbl:
                return i
        return -1

    def _derive_centerline_names(self) -> None:
        """On load: adopt a no-rotation label at each centerline's far end as
        that centerline's managed name label, and take its text as the name —
        the geometric re-link the .iprj can't persist (cf.
        `derive_attachments`)."""
        far_ends = [cl.far_end() for cl in self.centerlines]
        for ci, li in match_name_labels(far_ends, self.labels).items():
            cl, lbl = self.centerlines[ci], self.labels[li]
            cl.name = (lbl.text or "").strip()
            cl.name_label = lbl

    def sync_centerline_labels(self) -> None:
        """Keep every centerline's managed name label in step with its name,
        far end, and owner band (ROADMAP Item 22) — create it when a named
        centerline first has geometry, move it to the far end as the shape
        changes, and drop it when the name is cleared."""
        for cl in self.centerlines:
            self._sync_one_centerline_label(cl)

    def _sync_one_centerline_label(self, cl: CenterlineController) -> None:
        lbl = cl.name_label
        if lbl is not None and self._label_index(lbl) == -1:
            lbl = cl.name_label = None  # user deleted it from the pool
        name = (cl.name or "").strip()
        end = cl.far_end()
        if not name or end is None:
            if lbl is not None:
                idx = self._label_index(lbl)
                if idx != -1:
                    self.labels.pop(idx)
                cl.name_label = None
            return
        if lbl is None:
            lbl = domain.new_label(end, name)
            cl.name_label = lbl
            self.labels.append(lbl)
        lbl.text = name
        lbl.position_x, lbl.position_y = float(end[0]), float(end[1])
        lbl.rotation_angle = 0.0
        set_element_owner(lbl, cl.owner)

    # -- centerline-membership labels (ROADMAP Item 26) ---------------------

    @property
    def _sensor_index_offset(self) -> int:
        """Absolute-vs-file-local sensor-index offset for membership slots
        (ROADMAP Item 26). Membership slots are written in absolute
        (merged-project) sensor space (0-3); the two-file split renumbers the
        _3_4 half's sensors to 0/1 on disk, so when this project *is* a bare
        _3_4 half its file-local sensors are 2 below absolute. Everything else
        — the merged overlay, the _1_2 half, an ordinary single file — is
        offset 0 (its local indices already equal absolute)."""
        return 2 if pair_role(self.source) == "3_4" else 0

    def _zone_slot(self, zone) -> tuple[int, int] | None:
        """The zone's (sensor index, zone index) slot in the loaded project by
        identity, or None (ROADMAP Item 26). These are *file-local* indices;
        `member_slots` shifts them to absolute for persistence."""
        for si, s in enumerate(self.project.sensors):
            for zi, z in enumerate(s.event_zones):
                if z is zone:
                    return (si, zi)
        return None

    def member_slots(self, cl: CenterlineController) -> list[tuple[int, int]]:
        """Absolute (sensor, zone-index) slots of *cl*'s member zones — what its
        membership label persists (ROADMAP Item 26). File-local slots are lifted
        to absolute space by `_sensor_index_offset` so a re-save from a bare
        _3_4 half still writes merged-space indices."""
        off = self._sensor_index_offset
        slots = []
        for zone in cl.member_zones():
            slot = self._zone_slot(zone)
            if slot is not None:
                slots.append((slot[0] + off, slot[1]))
        return slots

    def _derive_membership(self) -> None:
        """On load: reconstruct each centerline's zone membership from its
        persisted membership label (ROADMAP Item 26) — the explicit,
        no-geometry replacement for `derive_attachments`. A label whose Text
        parses as ``"name: slots"`` (`parse_membership_label`) and whose name
        matches a centerline is adopted as that centerline's managed membership
        label, and every listed slot re-attached (projected onto the datum).
        Slots are absolute sensor indices, mapped to this file's local indexing
        by `_sensor_index_offset`, so a bare _3_4 half resolves its own members
        even though its sensors are renumbered to 0/1 on disk (a slot for a
        sensor not in this file simply doesn't resolve and is skipped). Sets
        `_has_membership_labels` so the caller knows whether to fall back to the
        geometric derivation."""
        self._has_membership_labels = False
        off = self._sensor_index_offset
        by_name: dict[str, CenterlineController] = {}
        for cl in self.centerlines:
            nm = (cl.name or "").strip()
            if nm:
                by_name.setdefault(nm, cl)
        for lbl in self.labels:
            parsed = parse_membership_label(lbl.text or "")
            if parsed is None:
                continue
            name, slots = parsed
            cl = by_name.get(name)
            if cl is None or cl.membership_label is not None:
                continue
            cl.membership_label = lbl
            self._has_membership_labels = True
            for abs_si, zi in slots:
                local_si = abs_si - off
                if not (0 <= local_si < len(self.project.sensors)):
                    continue
                zones = self.project.sensors[local_si].event_zones
                if 0 <= zi < len(zones) and not is_placeholder(zones[zi]):
                    cl.attach_projected(zones[zi])

    def _membership_anchor(self, slot: int) -> tuple[float, float]:
        """World-px parking point for the *slot*-th membership label — stacked
        near the image's top-left (position is cosmetic; see Item 26)."""
        return units.image_to_world(
            self.bg, (MEMBERSHIP_MARGIN_PX,
                      MEMBERSHIP_MARGIN_PX + slot * MEMBERSHIP_STEP_PX))

    def sync_membership_labels(self) -> None:
        """Keep every centerline's membership label in step with its members,
        name, and owner band before save (ROADMAP Item 26): create it when a
        named centerline first has members, refresh its ``name: slots`` text,
        and drop it when the name is cleared or the last member leaves. Only
        named centerlines persist membership (the label needs a name to re-link
        on load); an unnamed centerline's membership stays session-local."""
        slot = 0
        for cl in self.centerlines:
            slot = self._sync_one_membership_label(cl, slot)

    def _sync_one_membership_label(self, cl: CenterlineController,
                                   slot: int) -> int:
        lbl = cl.membership_label
        if lbl is not None and self._label_index(lbl) == -1:
            lbl = cl.membership_label = None  # user deleted it from the pool
        name = (cl.name or "").strip()
        slots = self.member_slots(cl)
        if not name or not slots:
            if lbl is not None:
                idx = self._label_index(lbl)
                if idx != -1:
                    self.labels.pop(idx)
                cl.membership_label = None
            return slot
        text = format_membership_label(name, slots)
        anchor = self._membership_anchor(slot)
        if lbl is None:
            lbl = domain.new_label(anchor, text)
            cl.membership_label = lbl
            self.labels.append(lbl)
        lbl.text = text
        lbl.position_x, lbl.position_y = float(anchor[0]), float(anchor[1])
        lbl.rotation_angle = 0.0
        set_element_owner(lbl, cl.owner)
        return slot + 1

    def membership_for(self, zone) -> CenterlineController | None:
        """The centerline *zone* is a member of, or None (ROADMAP Item 26)."""
        for cl in self.centerlines:
            if id(zone) in cl.attached:
                return cl
        return None

    def set_zone_membership(self, zone, target_ci: int) -> bool:
        """Move *zone* into centerline index *target_ci* (or detach it when
        *target_ci* < 0), dropping any prior membership (ROADMAP Item 26).
        Returns True on success; False when the target centerline has no datum
        yet (nothing changes in that case)."""
        target = self.centerlines[target_ci] \
            if 0 <= target_ci < len(self.centerlines) else None
        if target is not None and target.current() is None:
            return False
        for cl in self.centerlines:
            cl.detach(zone)
        if target is not None:
            target.attach_projected(zone)
        return True

    def template_placement_active(self) -> bool:
        """Whether the Event-Zone CL-driven template drop is live (ROADMAP
        Item 27): Template folded into Draw › Event Zone, so a template picked
        in the CL/template bar turns each click into a template drop instead of
        a free-draw polygon. Blank template ⇒ plain event-zone drawing."""
        return (self.mode == "Draw" and self.draw_kind_name == "Event Zone"
                and self.template is not None)

    def template_target_centerline(self) -> CenterlineController | None:
        """The centerline template placement follows, or None for aim-upstream
        (ROADMAP Item 27). The Item 19 follow-switch + pick-select collapsed
        into one CL dropdown (`event_cl_idx`): a centerline chosen with a usable
        datum ⇒ place *along* it; blank (or a datum-less pick) ⇒ None, the
        ref-then-aim-upstream flow. The nearest-within-threshold auto mode is
        retired — the owner picks the centerline explicitly now."""
        idx = self.event_cl_idx
        if idx is not None and 0 <= idx < len(self.centerlines):
            ctrl = self.centerlines[idx]
            return ctrl if ctrl.current() is not None else None
        return None

    def on_zone_committed(self, el) -> None:
        """DrawingController.on_commit hook (ROADMAP Item 27): a plain event
        zone drawn while a centerline is picked in the CL dropdown joins that
        centerline's explicit membership group (Item 26). Only fires for the
        active draw kind, so it gates on Event Zone; template drops and Edit
        copies route their own membership and don't reach here."""
        if self.draw_kind_name != "Event Zone" or self.event_cl_idx is None:
            return
        self.set_zone_membership(el, self.event_cl_idx)

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

    def _recompute_canvas(self) -> None:
        """(Re)derive the oversized-canvas size and background offset from the
        current image dimensions (Item 25). Called on load and after a
        background swap so the canvas tracks the new image size."""
        self.canvas_w = 2 * self.image_w
        self.canvas_h = 2 * self.image_h
        self.canvas_off_x = self.image_w / 2.0
        self.canvas_off_y = self.image_h / 2.0

    def world_to_canvas(self, p):
        """World px -> canvas px (element/SVG space). The only place the canvas
        offset is added on the render side."""
        ix, iy = units.world_to_image(self.bg, p)
        return (ix + self.canvas_off_x, iy + self.canvas_off_y)

    def canvas_to_world(self, c):
        """Canvas px (mouse offsetX/Y) -> world px. Inverse of world_to_canvas;
        an off-image click yields a valid (possibly negative/beyond-extent)
        world point without disturbing on-image geometry."""
        return units.image_to_world(
            self.bg, (c[0] - self.canvas_off_x, c[1] - self.canvas_off_y))

    def replay_point_to_canvas(self, x_ft, y_ft):
        """A replay track point's world-feet position -> canvas px (Item 30).

        The Item 29 engine emits canonical world-feet; convert back to world px
        with the *same* calibrated scale the anchor used (so the round-trip is
        exact), then reuse world_to_canvas — the one feet->viewport path all
        overlay objects share, so markers register with the background."""
        emp = units.effective_meter_per_pixel(self.bg)
        return self.world_to_canvas(
            (units.ft_to_px(x_ft, emp), units.ft_to_px(y_ft, emp)))

    def describe(self, canvas_point) -> str:
        wx, wy = self.canvas_to_world(canvas_point)
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
        idx = self.event_cl_idx
        if idx is not None and 0 <= idx < len(self.centerlines) \
                and self.centerlines[idx].current() is not None:
            return (f"mode: template | {self.template.name} | click the "
                    "anchor point (stop bar at the LT/thru lane line) — "
                    f"detectors follow {self.centerline_label(idx)}")
        if self.template_ref is None:
            return (f"mode: template | {self.template.name} | click the "
                    "anchor point (stop bar at the LT/thru lane line)")
        return (f"mode: template | {self.template.name} | aim upstream, "
                "click to place  [Esc cancels]")

    # -- overlay ------------------------------------------------------------

    def svg(self) -> str:
        bg = self.bg
        # Overlay geometry is drawn in canvas space (world_to_image + offset)
        # so it registers with the offset background inside the oversized canvas.
        w2i = self.world_to_canvas
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
                s = 7 * lw
                fill = "#00e5ff" if si == self.active_si else "white"
                parts.append(_sensor_glyph(
                    x, y, sensor_boresight_deg(sensor.azimuth_angle), s,
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
        # text labels (§ ROADMAP Item 22): a point-anchored, styled <text>.
        # Font size tracks the label's FontSize but stays screen-relative so
        # it reads at any zoom (fs 12 ≈ the zone-name label size, 7*lw).
        def label_text_svg(lbl, x, y, *, fill=None, opacity=1.0) -> str:
            lfs = max((lbl.font_size or 12) * lw / 2.0, 1.0)
            color = fill or (f"rgb({lbl.textcolor_red or 0},"
                             f"{lbl.textcolor_green or 0},{lbl.textcolor_blue or 0})")
            style = [f'font-size="{lfs:.1f}"', f'fill="{color}"',
                     'text-anchor="middle"', 'dominant-baseline="middle"',
                     'paint-order="stroke"', 'stroke="black"',
                     f'stroke-width="{lfs / 8:.2f}"']
            if opacity < 1.0:
                style.append(f'opacity="{opacity:.2f}"')
            if lbl.font_bold:
                style.append('font-weight="bold"')
            if lbl.font_italic:
                style.append('font-style="italic"')
            if lbl.font_underline:
                style.append('text-decoration="underline"')
            transform = (f' transform="rotate({-(lbl.rotation_angle or 0):.1f} '
                         f'{x:.1f} {y:.1f})"' if lbl.rotation_angle else '')
            return (f'<text x="{x:.1f}" y="{y:.1f}" {" ".join(style)}'
                    f'{transform}>{escape(lbl.text or "")}</text>')

        lbl_targeted = is_draw_target(self.labels)
        for li, lbl in enumerate(self.labels):
            if not self.show_labels or not lbl.enable:
                continue
            x, y = w2i((lbl.position_x, lbl.position_y))
            selected = lbl_targeted and li in self.ctrl.selection
            if selected:
                r = max((lbl.font_size or 12) * lw / 2.0, 1.0) * 0.75
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" '
                             f'fill="none" stroke="white" stroke-width="{lw}"/>')
            parts.append(label_text_svg(lbl, x, y,
                                        fill="white" if selected else None))
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
        # Align group-rotate (Item 40 fix, 2026-07-11): the pivot cross was
        # only ever drawn for Edit rotate, so Align rotate gave no visual
        # anchor at all. The rotation *preview* lives on the marker layer
        # (markers + ghosts through align_render_alignment); only the pivot
        # belongs on the static overlay.
        if self.mode == "Align" and self.align_rotate_armed \
                and self.rotate_pivot is not None:
            px, py = w2i(self.rotate_pivot)
            parts.append(_cross(px, py, 6 * lw, "#ff4081", lw))
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
        # Text Label draw mode: ghost the draft label at the cursor so the
        # user sees exactly what a click will place (ROADMAP Item 22 follow-up).
        if self.mode == "Draw" and self.draw_kind_name == "Text Label" \
                and self.ctrl.cursor is not None and (self.label_draft.text or "").strip():
            x, y = w2i(self.ctrl.cursor)
            parts.append(_cross(x, y, 4 * lw, "#00e5ff", lw))
            parts.append(label_text_svg(self.label_draft, x, y, opacity=0.55))
        if self.ctrl.snap_indicator is not None:
            x, y = w2i(self.ctrl.snap_indicator)
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{4 * lw:.1f}" '
                         f'fill="none" stroke="orange" stroke-width="{lw}"/>')
        # template placement: reference marker, aim line, live detector preview.
        # With a usable centerline the preview follows it at the hover point
        # (single click places); otherwise the legacy ref-then-aim flow.
        if self.template_placement_active():
            cursor = self.template_cursor
            # mirror place_template's target so the preview matches what the
            # click will actually do (the CL dropdown pick, Item 27)
            cl_ctrl = self.template_target_centerline()
            placed = []
            fpp = self.ft_per_px()
            if cl_ctrl is not None and cursor is not None:
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

    def _marker_svg(self, points, labels: bool, align=None) -> str:
        """Track-marker SVG for one frame's *points* — the single renderer
        Replay (Item 30), Live (Item 35), and Align (Item 40) drive, so markers
        read identically (same evo_replay colors / short ids) whichever mode
        produced the frame. Sizes are in overlay-px scaled by zoom, so markers
        hold their on-screen size at any zoom/pan. Built as its own string for
        the separate marker layer (plan §4): the static zone/centerline overlay
        from svg() renders beneath, untouched, while this is the only content
        rewritten per tick.

        With *align* (an ``AlignmentTransform``) each point is re-aligned from
        its raw EVO meters through the composed transform live — the Align-mode
        path (Item 40), so a group drag/rotate re-seats the markers in real time
        without re-aligning the whole recording. Without it the point's
        precomputed ``x_ft/y_ft`` are used (Replay/Live, unchanged)."""
        lw = self.overlay_px / max(self.viewport.scale, 0.05)
        r = 4 * lw
        font = 7 * lw
        parts = []
        for pt in points:
            if align is not None:
                fx, fy = align.apply(pt.sensor, pt.x_raw_m, pt.y_raw_m)
            else:
                fx, fy = pt.x_ft, pt.y_ft
            cx, cy = self.replay_point_to_canvas(fx, fy)
            parts.append(self._marker_glyph(
                cx, cy, marker_color(pt.sensor),
                escape(short_id(pt.oid)) if labels else "", lw, r, font))
        return "".join(parts)

    def _marker_glyph(self, cx, cy, color, label, lw, r, font) -> str:
        """One marker's SVG — the circle plus (when *label* is non-empty) its
        id text. The single glyph both the raw (`_marker_svg`) and fused
        (`_fused_marker_svg`, Item 43) paths emit, so a marker reads identically
        whichever produced it."""
        glyph = (f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
                 f'fill="{color}" fill-opacity="0.9" stroke="black" '
                 f'stroke-width="{lw / 2:.2f}"/>')
        if label:
            glyph += (
                f'<text x="{cx:.1f}" y="{cy - r - lw:.1f}" fill="white" '
                f'font-size="{font:.1f}" text-anchor="middle" '
                f'paint-order="stroke" stroke="black" '
                f'stroke-width="{font / 8:.2f}">{label}</text>')
        return glyph

    def _fused_marker_svg(self, markers, labels: bool) -> str:
        """Marker SVG for one frame's *markers* — a ``{fused_id: (x_ft, y_ft)}``
        dict from the Item 42 stitcher (ROADMAP Item 43): one marker per real
        vehicle, coloured/labelled by fused id so the same vehicle keeps one
        colour+id across sensors and stitched gaps. Colour cycles the evo_replay
        sensor palette by ``fused_id % 10`` — a stable per-vehicle hue reusing
        the same look as the raw markers."""
        lw = self.overlay_px / max(self.viewport.scale, 0.05)
        r = 4 * lw
        font = 7 * lw
        parts = []
        for fid, (fx, fy) in markers.items():
            cx, cy = self.replay_point_to_canvas(fx, fy)
            parts.append(self._marker_glyph(
                cx, cy, marker_color(fid % 10),
                escape(short_id(fid)) if labels else "", lw, r, font))
        return "".join(parts)

    def ensure_fusion(self):
        """Compute (or return the cached) fused view of the loaded recording
        (ROADMAP Item 43). Keyed by (recording identity, calibrated?) so it is
        run once and reused across every frame/tick, and re-run only when the
        recording or its calibration changes. Returns the ``FusionResult`` (or
        None when no recording is loaded). ``calibrated`` follows whether the
        recording's frames came through a calibrated overlay (Items 38–40): an
        uncalibrated stream widens the cross-sensor gate and flags the result
        (FUSION_PLAN §4b)."""
        rec = self.replay
        if rec is None or not rec.frames:
            return None
        calibrated = bool(rec.alignment is not None and rec.alignment.calib)
        key = (id(rec), calibrated)
        if self._fusion_key != key:
            self._fusion = fuse(rec.frames, calibrated=calibrated)
            self._fusion_frames = fused_frame_markers(
                self._fusion, frame_times_s(rec.frames))
            self._fusion_key = key
        return self._fusion

    def replay_marker_svg(self) -> str:
        """Markers for the current replay frame (ROADMAP Item 30). Returns ""
        when no recording is loaded, so the layer is empty off-Replay. With the
        fused toggle on (Item 43) the frame's fused markers (one per real
        vehicle) render instead of the raw per-sensor points."""
        rec = self.replay
        if rec is None or not rec.frames:
            return ""
        i = max(0, min(self.replay_frame, len(rec.frames) - 1))
        if self.fused_view:
            self.ensure_fusion()
            markers = self._fusion_frames[i] if i < len(self._fusion_frames) else {}
            return self._fused_marker_svg(markers, self.replay_labels)
        return self._marker_svg(rec.frames[i].points, self.replay_labels)

    def live_marker_svg(self) -> str:
        """Markers for the latest live frame in the drop-to-latest slot (ROADMAP
        Item 35, plan §3). Returns "" when no frame has arrived or the slot has
        gone stale past LIVE_STALE_TIMEOUT — a stalled/dropped stream clears
        rather than freezing its last markers on screen (plan §5)."""
        slot = self.live_frame
        if slot is None:
            return ""
        frame, stamped = slot
        if time.monotonic() - stamped > LIVE_STALE_TIMEOUT:
            return ""
        return self._marker_svg(frame.points, self.live_labels)

    def align_source_frame(self):
        """The frame the Align overlay renders (Item 40): the newest live slot
        when a live session is running, else the current replay frame. Returns
        None when neither source has a frame — the overlay is then empty and the
        status line prompts the user to load a recording / connect live."""
        if self.live_session is not None:
            slot = self.live_frame
            if slot is not None and time.monotonic() - slot[1] <= LIVE_STALE_TIMEOUT:
                return slot[0]
            return None
        rec = self.replay
        if rec is not None and rec.frames:
            i = max(0, min(self.replay_frame, len(rec.frames) - 1))
            return rec.frames[i]
        return None

    def current_alignment(self):
        """The composed transform being authored in Align mode (Item 40):
        ``{Cᵢ}`` calibration under the group placement G. None until a
        placement is seeded (no ``Z;`` fit and no anchor — nothing to align)."""
        if self.align_placement is None:
            return None
        return AlignmentTransform(calib=dict(self.align_calib),
                                  placement=self.align_placement,
                                  calibration=self.align_calibration)

    def align_render_alignment(self):
        """current_alignment() with the in-flight 2-click rotate preview
        applied, so markers *and ghost sensors* swing live while the user is
        aiming — commit_align_rotate then makes the previewed value real."""
        tr = self.current_alignment()
        if (tr is None or not self.align_rotate_armed
                or self.rotate_pivot is None or not self.rotate_angle):
            return tr
        fpp = self.ft_per_px()
        if fpp is None:
            return tr
        pivot_ft = (self.rotate_pivot[0] * fpp, self.rotate_pivot[1] * fpp)
        return AlignmentTransform(
            calib=tr.calib,
            placement=rotated_about(tr.placement, pivot_ft, self.rotate_angle),
            calibration=tr.calibration)

    def align_slot_map(self) -> dict[int, int]:
        """Stream slot → project sensor index, from the overlay source's Z;
        fit. Kept off the *source* (recording / live aligner) rather than the
        current placement because a manual group drag turns the placement into
        a plain ``Placement`` that no longer carries the match (plan §3). With
        no Z; the slot is assumed to be the sensor index itself — the vendor's
        ``oid % 10`` convention on a site authored slot-for-sensor."""
        zf = None
        if self.live_session is not None and self.live_aligner is not None:
            zf = self.live_aligner.zone_fit
        elif self.replay is not None:
            zf = self.replay.zone_fit
        if zf is not None:
            return dict(zf.slot_to_sensor)
        return {si: si for si in range(len(self.project.sensors))}

    def align_ghosts(self) -> list[tuple[int, tuple, tuple, float]]:
        """Ghost-sensor placements for the Align overlay (owner reframing,
        2026-07-11): ``[(sensor_index, real_pos_px, ghost_pos_px,
        d_azimuth_deg)]`` for every mapped sensor with a stored position.

        The ghost is where the sensor *would have to move* for its stream to
        land where the authored transform now renders it — the whole point of
        the workflow. Computed live against the baseline mapping, so a group
        drag/rotate (including the rotate preview) moves ghosts and markers
        together while the background and the real sensors stay put."""
        base, cur = self.align_base, self.align_render_alignment()
        fpp = self.ft_per_px()
        if base is None or cur is None or fpp is None:
            return []
        out = []
        for slot, si in sorted(self.align_slot_map().items()):
            if not 0 <= si < len(self.project.sensors):
                continue
            s = self.project.sensors[si]
            if s.position_x is None or s.position_y is None:
                continue
            try:
                wd = world_delta(base, cur, slot)
            except ValueError:  # degenerate placement — no ghost to show
                continue
            g_ft = wd.apply_ft(s.position_x * fpp, s.position_y * fpp)
            out.append((si, (s.position_x, s.position_y),
                        (g_ft[0] / fpp, g_ft[1] / fpp), wd.rotation_deg))
        return out

    def align_dirty(self) -> bool:
        """Whether the authored alignment proposes any real sensor move —
        gates the Commit button and the status-line Δ readout."""
        fpp = self.ft_per_px()
        if fpp is None:
            return False
        return any(
            math.hypot(g[0] - r[0], g[1] - r[1]) * fpp >= 0.05
            or abs(daz) >= 0.01
            for _, r, g, daz in self.align_ghosts())

    def align_marker_svg(self) -> str:
        """The Align overlay (Item 40, reframed 2026-07-11): the source frame
        re-aligned live through the authored transform, plus ghost copies of
        the mapped sensors moving with it — so a group drag/rotate visibly
        moves the *sensors* and their tracks together against the fixed
        background. Empty when no placement is seeded yet."""
        align = self.align_render_alignment()
        if align is None:
            return ""
        parts = ""
        frame = self.align_source_frame()
        if frame is not None:
            parts = self._marker_svg(frame.points, self.align_labels,
                                     align=align)
        return parts + self._align_ghost_svg()

    def _align_ghost_svg(self) -> str:
        """Dashed ghost-sensor glyphs + displacement leaders, rendered on the
        marker layer so drag ticks stay marker-layer-only (plan §6). The ghost
        wedge is aimed at the sensor's *proposed* azimuth (its current azimuth
        plus the alignment's rotation), and a leader line ties it back to the
        real (unmoved) sensor so the size of the proposed move reads at a
        glance."""
        ghosts = self.align_ghosts()
        if not ghosts:
            return ""
        lw = self.overlay_px / max(self.viewport.scale, 0.05)
        font = 7 * lw
        s = 7 * lw
        parts = []
        for si, real_px, ghost_px, d_az in ghosts:
            ox, oy = self.world_to_canvas(real_px)
            gx, gy = self.world_to_canvas(ghost_px)
            if math.hypot(gx - ox, gy - oy) > 0.5:
                parts.append(
                    f'<line x1="{ox:.1f}" y1="{oy:.1f}" x2="{gx:.1f}" '
                    f'y2="{gy:.1f}" stroke="#ff9800" stroke-width="{lw / 2:.2f}" '
                    f'stroke-dasharray="{2 * lw} {2 * lw}"/>')
            base_az = self.project.sensors[si].azimuth_angle or 0.0
            parts.append(_sensor_glyph(
                gx, gy, sensor_boresight_deg(base_az + d_az), s,
                fill="#ff9800", fill_opacity="0.35", stroke="#ff9800",
                stroke_width=lw, dash=f"{3 * lw} {2 * lw}"))
            parts.append(f'<text x="{gx:.1f}" y="{gy + s + font:.1f}" '
                         f'fill="#ff9800" font-size="{font:.1f}" '
                         f'text-anchor="middle" paint-order="stroke" '
                         f'stroke="black" stroke-width="{font / 6:.2f}">'
                         f'S{si + 1}&#8242;</text>')
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
# between gestures. e.offsetX/Y are the overlay's untransformed local coords
# (= canvas pixels since Item 25's oversized canvas), and getComputedStyle
# reads `stage` — the element this handler is bound to and the one the server
# transforms — so client and server stay on the same coordinate surface.
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

    ui.add_head_html(
        "<style>body { background: #222; }</style>"
        # keep Ctrl-S for project save instead of the browser's save dialog
        "<script>document.addEventListener('keydown', e => {"
        " if ((e.ctrlKey || e.metaKey) && e.key === 's') e.preventDefault();"
        " });</script>")

    def refresh_overlay():
        ii.content = v.svg()

    def apply_transform():
        # Item 25: pan/zoom act on `stage` (the oversized surface holding both
        # the background image and the interactive_image overlay), not on `ii`.
        stage.style(v.viewport.css())
        # snap/grab radii feel constant on screen regardless of zoom
        f = units.image_scale_factor(v.bg) / max(v.viewport.scale, 0.05)
        v.ctrl.snap_radius = 12.0 * f
        v.ctrl.handle_radius = 10.0 * f
        for cl in v.centerlines:
            cl.handle_radius = 10.0 * f
        refresh_overlay()  # stroke widths track zoom level
        refresh_marker_layer()  # marker sizes track zoom too (Item 30)

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
                bulk_zone_properties()  # ROADMAP Item 26
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
                cl_opts = {_CL_NONE: "— none —"}
                cl_opts.update({i: v.centerline_label(i)
                                for i in range(len(v.centerlines))})
                cur_cl = v.membership_for(zone)
                cl_to = ui.select(
                    cl_opts,
                    value=(v.centerlines.index(cur_cl) if cur_cl else _CL_NONE),
                    label="Centerline").classes("w-32")

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
                # Centerline membership (Item 26): re-route only on an actual
                # change so the message stays informative.
                new_ci = int(cl_to.value if cl_to.value is not None else _CL_NONE)
                cur = v.membership_for(zone)
                cur_ci = v.centerlines.index(cur) if cur else _CL_NONE
                if new_ci != cur_ci and not v.set_zone_membership(zone, new_ci):
                    ui.notify("centerline has no geometry yet — not assigned",
                              type="warning")
                dialog.close()
                refresh_overlay()
                refresh_status()

            with ui.row():
                ui.button("Apply", on_click=apply)
                ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    # -- bulk zone edit (ROADMAP Item 26) --------------------------------------

    def bulk_zone_properties():
        """Edit a multi-zone selection at once (ROADMAP Item 26): reassign
        sensor/phase/centerline and nudge outputs, leaving unnamed fields
        alone. Sensor reassignment reuses the same cross-file move the
        single-zone dialog does (`bulk_reassign` -> `insert_zone`)."""
        if v.mode != "Edit" or v.draw_kind_name != "Event Zone":
            ui.notify("select event zones in the Edit tool first", type="warning")
            return
        si = v.active_si
        zones = v.active_zones()
        sel = [i for i in v.ctrl.selection if 0 <= i < len(zones)
               and not is_placeholder(zones[i])]
        if len(sel) < 2:
            ui.notify("select more than one zone for bulk edit", type="warning")
            return
        sensor_opts = {_SENSOR_UNCHANGED: "— unchanged —"}
        sensor_opts.update({i: f"S{i + 1}" for i in range(len(v.project.sensors))})
        cl_opts = {_CL_UNCHANGED: "— unchanged —", _CL_NONE: "— none (detach) —"}
        cl_opts.update({i: v.centerline_label(i)
                        for i in range(len(v.centerlines))})

        with ui.dialog() as dialog, ui.card().style("min-width: 460px"):
            ui.label(f"Bulk edit {len(sel)} zones").classes("text-lg")
            with ui.row().classes("items-center gap-2"):
                set_phase = ui.checkbox("Set phase")
                phase = ui.number("Phase", value=0, min=0, precision=0).classes("w-24")
            with ui.row().classes("items-center gap-2"):
                ui.label("Output nudge")
                out_nudge = ui.number(value=0, precision=0).classes("w-20")
                ui.button("−1", on_click=lambda:
                          out_nudge.set_value(int(out_nudge.value or 0) - 1)) \
                    .props("flat dense")
                ui.button("+1", on_click=lambda:
                          out_nudge.set_value(int(out_nudge.value or 0) + 1)) \
                    .props("flat dense")
            with ui.row().classes("items-center gap-2"):
                sensor_to = ui.select(sensor_opts, value=_SENSOR_UNCHANGED,
                                      label="Sensor").classes("w-40")
                cl_to = ui.select(cl_opts, value=_CL_UNCHANGED,
                                  label="Centerline").classes("w-48")

            def apply():
                sv = sensor_to.value
                target_zones = (v.project.sensors[sv].event_zones
                                if sv is not None and sv >= 0 and sv != si else None)
                edited = bulk_reassign(
                    zones, sel,
                    phase=int(phase.value or 0) if set_phase.value else None,
                    output_delta=int(out_nudge.value or 0),
                    target_zones=target_zones)
                if cl_to.value != _CL_UNCHANGED:
                    tci = int(cl_to.value if cl_to.value is not None else _CL_NONE)
                    failed = sum(not v.set_zone_membership(z, tci) for z in edited)
                    if failed:
                        ui.notify("centerline has no geometry yet — "
                                  "membership not assigned", type="warning")
                dialog.close()
                if target_zones is not None:
                    # zones left the active sensor; follow them and re-select
                    activate_sensor(sv)
                    new = v.active_zones()
                    ids = {id(z) for z in edited}
                    v.ctrl.select_many([i for i, z in enumerate(new)
                                        if id(z) in ids])
                ui.notify(f"bulk-edited {len(edited)} zones")
                refresh_overlay()
                refresh_status()

            with ui.row():
                ui.button("Apply", on_click=apply)
                ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    # -- text-label properties (ROADMAP Item 22) --------------------------------

    def _hex_to_rgb(value: str) -> tuple[int, int, int]:
        """Parse a '#rrggbb' (or 'rgb(r,g,b)') color into 0–255 ints; falls
        back to white on anything unexpected from the color picker."""
        s = (value or "").strip()
        try:
            if s.startswith("#") and len(s) >= 7:
                return int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16)
            if s.startswith("rgb"):
                nums = [int(float(n)) for n in re.findall(r"[\d.]+", s)[:3]]
                if len(nums) == 3:
                    return nums[0], nums[1], nums[2]
        except ValueError:
            pass
        return 255, 255, 255

    def label_properties():
        if v.mode != "Edit" or v.draw_kind_name != "Text Label":
            ui.notify("select a text label in the Edit tool first", type="warning")
            return
        if len(v.ctrl.selection) != 1:
            ui.notify("select exactly one text label for properties", type="warning")
            return
        li = v.ctrl.selected
        if not (0 <= li < len(v.labels)):
            ui.notify("select a text label first", type="warning")
            return
        lbl = v.labels[li]
        hexcolor = "#%02x%02x%02x" % (lbl.textcolor_red or 0,
                                      lbl.textcolor_green or 0,
                                      lbl.textcolor_blue or 0)
        owner_opts = {Owner.GENERAL: "General (both files)",
                      Owner.FILE1: "S1/2 (_1_2)", Owner.FILE2: "S3/4 (_3_4)"}
        with ui.dialog() as dialog, ui.card().style("min-width: 420px"):
            ui.label("Text label properties").classes("text-lg")
            text_in = ui.input("Text", value=lbl.text or "").classes("w-full")
            with ui.row().classes("items-center"):
                size_in = ui.number("Font size", value=lbl.font_size or 12,
                                    min=1, precision=0).classes("w-24")
                rot_in = ui.number("Rotation°", value=lbl.rotation_angle or 0.0,
                                   precision=1).classes("w-24")
                color_in = ui.color_input("Color", value=hexcolor).classes("w-40")
            with ui.row().classes("items-center gap-4"):
                bold_cb = ui.checkbox("Bold", value=bool(lbl.font_bold))
                italic_cb = ui.checkbox("Italic", value=bool(lbl.font_italic))
                underline_cb = ui.checkbox("Underline", value=bool(lbl.font_underline))
            owner_sel = ui.select(owner_opts, value=element_owner(lbl),
                                  label="Belongs to").classes("w-56")

            def apply():
                lbl.text = text_in.value or ""
                lbl.font_size = int(size_in.value or 12)
                lbl.rotation_angle = float(rot_in.value or 0.0)
                r, g, b = _hex_to_rgb(color_in.value)
                lbl.textcolor_red, lbl.textcolor_green, lbl.textcolor_blue = r, g, b
                lbl.font_bold = int(bold_cb.value)
                lbl.font_italic = int(italic_cb.value)
                lbl.font_underline = int(underline_cb.value)
                set_element_owner(lbl, owner_sel.value)
                dialog.close()
                refresh_overlay()
                refresh_status()

            with ui.row():
                ui.button("Apply", on_click=apply)
                ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    def open_properties():
        """Route the Properties action (p / Enter / double-click / button) to
        the dialog for the active Edit sub-type (ROADMAP Item 22) — and to the
        bulk editor for a multi-zone event-zone selection (ROADMAP Item 26)."""
        if v.mode == "Edit" and v.draw_kind_name == "Text Label":
            label_properties()
        elif v.mode == "Edit" and v.draw_kind_name == "Event Zone" \
                and len(v.ctrl.selection) > 1:
            bulk_zone_properties()
        else:
            zone_properties()

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

    def add_sensor():
        if len(v.project.sensors) >= MAX_SENSORS:
            ui.notify(f"max {MAX_SENSORS} sensors (two-file limit)", type="warning")
            return
        s = Sensor()
        s.position_x, s.position_y = units.image_to_world(
            v.bg, (v.image_w / 2, v.image_h / 2))
        v.project.sensors.append(s)
        v.set_active_sensor(len(v.project.sensors) - 1)
        tool.value = "Draw"
        draw_kind_toggle.set_value("Sensor")  # Sensor sub-kind; rebuilds owner dropdown
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
            refresh_owner_sel()
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
        update_event_cl_options()  # Event-Zone CL dropdown uses the names

    def change_active_centerline(e):
        if e.value is None or e.value == v.active_cli:
            return
        v.set_active_centerline(e.value)
        centerline_name_in.value = v.centerline_ctrl.name
        refresh_overlay()
        refresh_status()

    def rename_centerline(e):
        """Item 20: rename the active centerline; refreshes every picker that
        shows centerline labels. Item 22: the name persists as a no-rotation
        label at the far end, so re-sync the managed name label and redraw."""
        v.centerline_ctrl.name = (e.value or "").strip()
        v.sync_centerline_labels()
        update_centerline_options()
        refresh_overlay()

    def add_centerline():
        v.add_centerline()
        update_centerline_options()
        tool.value = "Draw"
        draw_kind_toggle.set_value("Centerline")  # Centerline sub-kind
        refresh_overlay()
        refresh_status()
        ui.notify(f"{v.centerline_label(len(v.centerlines) - 1)} ready — "
                  "click the stop bar to start it")

    # -- Event-Zone CL dropdown (Item 27: one control for template + membership)

    def update_event_cl_options():
        """Options for the Event-Zone CL dropdown: only centerlines with a
        usable datum — attaching a zone or placing along an empty centerline
        would be a dead choice. Preserves the current pick when it still
        resolves; otherwise clears back to blank (aim-upstream / no membership)."""
        opts = {i: v.centerline_label(i) for i in range(len(v.centerlines))
                if v.centerlines[i].current() is not None}
        keep = v.event_cl_idx if v.event_cl_idx in opts else None
        v.event_cl_idx = keep
        event_cl_sel.set_options(opts, value=keep)

    def change_event_cl(e):
        v.event_cl_idx = e.value  # int index, or None for blank (aim upstream)
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
        cl_ctrl = v.template_target_centerline()
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
        # refresh centerline-name (Item 22) and membership (Item 26) labels
        # (position/text/owner) before they are written out with the rest of
        # the label pool
        v.sync_centerline_labels()
        v.sync_membership_labels()
        save_centerlines_owned(
            v.project, [(cl.owner, cl.points) for cl in v.centerlines])
        # after save_centerlines, so the endpoint-coincidence guard sees the
        # final chain vertices (model/centerline.py's save_lineals docstring)
        skipped = save_lineals_owned(
            v.project, [(element_owner(l), l) for l in v.lineals])
        if skipped:
            ui.notify(f"{len(skipped)} lineal(s) not saved — they touch a "
                      "centerline or another lineal's endpoint, or their band "
                      "is full", type="warning")
        label_skipped = save_labels_owned(
            v.project, [(element_owner(l), l) for l in v.labels])
        if label_skipped:
            ui.notify(f"{len(label_skipped)} text label(s) not saved — their "
                      "index band is full", type="warning")
        if not is_multifile(v.project):
            save_iprj(v.project, path)
            v.source = path
            v.pair = None
            title_label.set_text(path.name)
            folder_tip.set_text(str(path))
            ui.notify(f"saved {path}")
            return
        primary, secondary = split_project(v.project)
        p12, p34 = pair_paths(path)
        save_iprj(primary, p12)
        save_iprj(secondary, p34)
        v.pair = (p12, p34)
        v.source = p12
        title_label.set_text(f"{p12.name} + {p34.name}")
        folder_tip.set_text(str(p12))
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
        v._recompute_canvas()  # Item 25: canvas tracks the new image size
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
            # if a template is currently picked (in the Event-Zone bar, Item 27),
            # open straight to it instead of a blank form
            current = template_sel.value or None
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
        elif v.template_placement_active():
            # a template picked in Draw › Event Zone (Item 27) — its own status
            status_label.set_text(v.template_status())
        elif v.mode in ("Draw", "Edit"):
            status_label.set_text(v.ctrl.status())
        elif v.mode == "Sensor":
            status_label.set_text(
                f"mode: sensor | S{v.active_si + 1} active | "
                "drag a sensor to move it, click one for properties")
        elif v.mode == "Centerline":
            status_label.set_text(f"C{v.active_cli + 1}/{len(v.centerlines)} | "
                                  f"{v.centerline_ctrl.status()}")
        elif v.mode == "Background":
            status_label.set_text(
                "mode: calibrate 2-pt | click two reference points, "
                "then enter the known distance")
        elif v.mode == "Record":
            s = _active_record_session()
            if s is None:
                status_label.set_text(
                    "mode: record | start a capture (record icon at right)")
            else:
                st = s.status
                if st.error:
                    status_label.set_text(f"mode: record | {s.host} | error: {st.error}")
                elif st.connected:
                    status_label.set_text(
                        f"mode: record | {s.host} | {st.frames} frames | "
                        f"{st.fps:.1f} fps")
                elif s.running:
                    status_label.set_text(f"mode: record | {s.host} | connecting…")
                elif st.stopped:
                    name = st.path.name if st.path else "?"
                    status_label.set_text(
                        f"mode: record | {s.host} | stopped — {st.frames} "
                        f"frames → {name}")
                else:
                    status_label.set_text(f"mode: record | {s.host} | idle")
        elif v.mode == "Replay":
            if v.replay is None:
                status_label.set_text(
                    "mode: replay | load an EVO recording (video icon at right)")
            else:
                n = len(v.replay.frames)
                f = v.replay.frames[v.replay_frame]
                if v.fused_view:
                    res = v.ensure_fusion()
                    markers = (v._fusion_frames[v.replay_frame]
                               if v.replay_frame < len(v._fusion_frames) else {})
                    nt = len(markers)
                    view = (f"{nt} fused track{'s' if nt != 1 else ''}"
                            + (" (low-confidence)"
                               if res is not None and res.low_confidence else ""))
                else:
                    nt = len(f.points)
                    view = f"{nt} track{'s' if nt != 1 else ''}"
                status_label.set_text(
                    f"mode: replay | frame {v.replay_frame + 1}/{n} | {f.t} | "
                    f"{view} | "
                    f"{'playing' if v.replay_playing else 'paused'}")
        elif v.mode == "Live":
            s = v.live_session
            if s is None:
                status_label.set_text(
                    "mode: live | connect to an EVO host (sensors icon at right)")
            else:
                st = s.status
                if st.error:
                    status_label.set_text(f"mode: live | {s.host} | error: {st.error}")
                elif st.connected:
                    slot = v.live_frame
                    nt = len(slot[0].points) if slot else 0
                    status_label.set_text(
                        f"mode: live | {s.host} | {st.frames} msgs | "
                        f"{st.fps:.1f} fps | {nt} track{'s' if nt != 1 else ''}"
                        + (" | recording" if s.save else ""))
                elif s.running:
                    status_label.set_text(f"mode: live | {s.host} | connecting…")
                else:
                    status_label.set_text(
                        f"mode: live | {s.host} | disconnected ({st.frames} msgs)")
        elif v.mode == "Align":
            status_label.set_text(align_status())
        else:
            status_label.set_text(f"mode: {v.mode.lower()}")
        snap_switch.set_value(v.ctrl.snap_enabled)  # no-op when already equal
        select_count_label.set_text(
            f"{len(v.ctrl.selection)} selected" if v.mode == "Edit" else "")
        # Properties is enabled for a single selection (any kind); a multi-zone
        # event-zone selection routes to the bulk editor (ROADMAP Item 26).
        properties_btn.set_enabled(
            len(v.ctrl.selection) == 1
            or (v.draw_kind_name == "Event Zone" and len(v.ctrl.selection) > 1))
        zones = v.active_zones()
        move_station_btn.set_enabled(
            v.mode == "Edit" and v.draw_kind_name == "Event Zone"
            and len(v.ctrl.selection) == 1 and 0 <= v.ctrl.selected < len(zones)
            and attached_centerline_for(zones[v.ctrl.selected]) is not None)
        # Align (Item 40, reframed 2026-07-11): Commit whenever the authored
        # alignment proposes a real sensor move (calibration *or* a group
        # drag/rotate) and no commit is pending; Undo only while a commit
        # snapshot is held.
        align_commit_btn.set_enabled(v.align_dirty()
                                     and v.align_commit_snapshot is None)
        align_undo_btn.set_enabled(v.align_commit_snapshot is not None)
        refresh_zone_table()

    # -- zone table panel (synced with canvas selection) -----------------------

    def zone_rows() -> list[dict]:
        rows = []
        for si, s in enumerate(v.project.sensors):
            for zi, z in enumerate(s.event_zones):
                if is_placeholder(z):
                    continue
                cl = v.membership_for(z)
                rows.append({"key": f"{si}:{zi}", "sensor": f"S{si + 1}",
                             "on": "✓" if z.enable else "",
                             "name": z.zone_name or "",
                             "phase": z.phase_number or 0,
                             "output": z.output_number or 0,
                             "type": z.zone_type or 0,
                             "cl": v.centerline_label(v.centerlines.index(cl))
                             if cl else ""})
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

    def activate_sensor(si: int):
        """Make sensor `si` the active/edited one (Item 24): drives the unified
        Owner/Sensor dropdown off the source-of-truth field. Clears the General
        owner intent so the dropdown reflects the sensor."""
        if si == v.active_si and not v.assign_general:
            return
        cancel_rotate()  # retarget clears the controller's selection
        v.assign_general = False
        v.set_active_sensor(si)
        refresh_owner_sel()

    def edit_zone_on_sensor(si: int):
        """Table selection lands in Edit on Event Zone for sensor `si`."""
        if draw_kind_toggle.value != "Event Zone":
            draw_kind_toggle.set_value("Event Zone")  # retargets ctrl to zones
        activate_sensor(si)
        if v.mode != "Edit":
            tool.value = "Edit"  # on_change syncs the controller mode
        elif v.draw_kind_name != "Event Zone":
            v.set_draw_kind("Event Zone")

    def select_zone_key(key: str):
        """Plain row click: select just this one zone (mirrors a plain
        canvas click), overriding whatever the checkbox column had set."""
        si, zi = (int(x) for x in key.split(":"))
        edit_zone_on_sensor(si)
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
        edit_zone_on_sensor(si)
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
        # Item 25: the background is its own element now, so dim it directly
        # (the interactive_image overlay stays fully opaque/interactive).
        bg_img.style("opacity: 1" if on else "opacity: 0")

    def set_zone_panel_mode(mode: str):
        """Item 24 (§5): Auto/On/Off for the zone table. Auto shows it only when
        a zone kind is the active target; update_context_bar applies the rule."""
        v.zone_panel_mode = mode
        zone_panel_mode_btn.set_text(mode)
        update_context_bar()

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
            pw = v.canvas_to_world(p)
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
            v.cal_points.append(v.canvas_to_world(p))
            refresh_overlay()
            if len(v.cal_points) == 2:
                finish_two_point()
        elif button == 0 and v.mode == "Sensor":
            pw = v.canvas_to_world(p)
            si = v.sensor_at(pw)
            if si != -1:
                s = v.project.sensors[si]
                v.sensor_drag = {"si": si, "anchor": pw, "moved": False,
                                 "orig": (s.position_x, s.position_y)}
                if si != v.active_si:
                    activate_sensor(si)  # unified dropdown follows the pick
                    refresh_status()
        elif button == 0 and v.mode == "Align":
            pw = v.canvas_to_world(p)
            if v.align_rotate_armed:
                if v.rotate_pivot is None:
                    v.rotate_pivot = pw  # click 1: place the pivot
                else:
                    commit_align_rotate(v.rotate_pivot, v.rotate_angle)  # click 2
                refresh_overlay()
                refresh_status()
            elif v.align_placement is not None and v.ft_per_px() is not None:
                # Start a group drag (locked) / per-sensor nudge (unlocked). In
                # unlocked mode a click on a sensor selects which sensor's Cᵢ the
                # drag adjusts (reusing the Sensor-mode pick), then the whole
                # gesture edits the transform, never the sensor field.
                if not v.align_locked:
                    si = v.sensor_at(pw)
                    if si != -1 and si != v.active_si:
                        activate_sensor(si)
                v.align_drag = {"anchor": pw, "placement0": v.align_placement,
                                "calib0": dict(v.align_calib),
                                "slot": _active_slot(), "moved": False}
        elif button == 0 and v.template_placement_active():
            # Item 27: a template picked in Draw › Event Zone turns the click
            # into a template drop (was the standalone Template tool). With a
            # picked centerline it places along it on one click; otherwise the
            # ref-then-aim-upstream flow.
            if missing_placeholders(v.template, v.template_context):
                ui.notify("fill in the placement values first", type="warning")
                edit_placement_values(auto=False)
                return
            pw = v.canvas_to_world(p)
            if v.template_target_centerline() is not None:
                place_template(pw)  # curvilinear: one click, no aim needed
            elif v.template_ref is None:
                v.template_ref = pw
                refresh_overlay()
                refresh_status()
            else:
                place_template(pw)
        elif button == 0 and v.mode == "Draw":
            v.ctrl.mouse_down(v.canvas_to_world(p),
                              ctrl=bool(e.args.get("ctrlKey")))
            notify_ctrl_warning()
            refresh_overlay()
            refresh_status()
        elif button == 0 and v.mode == "Edit" and v.rotate_armed:
            pw = v.canvas_to_world(p)
            if v.rotate_pivot is None:
                v.rotate_pivot = pw  # click 1: place the pivot
            else:
                commit_rotate(v.rotate_pivot, v.rotate_angle)  # click 2
            refresh_overlay()
            refresh_status()
        elif button == 0 and v.mode == "Edit":
            pw = v.canvas_to_world(p)
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
        elif button == 0 and v.mode == "Centerline":
            v.centerline_ctrl.mouse_down(v.canvas_to_world(p))
            refresh_overlay()
            refresh_status()

    def on_move(e):
        p = (e.args["offsetX"], e.args["offsetY"])
        pos_label.set_text(v.describe(p))
        pw = v.canvas_to_world(p)
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
        elif v.align_drag is not None and e.args.get("buttons", 0) & 1:
            _align_drag_move(pw)  # marker-layer-only re-render (plan §6)
        elif v.mode == "Align" and v.align_rotate_armed:
            if v.rotate_pivot is not None:
                if v.rotate_ray is None:
                    v.rotate_ray = pw  # freeze the angle-measure reference ray
                else:
                    v.rotate_angle = geometry.rotation_angle_deg(
                        v.rotate_pivot, v.rotate_ray, pw)
                # live preview (2026-07-11 fix): markers + ghost sensors swing
                # with the aim through align_render_alignment(), so the rotate
                # is judged visually instead of committed blind
                refresh_marker_layer()
                refresh_status()
            refresh_overlay()
        elif v.ruler_active:
            if v.ruler_pending:
                v.ruler_end = pw
                refresh_overlay()
        elif v.template_placement_active():
            # cursor tracked from the first hover: with a centerline the
            # preview follows the mouse before any click (Item 27)
            v.template_cursor = pw
            refresh_overlay()
        elif v.mode == "Draw":
            dragging = bool(e.args.get("buttons", 0) & 1)
            v.ctrl.mouse_move(pw, dragging)
            # only redraw while something tracks the mouse — including the
            # Text Label draft ghost, which follows the cursor (Item 22)
            if v.ctrl.pending or dragging or v.ctrl.snap_enabled \
                    or v.draw_kind_name == "Text Label":
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
        elif v.mode == "Centerline":
            dragging = bool(e.args.get("buttons", 0) & 1)
            v.centerline_ctrl.mouse_move(pw, dragging)
            if dragging:
                refresh_overlay()

    def on_up(e):
        v.drag_anchor = None
        p = (e.args["offsetX"], e.args["offsetY"])
        pw = v.canvas_to_world(p)
        if v.sensor_drag is not None:
            d, v.sensor_drag = v.sensor_drag, None
            if not d["moved"]:
                sensor_properties(d["si"])
        elif v.align_drag is not None:
            v.align_drag = None
            _push_live_alignment()  # new live frames adopt the seated transform
            refresh_marker_layer()
            refresh_status()
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
            v.sync_centerline_labels()  # name label follows the far end (Item 22)
            update_event_cl_options()  # a new datum may now be pickable (Item 27)
            refresh_overlay()
            refresh_status()

    def on_dblclick(e):
        # the two mousedowns already selected the zone under the cursor
        if v.mode == "Edit":
            open_properties()
        elif v.mode == "Draw" and not v.template_placement_active() \
                and v.ctrl.finish_polygon():
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
    # ROADMAP Item 24: only Draw/Edit are top-level tools now (Background stays
    # click-only). Centerline (c) and Sensor (s) joined the Draw sub-kinds, so
    # their keys moved into DRAW_SUBTYPE_KEYS. `t` (Template) is retired — Item
    # 27 folded template placement into Draw › Event Zone (pick a template in
    # the Event-Zone bar, reachable via `z`), so it needs no tool key.
    TOOL_KEYS = {"d": "Draw", "e": "Edit"}
    DRAW_SUBTYPE_KEYS = {"z": "Event Zone", "l": "Lineal", "i": "Ignore Zone",
                         "a": "Text Label", "c": "Centerline", "s": "Sensor"}

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
            open_properties()
            return
        if name == "Escape" and v.rotate_armed:
            cancel_rotate()
            refresh_overlay()
            refresh_status()
            return
        if name == "Escape" and v.align_rotate_armed:
            cancel_align_rotate()
            refresh_overlay()
            refresh_status()
            return
        if name == "Escape" and v.template_placement_active() \
                and v.template_ref is not None:
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
            v.sync_centerline_labels()  # delete/undo may move the far end (Item 22)
            update_event_cl_options()  # a deleted datum drops from the picker
            refresh_overlay()
            refresh_status()
        elif v.mode == "Sensor" and name in ARROWS:
            nudge_sensor(*ARROWS[name])
        elif v.mode == "Sensor" and name in ("Delete", "x"):
            delete_sensor()

    # Re-entrancy guard: refresh_owner_sel() sets the dropdown programmatically,
    # which fires its on_change; the lock makes change_owner ignore that echo so
    # a mode-driven rebuild can't flip assign_general (Item 24, §8).
    _owner_sel_lock = [False]

    # ROADMAP Item 24: Sensor and Centerline are Draw sub-kinds, not top-level
    # tools, so the effective mode the state machine branches on is derived from
    # the tool toggle + Draw sub-kind by the module-level effective_mode().
    def _enter_mode(new_mode: str):
        """Apply an effective-mode transition: sync the controller mode and run
        the same teardown change_tool used to do (exit the ruler, clear template
        preview, end a centerline drag, cancel a rotate, drop the marquee)."""
        old_mode = v.mode
        # Leaving Align (Item 40): bake the authored transform into the overlay
        # sources so Replay/Live keep it, and end any in-flight align gesture.
        if old_mode == "Align" and new_mode != "Align":
            cancel_align_rotate()
            v.align_drag = None
            _persist_align_to_sources()
        v.mode = new_mode
        v.ctrl.set_mode("edit" if new_mode == "Edit" else "draw")
        # Selecting any tool / sub-kind exits the ruler overlay (owner's call):
        # it captures clicks regardless of the active tool, so leaving it on
        # would block the newly picked tool until explicitly toggled off.
        if v.ruler_active:
            set_ruler_active(False)
        # Any mode/sub-kind transition drops a pending template drop (Item 27:
        # Template is a mode of Event Zone now, not its own effective mode, so
        # there's no mode to preserve it across).
        v.template_ref = None
        v.template_cursor = None
        if new_mode != "Centerline":
            v.centerline_ctrl.end_drag()
        if new_mode != "Edit":
            cancel_rotate()
        v.marquee_anchor = None
        v.marquee_cursor = None
        # Item 40, owner fix 2026-07-11: the overlay persists — still playing —
        # across every non-overlay mode, so Draw/Edit keep the animated tracks
        # (marker_source() renders them there; the caller's
        # refresh_marker_layer picks that up). Only choosing a *different*
        # Overlay source stops the current one: entering Record/Live/Align
        # pauses the replay transport, and entering Record/Replay tears down
        # the live session (Live↔Align keeps it running, as before). Leaving
        # Record just stops its status poll — an in-progress capture keeps
        # running (close ≠ stop, same as the old dialog-only Record).
        if new_mode in ("Record", "Live", "Align"):
            _pause_replay()
        if new_mode in ("Record", "Replay"):
            _stop_live()
        if new_mode == "Align":
            enter_align()  # seed the group placement + route the live feed
        record_status_timer.active = (new_mode == "Record")

    def change_tool(e):
        kind = draw_kind_toggle.value
        _enter_mode(effective_mode(e.value, kind, overlay_kind_toggle.value))
        update_context_bar()
        refresh_overlay()
        refresh_marker_layer()  # re-route the marker painter (marker_source)
        refresh_status()

    def change_draw_kind(e):
        cancel_rotate()  # retarget clears the controller's selection
        kind = e.value
        _enter_mode(effective_mode(tool.value, kind, overlay_kind_toggle.value))
        if kind not in MODE_SUBKINDS:
            # A real drawing kind: retarget the controller to its element list
            # (also what Edit then operates on). Centerline/Sensor aren't
            # controller kinds, so draw_kind_name keeps its last drawing value.
            v.set_draw_kind(kind)
        update_context_bar()  # owner options / zone panel key off mode + kind
        refresh_overlay()
        refresh_status()

    def change_overlay_kind(e):
        """Overlay sub-kind toggle (ROADMAP Item 37): Record/Replay/Live are
        siblings under the one "Overlay" tool now, so switching between them
        works exactly like change_draw_kind switching Draw sub-kinds."""
        _enter_mode(effective_mode(tool.value, draw_kind_toggle.value, e.value))
        update_context_bar()
        refresh_overlay()
        refresh_marker_layer()
        refresh_status()

    _OWNER_BAND_TEXT = {Owner.GENERAL: "→ both files",
                        Owner.FILE1: "→ S1/2 (_1_2)",
                        Owner.FILE2: "→ S3/4 (_3_4)"}

    def _general_ok() -> bool:
        return general_offered(v.mode, v.draw_kind_name)

    def effective_owner() -> Owner:
        return resolve_owner(v.assign_general, v.active_si, _general_ok())

    def update_owner_hint():
        owner_hint_label.set_text(_OWNER_BAND_TEXT[effective_owner()])

    def owner_sel_options() -> dict:
        opts: dict = {}
        if _general_ok():
            opts[_GENERAL_KEY] = "General"
        for i in range(len(v.project.sensors)):
            opts[i] = f"S{i + 1}"
        return opts

    def owner_sel_value():
        return _GENERAL_KEY if (_general_ok() and v.assign_general) else v.active_si

    def refresh_owner_sel():
        """Rebuild the unified Owner/Sensor dropdown's options + value from the
        source-of-truth fields (active_si + assign_general). Guarded so the
        programmatic set_options doesn't re-enter change_owner (§8)."""
        _owner_sel_lock[0] = True
        owner_sel.set_options(owner_sel_options(), value=owner_sel_value())
        _owner_sel_lock[0] = False

    def change_owner(e):
        """User pick on the unified Owner/Sensor dropdown (Item 24, §3.3): one
        widget drives both the active sensor and the General/sensor owner of
        new owned annotations. General leaves active_si untouched so a later
        zone kind still has a valid sensor; picking a sensor clears General."""
        if _owner_sel_lock[0]:
            return
        val = e.value
        if val is None:
            return
        if val == _GENERAL_KEY:
            if v.assign_general:
                return
            v.assign_general = True
        else:
            if val == v.active_si and not v.assign_general:
                return
            v.assign_general = False
            if val != v.active_si:
                cancel_rotate()  # retarget clears the controller's selection
                v.set_active_sensor(val)
        if v.mode == "Centerline":
            v.centerline_ctrl.owner = v.current_owner()
            v.sync_centerline_labels()
        refresh_owner_sel()  # General may have just become (un)offered
        update_owner_hint()
        refresh_overlay()
        refresh_status()
        refresh_zone_table()  # active-sensor change rescopes table highlighting

    def read_label_draft(*_):
        """Draw-mode editor bar -> v.label_draft (ROADMAP Item 22 follow-up):
        a click in Text Label draw mode places a copy of this. Redraws so the
        cursor preview tracks the edited text/styling."""
        d = v.label_draft
        d.text = label_draft_text.value or ""
        d.font_size = int(label_draft_size.value or 12)
        d.rotation_angle = float(label_draft_rot.value or 0.0)
        d.textcolor_red, d.textcolor_green, d.textcolor_blue = \
            _hex_to_rgb(label_draft_color.value)
        d.font_bold = int(label_draft_bold.value)
        d.font_italic = int(label_draft_italic.value)
        d.font_underline = int(label_draft_underline.value)
        refresh_overlay()

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

    def _zone_kind_active() -> bool:
        """A zone kind is the active target (Item 24, §5) — Auto shows the zone
        table exactly then. Edit reads draw_kind_name (the last-targeted kind)."""
        return v.mode in ("Draw", "Edit") and \
            v.draw_kind_name in ("Event Zone", "Ignore Zone")

    # -- replay (ROADMAP Item 30) --------------------------------------------
    # Guards a programmatic scrubber set (in set_replay_frame) so it doesn't
    # re-enter on_replay_scrub, the same pattern as _owner_sel_lock above.
    _replay_scrub_lock = [False]

    def refresh_marker_layer():
        """Rewrite the shared track-marker layer (plan §4) from whichever
        painter marker_source() picks: the Overlay sub-modes render their own,
        and every non-overlay mode keeps a running live feed or loaded
        recording visible — Item 40's relaxed read-only invariant (owner fix
        2026-07-11), so the overlay persists over Draw/Edit instead of
        clearing the moment those modes are entered. Called on every zoom/pan
        (via apply_transform) so marker sizes track the zoom, and on each
        replay/live timer tick / scrub."""
        src = marker_source(
            v.mode, v.replay is not None,
            v.live_session is not None and v.live_session.running)
        if src == "replay":
            replay_layer.content = v.replay_marker_svg()
        elif src == "live":
            replay_layer.content = v.live_marker_svg()
        elif src == "align":
            replay_layer.content = v.align_marker_svg()
        else:
            replay_layer.content = ""

    def _set_play_icon():
        replay_play_btn.props(
            f"icon={'pause' if v.replay_playing else 'play_arrow'}")

    def _pause_replay():
        if v.replay_playing:
            v.replay_playing = False
        replay_timer.active = False
        _set_play_icon()

    def set_replay_frame(i, *, from_slider=False):
        """Jump to frame *i* (clamped): the single seam every transport control
        and the timer route through, so the scrubber, marker layer, and status
        line stay in lockstep."""
        rec = v.replay
        if rec is None or not rec.frames:
            return
        i = max(0, min(int(i), len(rec.frames) - 1))
        v.replay_frame = i
        v.replay_pos = float(i)
        if not from_slider:
            _replay_scrub_lock[0] = True
            replay_slider.value = i
            _replay_scrub_lock[0] = False
        refresh_marker_layer()
        refresh_status()

    def replay_tick():
        """10 fps cadence (plan §6): advance replay_pos by the speed multiplier
        so sub-1x speeds still animate; stop (don't loop) at the last frame."""
        rec = v.replay
        if rec is None or not v.replay_playing:
            return
        v.replay_pos += v.replay_speed
        frame = int(v.replay_pos)
        if frame >= len(rec.frames) - 1:
            set_replay_frame(len(rec.frames) - 1)
            _pause_replay()
            return
        set_replay_frame(frame)

    def toggle_replay_play():
        if v.replay is None:
            ui.notify("load a recording first (video icon)", type="warning")
            return
        if v.replay_playing:
            _pause_replay()
            return
        if v.replay_frame >= len(v.replay.frames) - 1:
            set_replay_frame(0)  # replay from the top when parked at the end
        v.replay_playing = True
        replay_timer.active = True
        _set_play_icon()

    def replay_step(delta):
        if v.replay is None:
            return
        _pause_replay()
        set_replay_frame(v.replay_frame + delta)

    def on_replay_scrub(e):
        if _replay_scrub_lock[0]:
            return
        _pause_replay()  # scrubbing takes manual control
        set_replay_frame(int(e.value or 0), from_slider=True)

    def change_replay_speed(e):
        try:
            v.replay_speed = float(e.value)
        except (TypeError, ValueError):
            v.replay_speed = 1.0

    def toggle_replay_labels(e):
        v.replay_labels = bool(e.value)
        refresh_marker_layer()

    def toggle_fused_view(e):
        """Raw↔fused toggle (ROADMAP Item 43): flip the Replay markers between
        the raw per-sensor points and the Item 42 fused tracks (one marker/id
        per real vehicle). Fusion over a whole recording is the expensive step,
        so compute + cache it here on the switch-on (with a note), not on the
        render tick; a stitched/low-confidence summary lands in the status."""
        v.fused_view = bool(e.value)
        if v.fused_view and v.replay is not None:
            res = v.ensure_fusion()
            if res is not None:
                n_fused = sum(1 for t in res.tracks if t.kind != "single")
                note = (f"fused {len(res.id_of)} raw tracks → "
                        f"{len(res.tracks)} ({n_fused} stitched/merged)")
                if res.low_confidence:
                    note += " — low-confidence (uncalibrated)"
                ui.notify(note)
        refresh_marker_layer()
        refresh_status()

    def recording_files() -> dict:
        """EVO recordings discoverable near the loaded project — the site
        folder and its `recordings/` subfolder (Item 28's file convention).
        Keyed by absolute path, valued by filename for the picker."""
        found: dict[str, str] = {}
        if v.source:
            for root in (v.source.parent, v.source.parent / "recordings"):
                try:
                    for pattern in ("*EVO*.txt.gz", "*EVO*.txt"):
                        for f in sorted(root.glob(pattern)):
                            found[str(f)] = f.name
                except OSError:
                    pass
        return found

    def _active_record_session() -> RecordingSession | None:
        """The session the consolidated status line reports for Record mode
        (ROADMAP Item 37): whichever host is actively running, else the most
        recently started one. Mirrors how the Live/Replay status branches
        already summarize a single "current" thing."""
        running = [s for s in v.record_sessions.values() if s.running]
        if running:
            return running[0]
        return next(reversed(v.record_sessions.values()), None)

    def set_recording(rec: Recording, path: Path):
        """Adopt a freshly loaded Recording: reset transport state and size the
        scrubber to its frame count. Also switches the Overlay sub-kind to
        Replay (ROADMAP Item 37) so the transport controls and status line
        are already showing it — a no-op if already there, and how "Load into
        Replay" from the Record panel now lands the user in Replay."""
        tool.value = "Overlay"
        overlay_kind_toggle.set_value("Replay")
        v.replay = rec
        v.replay_path = path
        v.replay_playing = False
        v.replay_frame = 0
        v.replay_pos = 0.0
        # A new recording supersedes any authored alignment (Item 40): reseed
        # from this recording's own Z; fit / anchor next time Align is entered.
        v.align_placement = None
        v.align_calib = {}
        v.align_calibration = None
        v.align_commit_snapshot = None
        v.align_base = None
        # ...and any cached fused view (Item 43): recomputed for this recording
        # on the next fused-view render (id() can be reused after GC, so don't
        # lean on the key alone).
        v._fusion = None
        v._fusion_frames = ()
        v._fusion_key = None
        replay_timer.active = False
        n = len(rec.frames)
        _replay_scrub_lock[0] = True
        replay_slider.props(f"max={max(n - 1, 1)}")
        replay_slider.value = 0
        _replay_scrub_lock[0] = False
        _set_play_icon()
        refresh_marker_layer()
        refresh_status()
        if rec.zone_fit is not None:
            align_note = (f"zone-aligned: {rec.zone_fit.rotation_deg:+.1f}°, "
                          f"×{rec.zone_fit.scale:.3f} over "
                          f"{rec.zone_fit.n_zones} zones")
        else:
            align_note = f"anchored to S{rec.sensor_index + 1}"
        ui.notify(f"loaded {n} frame{'s' if n != 1 else ''} from {path.name} "
                  f"({align_note})")

    def load_replay_recording(preset_path: Path | None = None,
                               preset_sensor: int | None = None):
        """Recording picker (plan §4): pick a file + the sensor its stream
        anchors to, load it through the Item 29 engine, and hand it to the
        transport. `preset_path`/`preset_sensor` let the Item 31 Record panel
        hand a just-finished capture straight in (plan §5's "hand a finished
        recording straight to the Item 30 playback loader")."""
        if v.ft_per_px() is None:
            ui.notify("calibrate the background first — playback needs the "
                      "meters-per-pixel scale", type="warning")
            return
        with ui.dialog() as dialog, ui.card().style("min-width: 480px"):
            ui.label("Load EVO recording").classes("text-lg")
            n_sensors = len(v.project.sensors)
            default_sensor = preset_sensor if preset_sensor is not None else v.active_si
            sensor_sel = ui.select(
                {i: f"S{i + 1}" for i in range(n_sensors)},
                value=min(default_sensor, n_sensors - 1),
                label="anchor sensor").classes("w-full").props("dense")
            with sensor_sel:
                ui.tooltip("the sensor this recording's stream belongs to — "
                           "its C; reference aligns to this sensor (plan §1c)")
            found = recording_files()
            if found:
                ui.select(found, label="found recordings",
                          on_change=lambda e: path_in.set_value(e.value)) \
                    .classes("w-full").props("dense clearable")
            path_in = ui.input(
                "path to recording .txt/.txt.gz",
                value=str(preset_path) if preset_path else "").classes("w-full")
            downs = ui.number("downsample (keep every Nth frame)", value=1,
                              min=1, precision=0).classes("w-full").props("dense")

            def apply():
                p = Path(path_in.value or "").expanduser()
                if not p.is_file():
                    ui.notify(f"not found: {p}", type="negative")
                    return
                try:
                    rec = load_recording(
                        v.project, p, sensor_index=int(sensor_sel.value),
                        downsample_rate=int(downs.value or 1))
                except Exception as exc:  # noqa: BLE001 — surface any parse error
                    ui.notify(f"failed to load {p.name}: {exc}", type="negative")
                    return
                dialog.close()
                set_recording(rec, p)

            with ui.row():
                ui.button("Load", on_click=apply)
                ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    def _host_auth_form() -> tuple:
        """Shared host/credentials form (ROADMAP Item 37): the known-hosts
        picker + host/user/password inputs Record and Live each used to
        re-declare independently (LIVE_OVERLAY_PLAN §4 called this "shared"
        but it was only a shared data source, `known_hosts()` — this is the
        first actual shared widget builder). Must be called inside the
        caller's own `ui.dialog()`/`ui.card()` context so the widgets land
        in the right place; returns the three inputs for the caller to read."""
        hosts = known_hosts()
        first_host = next(iter(hosts), "")
        default_user, default_pass = hosts.get(first_host, ("evo", "root"))

        def pick_known_host(host):
            u, p = hosts.get(host, ("evo", "root"))
            host_in.set_value(host)
            user_in.set_value(u)
            pass_in.set_value(p)

        host_in = ui.input("host (IP)", value=first_host) \
            .classes("w-full").props("dense")
        if hosts:
            # Known-hosts picker writes into host_in, mirroring the "found
            # recordings" select's relationship to path_in in the Replay
            # loader above.
            ui.select({h: h for h in hosts}, label="known hosts",
                      on_change=lambda e: pick_known_host(e.value)) \
                .classes("w-full").props("dense clearable")
        user_in = ui.input("username", value=default_user) \
            .classes("w-full").props("dense")
        pass_in = ui.input("password", value=default_pass, password=True) \
            .classes("w-full").props("dense")
        return host_in, user_in, pass_in

    def open_record_panel():
        """Record panel (ROADMAP Item 31, plan §5; folded under Overlay ›
        Record by Item 37): host/credentials form, start/stop over the
        existing evo_recorder websocket logic (now capture/recorder.py), live
        frame-count status, and a one-click hand-off of the finished file
        into the Item 30 loader above. The session lives on
        `v.record_sessions` (keyed by host), not the dialog, so reopening the
        panel finds an in-progress or just-finished capture instead of
        losing track of it."""
        with ui.dialog() as dialog, ui.card().style("min-width: 420px"):
            ui.label("Record EVO capture").classes("text-lg")
            host_in, user_in, pass_in = _host_auth_form()

            status_label = ui.label("idle").classes("font-mono text-sm")

            def current_session() -> RecordingSession | None:
                return v.record_sessions.get(host_in.value)

            def refresh_record_status():
                s = current_session()
                if s is None:
                    status_label.text = "idle"
                    start_btn.set_visibility(True)
                    stop_btn.set_visibility(False)
                    load_btn.set_visibility(False)
                    return
                st = s.status
                if st.error:
                    status_label.text = f"error: {st.error}"
                elif st.connected:
                    status_label.text = f"recording — {st.frames} frames"
                elif s.running:
                    status_label.text = "connecting…"
                elif st.stopped:
                    name = st.path.name if st.path else "?"
                    status_label.text = f"stopped — {st.frames} frames → {name}"
                else:
                    status_label.text = "idle"
                start_btn.set_visibility(not s.running)
                stop_btn.set_visibility(s.running)
                load_btn.set_visibility(
                    st.path is not None and st.frames > 0 and not s.running)

            def start():
                host = host_in.value
                if not host:
                    ui.notify("enter a host", type="warning")
                    return
                existing = v.record_sessions.get(host)
                if existing is not None and existing.running:
                    ui.notify("already recording", type="warning")
                    return
                out_dir = v.source.parent / "recordings"  # plan §5 file convention
                session = RecordingSession(
                    host, user_in.value or "evo", pass_in.value or "root", out_dir)
                v.record_sessions[host] = session
                session.start()
                refresh_record_status()

            async def stop():
                s = current_session()
                if s is None:
                    return
                await s.stop()
                refresh_record_status()

            def load_into_replay():
                s = current_session()
                if s is None or s.status.path is None:
                    return
                dialog.close()
                record_timer.active = False
                load_replay_recording(preset_path=s.status.path)

            with ui.row():
                start_btn = ui.button(
                    "Start", icon="fiber_manual_record", color="red",
                    on_click=start).props("dense")
                stop_btn = ui.button(
                    "Stop", icon="stop", on_click=stop).props("dense")
                load_btn = ui.button(
                    "Load into Replay", icon="video_file",
                    on_click=load_into_replay).props("dense")
            ui.button("Close", on_click=dialog.close).props("flat dense")

            # Polls session.status while the dialog is open; the session
            # itself keeps running (on the server's own loop) if the dialog
            # is closed without Stop — same "close ≠ stop" model as leaving
            # evo_recorder.py running in a terminal.
            record_timer = ui.timer(0.5, refresh_record_status)
            dialog.on("hide", lambda: setattr(record_timer, "active", False))
            dialog.on("show", lambda: setattr(record_timer, "active", True))

        refresh_record_status()
        dialog.open()

    # -- live overlay (ROADMAP Item 35, plan §§3-5) --------------------------
    # Wires the Item 34 feed-tap → the Item 33 streaming aligner → the Item 30
    # marker layer: a subscribed callback runs the aligner on every captured
    # message (lossless, on the capture task) and overwrites the single
    # `v.live_frame` slot; a fixed-cadence timer reads that slot and rewrites
    # only the marker layer (drop-to-latest, so socket rate never floods the
    # redraw — plan §3). All on one thread (the server loop), so the slot needs
    # no lock between the callback and the timer.

    def live_tick():
        """10 fps cadence (plan §3/§5): render the latest slot frame onto the
        marker layer and refresh the status line. If the connection has errored
        or ended, stop the timer — the overlay then clears itself once the slot
        goes stale (plan §5's error/disconnect surfacing)."""
        s = v.live_session
        if s is not None and (s.status.error or (not s.running and s.status.stopped)):
            live_timer.active = False
        refresh_marker_layer()
        refresh_status()

    def _stop_live():
        """Tear down the live overlay (plan §4): stop the timer, unsubscribe the
        aligner immediately (so no more frames land in the slot), and cancel the
        capture task. Sync entry — the socket stop is async, so it's scheduled
        on the running loop. Idempotent, so leaving Live from any path is safe."""
        live_timer.active = False
        s = v.live_session
        if s is not None:
            if v.live_cb is not None:
                s.unsubscribe(v.live_cb)
            if s.running:
                asyncio.create_task(s.stop())
        v.live_session = None
        v.live_aligner = None
        v.live_cb = None
        v.live_frame = None

    def open_live_connect():
        """Live connect dialog (plan §4): built from the same `_host_auth_form`
        as the Record panel (ROADMAP Item 37) plus the anchor-sensor pick the
        Replay loader uses, and an optional record-to-disk toggle (the
        superset behavior — a RecordingSession with save=True both overlays and
        captures, plan §1). On connect it subscribes an aligner-driven callback
        to the session's message stream and starts the overlay timer."""
        if v.ft_per_px() is None:
            ui.notify("calibrate the background first — the live overlay needs "
                      "the meters-per-pixel scale", type="warning")
            return
        if v.live_session is not None and v.live_session.running:
            ui.notify("already connected — Stop first", type="warning")
            return
        with ui.dialog() as dialog, ui.card().style("min-width: 420px"):
            ui.label("Connect live EVO overlay").classes("text-lg")
            host_in, user_in, pass_in = _host_auth_form()
            n_sensors = len(v.project.sensors)
            sensor_sel = ui.select(
                {i: f"S{i + 1}" for i in range(n_sensors)},
                value=min(v.active_si, n_sensors - 1),
                label="anchor sensor").classes("w-full").props("dense")
            with sensor_sel:
                ui.tooltip("the sensor this host's stream belongs to — its C; "
                           "reference aligns to this sensor (plan §1c)")
            save_switch = ui.switch("also record to disk", value=False)
            with save_switch:
                ui.tooltip("keep a capture while overlaying (plan §1's superset "
                           "behavior); off = overlay only, nothing written")

            def connect():
                host = host_in.value
                if not host:
                    ui.notify("enter a host", type="warning")
                    return
                out_dir = v.source.parent / "recordings"  # plan §5 convention
                session = RecordingSession(
                    host, user_in.value or "evo", pass_in.value or "root",
                    out_dir, save=bool(save_switch.value))
                try:
                    aligner = LiveAligner(v.project, sensor_index=int(sensor_sel.value))
                except Exception as exc:  # noqa: BLE001 — bad sensor, surface it
                    ui.notify(f"cannot align: {exc}", type="negative")
                    return

                def on_message(msg: str) -> None:
                    # Runs on the capture task (plan §1/§3): pure aligner + one
                    # slot write, so it can't stall the socket. The GUI stamps
                    # wall-clock time since a live message carries none (plan §2).
                    frame = aligner.feed(
                        msg, t=datetime.now().strftime("%H:%M:%S.%f")[:-3])
                    if frame is not None:
                        v.live_frame = (frame, time.monotonic())
                        # Retain recent frames so Align › Auto-calibrate has
                        # volume on a live overlay (Item 40); bounded deque.
                        v.live_history.append(frame)

                session.subscribe(on_message)
                v.live_session = session
                v.live_aligner = aligner
                v.live_cb = on_message
                v.live_frame = None
                v.live_history.clear()  # fresh buffer per connection (Item 40)
                session.start()
                live_timer.active = True
                dialog.close()
                ui.notify(f"connecting to {host} (anchored to "
                          f"S{int(sensor_sel.value) + 1})")
                refresh_status()

            with ui.row():
                ui.button("Connect", icon="sensors", on_click=connect)
                ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    async def live_stop():
        """Explicit Stop from the Live toolbar: disconnect but stay in Live mode
        (so the status line reports the stop and the user can reconnect)."""
        s = v.live_session
        if s is not None and v.live_cb is not None:
            s.unsubscribe(v.live_cb)
        if s is not None:
            await s.stop()
        live_timer.active = False
        v.live_frame = None
        refresh_marker_layer()
        refresh_status()

    def toggle_live_labels(e):
        v.live_labels = bool(e.value)
        refresh_marker_layer()

    # -- interactive alignment (ROADMAP Item 40, CALIBRATION_ALIGNMENT_PLAN §4)
    # The Align sub-mode of Overlay relaxes the Replay/Live read-only invariant:
    # the marker overlay persists over a canvas whose sensor drag/rotate now
    # seats the *calibrated group* (G) as a rigid body, while Auto-calibrate
    # solves the locked per-sensor relationship {Cᵢ} underneath. Everything is
    # in-memory and reversible (plan §5a) until an explicit Commit folds {Cᵢ}
    # into the iprj sensors. Markers re-align live through v.current_alignment()
    # (Viewer.align_marker_svg), so a drag re-seats them with a marker-layer-only
    # rewrite — never the static SVG (the Item 20/30 performance lesson, §6).

    def _align_zones_anchor_ref():
        """The Z; zones + sensor anchor/reference of the active overlay source
        (live session first, else the loaded recording) — what build_alignment
        seeds the group placement G from."""
        if v.live_session is not None and v.live_aligner is not None:
            la = v.live_aligner
            return la.zones, la.anchor_ft, la.ref_m
        rec = v.replay
        if rec is not None:
            return rec.zones, rec.anchor_ft, rec.ref_m
        return (), None, (0.0, 0.0)

    def _align_calib_frames():
        """Frames Auto-calibrate solves over: the live rolling buffer when a
        live overlay is running (volume for the statistical fit), else the
        loaded recording's frames."""
        if v.live_session is not None:
            return list(v.live_history)
        return v.replay.frames if v.replay is not None else []

    def _seed_align_placement():
        """(Re)seed the group placement G from the current calibration: G is the
        zonefit refit over calibrated centroids when Z; exists, else the
        translation seed from the sensor anchor (plan §§1/3). Resets any manual
        drag/rotate override to the automatic fit.

        Also seeds the *baseline* mapping (once per authoring session): the
        uncalibrated automatic fit, i.e. the default stream→iprj mapping the
        sensors' stored placement implies. Ghosts and Commit measure against
        it; a commit re-bases it (see align_commit), so it is only filled in
        here when absent."""
        zones, anchor, ref = _align_zones_anchor_ref()
        if v.align_base is None:
            v.align_base = build_alignment(v.project, list(zones), None,
                                           anchor_ft=anchor, ref_m=ref)
        tr = build_alignment(v.project, list(zones), v.align_calibration,
                             anchor_ft=anchor, ref_m=ref)
        if tr is None:
            v.align_placement = None
            v.align_calib = {}
        else:
            v.align_placement = tr.placement
            v.align_calib = dict(tr.calib)

    def _push_live_alignment():
        """Route the live aligner through the authored transform so new live
        frames align through it too (plan §6 — one path, both replay and live).
        A no-op off a live session."""
        if v.live_aligner is not None:
            v.live_aligner.alignment = v.current_alignment()

    def _persist_align_to_sources():
        """On leaving Align, bake the authored transform into the overlay
        sources so Replay/Live keep it (plan §6): realign the loaded recording
        once (O(frames), not per drag tick) and set the live aligner's
        transform. A no-op when nothing was authored."""
        tr = v.current_alignment()
        if tr is None:
            return
        if v.replay is not None:
            v.replay = realign(v.replay, tr)
        _push_live_alignment()

    def _active_slot() -> int:
        """The stream slot (oid % 10) of the active project sensor — the target
        of an unlocked per-sensor nudge."""
        for slot, si in v.align_slot_map().items():
            if si == v.active_si:
                return slot
        return v.active_si

    def enter_align():
        """Entering Align (plan §4): seed the group placement if none is held
        yet, and route any live feed through the current transform. Requires a
        calibrated background (markers need the meters/pixel scale)."""
        if v.ft_per_px() is None:
            ui.notify("calibrate the background first — alignment needs the "
                      "meters-per-pixel scale", type="warning")
            return
        if v.align_placement is None:
            _seed_align_placement()
        _push_live_alignment()

    def align_auto_calibrate():
        """Run the Item 39 relational solver over the current overlay's frames,
        make the sensors agree (background-blind), and lock the result (plan §4).
        Refits G over the calibrated centroids and surfaces the per-sensor
        fit-quality (pair counts / residuals / flags, plan §7)."""
        if v.ft_per_px() is None:
            ui.notify("calibrate the background first", type="warning")
            return
        frames = _align_calib_frames()
        if len(frames) < 2:
            ui.notify("no frames yet — load a recording or let the live overlay "
                      "run a moment first", type="warning")
            return
        # Solve only over stream slots that map to project sensors (2026-07-11
        # fix): oid % 10 is just an id convention, so a stream can carry stray
        # slots (fused/transient ids) that are not sensors — previously those
        # were solved and reported as impossible sensors ("S5/S6 too few
        # pairs" on a 4-sensor site). reference=None lets the solver anchor on
        # the best-observed real sensor instead of a hard-wired slot 0.
        smap = v.align_slot_map()
        cal = calibrate(frames, reference=None, slots=set(smap) or None)
        if not cal.sensors:
            ui.notify("no sensors seen in the frames", type="warning")
            return
        v.align_calibration = cal
        v.align_commit_snapshot = None  # a new solve supersedes any prior commit
        _seed_align_placement()  # refit G over calibrated centroids; set {Cᵢ}
        _push_live_alignment()
        refresh_marker_layer()
        refresh_status()

        def slot_name(slot: int) -> str:
            si = smap.get(slot)
            return f"S{si + 1}" if si is not None else f"slot {slot}"

        ok = [s for s in cal.sensors if s.status in ("ok", "translation_only")]
        flagged = cal.flagged
        parts = [f"calibrated {len(ok)} sensor{'s' if len(ok) != 1 else ''} "
                 f"(ref {slot_name(cal.reference)})"]
        if flagged:
            parts.append(", ".join(
                f"{slot_name(s.sensor)}:{s.status}" for s in flagged))
        ui.notify(" — ".join(parts),
                  type="positive" if v.align_calib else "warning")

    def toggle_align_lock():
        """Locked (default): a drag moves the whole calibrated group (edits G).
        Unlocked: a drag nudges the active sensor's calibration Cᵢ (the rare
        hand-adjust path, plan §4)."""
        v.align_locked = not v.align_locked
        align_lock_btn.props(f"icon={'lock' if v.align_locked else 'lock_open'}")
        refresh_status()

    def start_align_rotate():
        if v.align_placement is None:
            ui.notify("nothing to rotate yet — load an overlay first",
                      type="warning")
            return
        v.align_rotate_armed = True
        v.rotate_pivot = None
        v.rotate_ray = None
        v.rotate_angle = 0.0
        refresh_status()

    def cancel_align_rotate():
        if not v.align_rotate_armed:
            return
        v.align_rotate_armed = False
        v.rotate_pivot = None
        v.rotate_ray = None
        v.rotate_angle = 0.0

    def commit_align_rotate(pivot_px, angle):
        """Rotate the group about a world-px pivot (plan §4): edits G only, so
        the locked {Cᵢ} — the inter-sensor agreement — stays fixed."""
        fpp = v.ft_per_px()
        if fpp is None or v.align_placement is None:
            cancel_align_rotate()
            return
        pivot_ft = (pivot_px[0] * fpp, pivot_px[1] * fpp)
        v.align_placement = rotated_about(v.align_placement, pivot_ft, angle)
        cancel_align_rotate()
        _push_live_alignment()
        refresh_marker_layer()
        refresh_status()

    def _align_drag_move(pw):
        """Live drag: locked → translate G (whole group); unlocked → nudge the
        active sensor's Cᵢ position (plan §4). Recomputed from the drag-start
        snapshot each move so it can't accumulate rounding."""
        d = v.align_drag
        fpp = v.ft_per_px()
        if fpp is None:
            return
        dx_ft = (pw[0] - d["anchor"][0]) * fpp
        dy_ft = (pw[1] - d["anchor"][1]) * fpp
        if math.hypot(dx_ft, dy_ft) > 0.1:
            d["moved"] = True
        if v.align_locked:
            v.align_placement = translated(d["placement0"], dx_ft, dy_ft)
        else:
            slot = d["slot"]
            base = d["calib0"].get(slot, IDENTITY)
            v.align_calib = dict(d["calib0"])
            v.align_calib[slot] = nudged_delta(base, d["placement0"], (dx_ft, dy_ft))
        refresh_marker_layer()
        refresh_status()

    async def align_commit():
        """Write the proposed sensor moves — the ghost positions — into the
        iprj sensors' azimuth + position (owner reframing, 2026-07-11: the
        whole authored alignment, calibration *and* group placement, reads as
        a sensor move; a pure group drag commits too). Confirmed, snapshotted
        for undo, and the baseline re-bases to the committed transform so the
        ghosts collapse onto the moved sensors and the overlay doesn't jump."""
        tr = v.current_alignment()
        base = v.align_base
        if tr is None or base is None:
            ui.notify("nothing to commit — load an overlay and move the group "
                      "or run Auto-calibrate first", type="warning")
            return
        updates = commit_alignment(v.project, tr, base,
                                   slot_to_sensor=v.align_slot_map())
        if not updates:
            ui.notify("nothing to commit — the sensors already sit where the "
                      "alignment puts them", type="warning")
            return
        fpp = v.ft_per_px()
        with ui.dialog() as dlg, ui.card():
            ui.label("Commit sensor moves").classes("text-lg")
            ui.label("Moves each sensor to its ghost position (reversible "
                     "with the undo button):").classes("text-sm text-gray-400")
            for si, (az, px) in sorted(updates.items()):
                old = v.project.sensors[si]
                moved_ft = (math.hypot(px[0] - old.position_x,
                                       px[1] - old.position_y) * fpp
                            if fpp is not None else 0.0)
                ui.label(f"S{si + 1}:  azimuth {old.azimuth_angle or 0.0:.2f}° "
                         f"→ {az:.2f}°   ·   moved {moved_ft:.1f} ft") \
                    .classes("font-mono text-sm")
            with ui.row():
                ui.button("Commit", on_click=lambda: dlg.submit("commit"))
                ui.button("Cancel", on_click=lambda: dlg.submit("cancel"))
        if await dlg != "commit":
            return
        snap = {}
        for si in updates:
            s = v.project.sensors[si]
            snap[si] = (s.azimuth_angle, s.position_x, s.position_y)
        v.align_commit_snapshot = {"sensors": snap, "base": base}
        for si, (az, px) in updates.items():
            s = v.project.sensors[si]
            s.azimuth_angle = az
            s.position_x, s.position_y = px
        # Re-base: the committed transform is now the mapping consistent with
        # the (just-moved) sensors, so ghosts sit on the sensors again and a
        # later commit can't double-apply the same move.
        v.align_base = tr
        refresh_overlay()  # the sensor icons moved to their committed placement
        refresh_marker_layer()
        refresh_status()
        ui.notify(
            f"moved {len(updates)} sensor{'s' if len(updates) != 1 else ''} — "
            "Save to keep it; undo button to revert", type="positive")

    def align_undo_commit():
        snap = v.align_commit_snapshot
        if not snap:
            return
        for si, (az, x, y) in snap["sensors"].items():
            s = v.project.sensors[si]
            s.azimuth_angle = az
            s.position_x = x
            s.position_y = y
        v.align_base = snap["base"]  # ghosts measure against the old placement again
        v.align_commit_snapshot = None
        refresh_overlay()
        refresh_marker_layer()
        refresh_status()
        ui.notify("reverted the sensor-move commit")

    def align_reset():
        """Discard the authored alignment — back to the automatic fit, no
        calibration (plan §5a reversibility). Starts a fresh authoring session
        against the sensors' current placement, so the baseline reseeds too."""
        v.align_calibration = None
        v.align_calib = {}
        v.align_commit_snapshot = None
        v.align_base = None
        _seed_align_placement()
        _push_live_alignment()
        refresh_marker_layer()
        refresh_status()
        ui.notify("alignment reset to the automatic fit")

    def toggle_align_labels(e):
        v.align_labels = bool(e.value)
        refresh_marker_layer()

    def align_status() -> str:
        p = v.align_placement
        if p is None:
            return ("mode: align | load a recording (Replay) or connect Live, "
                    "then drag — ghost sensors and tracks move together over "
                    "the background")
        if v.align_rotate_armed:
            if v.rotate_pivot is None:
                return "mode: align rotate | click to place the pivot  [Esc cancels]"
            return (f"mode: align rotate | {v.rotate_angle:+.1f}° | "
                    "move to aim, click to commit  [Esc cancels]")
        lock = ("locked — drag moves the sensor group" if v.align_locked
                else f"UNLOCKED — drag nudges S{v.active_si + 1}")
        # the proposed sensor move, so "how much have I changed?" reads off
        # the status line as well as off the ghost leaders (2026-07-11)
        ghosts = v.align_ghosts()
        fpp = v.ft_per_px()
        if ghosts and fpp is not None:
            disp = max(math.hypot(g[0] - r[0], g[1] - r[1]) * fpp
                       for _, r, g, _ in ghosts)
            daz = max((abs(d) for *_, d in ghosts), default=0.0)
            move = (f"Δ {disp:.1f} ft, {daz:.1f}°" if disp >= 0.05 or daz >= 0.01
                    else "sensors unmoved")
        else:
            move = "sensors unmoved"
        cal = v.align_calibration
        if cal is None:
            calnote = "no calibration (Auto-calibrate to make sensors agree)"
        else:
            ok = [s for s in cal.sensors if s.status in ("ok", "translation_only")]
            res = [s.mean_residual_m for s in ok if s.mean_residual_m is not None]
            calnote = (f"calibrated {len(ok)} sensor"
                       f"{'s' if len(ok) != 1 else ''}"
                       + (f", ~{max(res):.1f} m residual" if res else "")
                       + (f", {len(cal.flagged)} flagged" if cal.flagged else ""))
        return f"mode: align | {lock} | {move} | {calnote}"

    def update_context_bar():
        """Row-2 context controls per tool + Draw sub-kind (ROADMAP Item 24;
        PHASE3_UI_PLAN §3): built once, shown/hidden by visibility rather than
        rebuilt, so widget state survives a switch. The unified Owner/Sensor
        dropdown's *options* also change with the sub-kind (General offered or
        not), so it is rebuilt here."""
        tool_is_draw = tool.value == "Draw"
        tool_is_overlay = tool.value == "Overlay"
        # Unified Owner/Sensor dropdown: everywhere but Background, Record,
        # Replay, and Live (all read-only, so they own nothing — Items 30/31/35).
        owns_nothing = ("Background", "Record", "Replay", "Live")
        owner_sel.set_visibility(v.mode not in owns_nothing)
        owner_hint_label.set_visibility(v.mode not in owns_nothing)
        refresh_owner_sel()
        update_owner_hint()
        # Draw sub-kind toggle + the per-sub-kind extras.
        draw_kind_toggle.set_visibility(tool_is_draw)
        # Overlay sub-kind toggle (ROADMAP Item 37): Record/Replay/Live.
        overlay_kind_toggle.set_visibility(tool_is_overlay)
        add_sensor_btn.set_visibility(v.mode == "Sensor")
        delete_sensor_btn.set_visibility(v.mode == "Sensor")
        centerline_sel.set_visibility(v.mode == "Centerline")
        add_centerline_btn.set_visibility(v.mode == "Centerline")
        centerline_name_in.set_visibility(v.mode == "Centerline")
        drafting = v.mode == "Draw" and v.draw_kind_name == "Text Label"
        for _w in label_draft_widgets:
            _w.set_visibility(drafting)
        # Edit context.
        select_count_label.set_visibility(v.mode == "Edit")
        properties_btn.set_visibility(v.mode == "Edit")
        rotate_btn.set_visibility(v.mode == "Edit")
        move_station_btn.set_visibility(v.mode == "Edit")
        delete_btn.set_visibility(v.mode == "Edit")
        # Background context.
        calibrate_size_btn.set_visibility(v.mode == "Background")
        upload_bg_btn.set_visibility(v.mode == "Background")
        # Template + CL controls (Item 27): folded into Draw › Event Zone. The
        # template picker and the CL dropdown live in the Event-Zone context;
        # the placement-values button only matters once a template is picked.
        # (The template-editor button lives on Row 1 and is always visible.)
        event_zone = v.mode == "Draw" and v.draw_kind_name == "Event Zone"
        template_sel.set_visibility(event_zone)
        event_cl_sel.set_visibility(event_zone)
        template_values_btn.set_visibility(event_zone and v.template is not None)
        # Record entry (Item 31, folded under Overlay by Item 37): shown only
        # in the Record sub-mode.
        for _cw in record_widgets:
            _cw.set_visibility(v.mode == "Record")
        # Replay transport (Item 30): the whole cluster shows only in Replay.
        for _rw in replay_widgets:
            _rw.set_visibility(v.mode == "Replay")
        # Live overlay controls (Item 35): shown only in Live.
        for _lw in live_widgets:
            _lw.set_visibility(v.mode == "Live")
        # Interactive alignment controls (Item 40): shown only in Align.
        for _aw in align_widgets:
            _aw.set_visibility(v.mode == "Align")
        # Zone-table panel (Item 24, §5): Auto shows it only when a zone kind is
        # the active target; the three-state control itself is always on Row 2.
        zone_panel.set_visibility(
            v.zone_panel_mode == "On"
            or (v.zone_panel_mode == "Auto" and _zone_kind_active()))

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
        # Frame the background (not the whole oversized canvas) so load/fit
        # lands on the imagery, with the off-image margin reachable by panning.
        v.viewport.fit((v.image_w, v.image_h), tuple(size),
                       content_origin=(v.canvas_off_x, v.canvas_off_y))
        apply_transform()
        scale_label.set_text(status_scale())

    # -- layout ---------------------------------------------------------------
    # Full-height flex column (height-budget fix, 2026-07-08): pin the page body
    # to the viewport height and strip NiceGUI's default content padding/gap, so
    # the two toolbar rows + the status bar sit at their natural heights and the
    # canvas row (flex-1, below) absorbs exactly the leftover space. This
    # replaces the old `calc(100vh - 120px)` magic constant, which budgeted only
    # the *top* chrome and let the status bar overflow the window by ~one row on
    # every machine (the batch's height goal). Robust to font/DPI/mode changes —
    # no pixel constant to keep in sync with the toolbar heights.
    ui.query(".nicegui-content").style(
        "height: 100vh; padding: 0; gap: 0; overflow: hidden;")

    # Two-tier toolbar (PHASE3_UI_PLAN §3): row 1 is persistent chrome that
    # never depends on the active tool, so it never scrolls; row 2 is a
    # single context bar whose controls are built once and individually
    # shown/hidden per tool by update_context_bar() (visibility toggling,
    # not rebuilding, so selector state survives a tool switch).

    # ROADMAP Item 24 (ITEM23_TOOLBAR_PLAN §3.1): Row 1 groups controls by type
    # behind `|` separators — modes + always-on drawing tools left, the file
    # cluster (template-editor · folder · filename · save) right. The product
    # name is gone; the filename is a muted inline label beside the folder menu.
    with ui.row().classes("w-full items-center gap-2 px-2 no-wrap overflow-x-auto"):
        tool = ui.toggle(["Draw", "Edit", "Background", "Overlay"],
                         value="Edit", on_change=change_tool).props("dense")
        with tool:
            ui.tooltip("accelerators: d draw · e edit · space+drag / "
                       "middle-drag pans · Esc cancel (Sensor & Centerline are "
                       "Draw sub-kinds now). Overlay: Record/Replay/Live a "
                       "capture (Replay & Live are read-only).")
        ui.separator().props("vertical")
        # Always-on drawing tools (apply in every mode).
        snap_switch = ui.switch("snap", on_change=toggle_snap).props("dense")
        with snap_switch:
            ui.tooltip("vertex/midpoint snapping (g)")
        ruler_btn = ui.button(icon="straighten", on_click=toggle_ruler) \
            .props("flat dense")
        with ruler_btn:
            ui.tooltip("ruler (r) — measures distance in any tool, "
                       "independent of the active tool")
        with ui.button(icon="clear", on_click=clear_ruler) \
                .props("flat dense"):
            ui.tooltip("clear ruler")
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
        ui.space()
        ui.separator().props("vertical")
        # File cluster (right-justified): template-editor · folder · filename · save.
        with ui.button(icon="edit_square", on_click=open_template_editor) \
                .props("flat dense"):
            ui.tooltip("open the template editor (new tab)")
        with ui.button(icon="folder").props("flat dense"):
            folder_tip = ui.tooltip("file")
            with ui.menu():
                ui.menu_item("New…", on_click=new_project)
                ui.menu_item("Open…", on_click=open_existing)
                ui.menu_item("Open second sensor-pair file (overlay)…",
                             on_click=open_second_pair_file)
                ui.separator()
                ui.menu_item("Save", on_click=save)
                ui.menu_item("Save As…", on_click=save_as)
        _title = (f"{v.pair[0].name} + {v.pair[1].name}" if v.pair
                  else v.source.name)
        title_label = ui.label(_title) \
            .classes("text-sm text-gray-300 whitespace-nowrap")
        folder_tip.set_text(str(v.pair[0] if v.pair else v.source))
        with ui.button(icon="save", on_click=save).props("flat dense"):
            ui.tooltip("save (Ctrl-S)")

    with ui.row().classes("w-full items-center gap-2 px-2 no-wrap overflow-x-auto"):
        # Draw sub-kind toggle (Item 24): Sensor and Centerline joined Event
        # Zone / Ignore Zone / Lineal / Text Label as Draw sub-kinds.
        draw_kind_toggle = ui.toggle(
            ["Event Zone", "Ignore Zone", "Lineal", "Text Label",
             "Centerline", "Sensor"],
            value="Event Zone",
            on_change=change_draw_kind).props("dense")
        with draw_kind_toggle:
            ui.tooltip("draw sub-kind: z Event Zone · i Ignore Zone · l Lineal "
                       "· a Text Label · c Centerline · s Sensor — also picks "
                       "what Edit operates on")
        # Overlay sub-kind toggle (ROADMAP Item 37): Record/Replay/Live share
        # one top-level "Overlay" tool now; this picks which of the three is
        # active, the same way draw_kind_toggle picks the Draw sub-kind.
        overlay_kind_toggle = ui.toggle(
            ["Record", "Replay", "Live", "Align"],
            value="Replay",
            on_change=change_overlay_kind).props("dense")
        with overlay_kind_toggle:
            ui.tooltip("Record: capture a live EVO host to disk. Replay: play "
                       "back a saved recording (read-only). Live: overlay a "
                       "live stream in real time (read-only). Align: seat the "
                       "overlay onto the background — drag/rotate the calibrated "
                       "sensor group, Auto-calibrate, and commit to the iprj.")
        ui.separator().props("vertical")

        # Unified Owner/Sensor dropdown (Item 24, §3.3): replaces the active-
        # sensor selector *and* the General/Active-sensor toggle. Options are
        # General (where offered) + S1…Sn; General is suppressed for zone/sensor
        # sub-kinds. Rebuilt by update_context_bar() as the sub-kind changes.
        owner_sel = ui.select(
            owner_sel_options(), value=owner_sel_value(), label="owner",
            on_change=change_owner).classes("w-28").props("dense")
        with owner_sel:
            ui.tooltip("active sensor + owner of new lineals/labels/centerlines: "
                       "General = both files; a sensor = its file band "
                       "(S1/2 → _1_2, S3/4 → _3_4). General is hidden for zones "
                       "and sensor editing.")
        owner_hint_label = ui.label("").classes("text-white font-mono text-xs")
        add_sensor_btn = ui.button(icon="add_circle", on_click=add_sensor) \
            .props("flat dense")
        with add_sensor_btn:
            ui.tooltip("add a sensor at image center")
        delete_sensor_btn = ui.button(icon="delete", on_click=delete_sensor) \
            .props("flat dense")
        with delete_sensor_btn:
            ui.tooltip("delete active sensor (x / Del) — prompts to reassign "
                       "or delete its zones")

        # Text Label draw-time editor bar (ROADMAP Item 22 follow-up): the same
        # fields as the properties dialog, inline; a click places a copy of
        # this draft. Widgets write v.label_draft live via read_label_draft.
        d0 = v.label_draft
        label_draft_text = ui.input("label text", value=d0.text or "") \
            .classes("w-40").props("dense")
        with label_draft_text:
            ui.tooltip("text placed on the next click (Text Label draw mode)")
        label_draft_size = ui.number("size", value=d0.font_size or 12, min=1,
                                     precision=0).classes("w-16").props("dense")
        label_draft_rot = ui.number("rot°", value=d0.rotation_angle or 0.0,
                                    precision=1).classes("w-16").props("dense")
        label_draft_color = ui.color_input(
            "color", value="#%02x%02x%02x" % (d0.textcolor_red or 0,
                                              d0.textcolor_green or 0,
                                              d0.textcolor_blue or 0)) \
            .classes("w-28").props("dense")
        label_draft_bold = ui.checkbox("B", value=bool(d0.font_bold)).props("dense")
        label_draft_italic = ui.checkbox("I", value=bool(d0.font_italic)).props("dense")
        label_draft_underline = ui.checkbox("U", value=bool(d0.font_underline)).props("dense")
        label_draft_widgets = [label_draft_text, label_draft_size, label_draft_rot,
                               label_draft_color, label_draft_bold,
                               label_draft_italic, label_draft_underline]
        for _w in label_draft_widgets:
            _w.on_value_change(read_label_draft)

        select_count_label = ui.label("").classes("text-white font-mono")
        properties_btn = ui.button(icon="tune", on_click=lambda: open_properties()) \
            .props("flat dense")
        with properties_btn:
            ui.tooltip("properties (p / Enter / double-click) — zone or text "
                       "label, single selection only")
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

        # Item 27: Template folded into Draw › Event Zone. Pick a template to
        # drop it on click; leave it blank for plain free-draw event zones.
        template_sel = ui.select(template_files(), label="template",
                                 on_change=change_template) \
            .classes("w-48").props("dense clearable")
        with template_sel:
            ui.tooltip("approach template to drop on click (anchor at the stop "
                       "bar / LT-thru lane line); blank = free-draw an event "
                       "zone. Pick a centerline at right to place along it.")
        template_values_btn = ui.button(
            icon="edit_note", on_click=lambda: edit_placement_values(auto=False)) \
            .props("flat dense")
        with template_values_btn:
            ui.tooltip("placement values — direction, thru/LT phase, "
                       "Base Output")
        # (template-editor button moved to the Row-1 file cluster in Item 24)
        # One CL dropdown (Item 27) replacing the Item-19 follow-switch +
        # pick-select: it drives *every* event zone drawn here. Chosen ⇒ a
        # template places along it and a plain zone joins its membership group
        # (Item 26); blank ⇒ aim-upstream template placement / no membership.
        event_cl_sel = ui.select(
            {}, label="along CL", on_change=change_event_cl) \
            .classes("w-28").props("dense clearable")
        with event_cl_sel:
            ui.tooltip("centerline for the zones drawn here: a template places "
                       "along it and a drawn zone joins its group (Item 26); "
                       "blank = aim upstream / no group")

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
            ui.tooltip("name for this centerline (e.g. N_CL for the north "
                       "approach); shown in the pickers and saved as a label "
                       "at the far end")

        # Record panel (ROADMAP Item 31, its own Overlay sub-mode by Item 37):
        # capture straight from a live EVO host and hand the finished file
        # into the loader below. Shown only in Record mode.
        record_btn = ui.button(
            icon="fiber_manual_record", on_click=open_record_panel) \
            .props("flat dense").classes("text-red-5")
        with record_btn:
            ui.tooltip("record a live EVO capture (Record panel)")
        record_widgets = [record_btn]

        # Replay transport (ROADMAP Item 30): a load-recording picker plus
        # play/pause, frame-step, speed, a timeline scrubber, and an id-label
        # toggle. Shown only in Replay mode by update_context_bar().
        replay_load_btn = ui.button(
            icon="video_file", on_click=load_replay_recording).props("flat dense")
        with replay_load_btn:
            ui.tooltip("load an EVO recording to play back")
        replay_step_back_btn = ui.button(
            icon="skip_previous", on_click=lambda: replay_step(-1)).props("flat dense")
        with replay_step_back_btn:
            ui.tooltip("step back one frame")
        replay_play_btn = ui.button(
            icon="play_arrow", on_click=toggle_replay_play).props("flat dense")
        with replay_play_btn:
            ui.tooltip("play / pause")
        replay_step_fwd_btn = ui.button(
            icon="skip_next", on_click=lambda: replay_step(1)).props("flat dense")
        with replay_step_fwd_btn:
            ui.tooltip("step forward one frame")
        replay_speed_sel = ui.select(
            {0.5: "0.5×", 1.0: "1×", 2.0: "2×", 4.0: "4×"}, value=1.0,
            label="speed", on_change=change_replay_speed).classes("w-20").props("dense")
        with replay_speed_sel:
            ui.tooltip("playback speed (relative to the 10 fps base cadence)")
        replay_slider = ui.slider(
            min=0, max=1, value=0, on_change=on_replay_scrub) \
            .classes("w-64").props("dense label")
        with replay_slider:
            ui.tooltip("timeline — drag to scrub to any frame")
        replay_labels_switch = ui.switch(
            "ids", value=True, on_change=toggle_replay_labels).props("dense")
        with replay_labels_switch:
            ui.tooltip("show the abbreviated track id over each marker")
        # Raw↔fused toggle (ROADMAP Item 43): off = raw per-sensor points;
        # on = the Item 42 fused tracks (one marker/id per real vehicle,
        # cross-sensor dedup + within-sensor stitch). Replay/batch only — Live
        # stays raw (fusion is batch-only, FUSION_PLAN §5).
        fused_switch = ui.switch(
            "fused", value=False, on_change=toggle_fused_view).props("dense")
        with fused_switch:
            ui.tooltip("fuse the tracks: show one marker/id per real vehicle "
                       "(cross-sensor + stop/drop/resume stitched) instead of "
                       "raw per-sensor points")
        replay_widgets = [replay_load_btn, replay_step_back_btn,
                          replay_play_btn, replay_step_fwd_btn, replay_speed_sel,
                          replay_slider, replay_labels_switch, fused_switch]

        # Live overlay controls (ROADMAP Item 35): connect (built from the
        # same _host_auth_form as the Record panel) / stop, plus the id-label
        # toggle. No timeline or scrubber — Live is a live tail, not file
        # scrubbing (plan §4). Shown only in Live mode by update_context_bar().
        live_connect_btn = ui.button(
            icon="sensors", on_click=open_live_connect).props("flat dense")
        with live_connect_btn:
            ui.tooltip("connect to a live EVO host and overlay its tracks")
        live_stop_btn = ui.button(
            icon="stop", on_click=live_stop).props("flat dense").classes("text-red-5")
        with live_stop_btn:
            ui.tooltip("disconnect the live overlay")
        live_labels_switch = ui.switch(
            "ids", value=True, on_change=toggle_live_labels).props("dense")
        with live_labels_switch:
            ui.tooltip("show the abbreviated track id over each live marker")
        live_widgets = [live_connect_btn, live_stop_btn, live_labels_switch]

        # Interactive alignment controls (ROADMAP Item 40): Auto-calibrate makes
        # the sensors agree (the relational solver, §2); the lock toggle switches
        # a drag between moving the whole group (locked) and nudging one sensor's
        # calibration (unlocked); Rotate group is a 2-click group rotate; Commit
        # folds the calibration into the iprj sensors (§5); Undo reverts a
        # commit; Reset discards the authored alignment. Shown only in Align.
        align_calibrate_btn = ui.button(
            icon="auto_fix_high", on_click=align_auto_calibrate).props("flat dense")
        with align_calibrate_btn:
            ui.tooltip("Auto-calibrate — solve the per-sensor corrections that "
                       "make the sensors agree (needs vehicle traffic in the "
                       "recording / live buffer)")
        align_lock_btn = ui.button(
            icon="lock", on_click=toggle_align_lock).props("flat dense")
        with align_lock_btn:
            ui.tooltip("lock: drag moves the whole calibrated group · unlock: "
                       "drag nudges the active sensor's calibration")
        align_rotate_btn = ui.button(
            icon="rotate_right", on_click=start_align_rotate).props("flat dense")
        with align_rotate_btn:
            ui.tooltip("rotate the group: click a pivot, aim, click to commit "
                       "(Esc cancels)")
        align_reset_btn = ui.button(
            icon="restart_alt", on_click=align_reset).props("flat dense")
        with align_reset_btn:
            ui.tooltip("reset to the automatic fit (discards drags + calibration)")
        align_commit_btn = ui.button(
            icon="save_as", on_click=align_commit).props("flat dense")
        with align_commit_btn:
            ui.tooltip("commit the calibration into the iprj sensors' azimuth + "
                       "position (confirm + undo)")
        align_undo_btn = ui.button(
            icon="undo", on_click=align_undo_commit).props("flat dense")
        with align_undo_btn:
            ui.tooltip("undo the last calibration commit")
        align_labels_switch = ui.switch(
            "ids", value=True, on_change=toggle_align_labels).props("dense")
        with align_labels_switch:
            ui.tooltip("show the abbreviated track id over each marker")
        align_widgets = [align_calibrate_btn, align_lock_btn, align_rotate_btn,
                         align_reset_btn, align_commit_btn, align_undo_btn,
                         align_labels_switch]

        # Zone-table three-state control (Item 24, §5): right-justified at the
        # end of the context bar, directly above the table it governs.
        ui.space()
        ui.separator().props("vertical")
        zone_panel_mode_btn = ui.button(
            v.zone_panel_mode, icon="view_sidebar").props("flat dense")
        with zone_panel_mode_btn:
            ui.tooltip("zone table: Auto (only in a zone kind) · On · Off")
            with ui.menu():
                ui.menu_item("Auto", on_click=lambda: set_zone_panel_mode("Auto"))
                ui.menu_item("On", on_click=lambda: set_zone_panel_mode("On"))
                ui.menu_item("Off", on_click=lambda: set_zone_panel_mode("Off"))

    ui.keyboard(on_key=on_key)  # ignores keys typed into dialogs/inputs

    # flex-1 + min-h-0: this row grows to fill whatever the toolbars and status
    # bar leave, and min-height:0 lets it actually shrink so the status bar below
    # always stays on screen (height-budget fix).
    with ui.row().classes("w-full no-wrap gap-0 flex-1 min-h-0"):
        with ui.element("div").props("id=viewport").classes("grow overflow-hidden") \
                .style("height: 100%; position: relative; "
                       "background: #111; cursor: crosshair;"):
            # Item 25: `stage` is the oversized (2x each way) drawing surface;
            # pan/zoom transform it. The background is a static <img> centered
            # inside it via the canvas offset; the interactive_image is a
            # transparent, full-canvas overlay that owns the SVG and the mouse
            # events (offsetX/Y are canvas px, 1:1 with its natural size). Both
            # ride `stage`'s transform, so they pan/zoom together and objects
            # can be drawn/dragged into the off-image margin.
            stage = ui.element("div").style(
                f"position: absolute; top: 0; left: 0; "
                f"width: {v.canvas_w}px; height: {v.canvas_h}px; "
                f"transform-origin: 0 0;")
            with stage:
                bg_img = ui.image(v.image_file).style(
                    f"position: absolute; left: {v.canvas_off_x}px; "
                    f"top: {v.canvas_off_y}px; width: {v.image_w}px; "
                    f"height: {v.image_h}px; pointer-events: none;")
                # No source -> a transparent, bitmap-free overlay sized to the
                # whole canvas (its SVG viewBox comes from `size`); keeps the bg
                # bitmap at natural size instead of quadrupling it.
                ii = ui.interactive_image(
                    content=v.svg(), size=(v.canvas_w, v.canvas_h), cross="#00e5ff")
                ii.style(f"position: absolute; top: 0; left: 0; "
                         f"width: {v.canvas_w}px; height: {v.canvas_h}px; "
                         f"max-width: none;")
                ii.on("mousedown", on_down,
                      ["offsetX", "offsetY", "button", "buttons", "ctrlKey", "shiftKey"])
                ii.on("mousemove", on_move, ["offsetX", "offsetY", "buttons"],
                      throttle=0.03)
                ii.on("mouseup", on_up, ["offsetX", "offsetY"])
                ii.on("dblclick", on_dblclick, ["offsetX", "offsetY"])
                # Replay marker layer (Item 30, plan §4): a second full-canvas
                # overlay stacked *above* ii so the animated markers sit over
                # the static zone/centerline overlay. pointer-events:none lets
                # every mouse event fall through to ii beneath; only this layer's
                # content is rewritten each ui.timer tick, never the full svg().
                replay_layer = ui.interactive_image(
                    content="", size=(v.canvas_w, v.canvas_h))
                replay_layer.style(f"position: absolute; top: 0; left: 0; "
                                   f"width: {v.canvas_w}px; height: {v.canvas_h}px; "
                                   f"max-width: none; pointer-events: none;")
                # js_handler zooms `stage` locally every tick; the emit
                # (throttled, so it can't flood the socket) syncs absolute
                # viewport state to on_wheel. Bound to `stage` so the JS reads/
                # writes the same element the server transforms.
                stage.on("wheel.prevent", on_wheel, args=None,
                         js_handler=_WHEEL_ZOOM_JS, throttle=0.05)
        # w-[32rem] (512px): wide enough for the 7-column table (S · On · Name ·
        # Ph · Out · Type · CL + the multi-select checkbox ≈ 466px of content) to
        # fit without Quasar's internal horizontal scrollbar. Trades a little
        # canvas width for a table that reads at a glance (owner's call).
        with ui.column().classes("w-[32rem] px-1 overflow-y-auto") \
                .style("height: 100%;") as zone_panel:
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
                    {"name": "cl", "label": "CL", "field": "cl",
                     "align": "left", "sortable": True},
                ],
                rows=zone_rows(), row_key="key", selection="multiple",
                on_select=on_table_select, pagination=0) \
                .classes("w-full").props("dense flat hide-bottom")
            zone_table.on("rowClick", on_table_row_click)
            zone_table.on("rowDblclick", on_table_row_dblclick)
            ui.label("click: select one · checkbox: multi-select · "
                     "double-click: properties") \
                .classes("text-xs text-gray-500 px-1")

    # Set initial per-mode visibility after zone_panel exists (the context bar
    # now governs the zone table too, so this must run once it's built).
    update_context_bar()
    update_event_cl_options()  # populate the Event-Zone CL dropdown from load

    with ui.row().classes("w-full justify-between px-2"):
        status_label = ui.label("mode: edit").classes("text-white font-mono")
        pos_label = ui.label("—").classes("text-white font-mono")
        scale_label = ui.label(status_scale()).classes("text-white font-mono")

    refresh_status()
    # Replay animation clock (Item 30): a fixed 10 fps cadence (plan §6),
    # inactive until playback starts so it costs nothing off-Replay.
    replay_timer = ui.timer(0.1, replay_tick, active=False)
    # Live overlay clock (Item 35): the same fixed 10 fps cadence (plan §3),
    # inactive until a live connection starts so it costs nothing off-Live.
    live_timer = ui.timer(0.1, live_tick, active=False)
    # Record status poll (ROADMAP Item 37): keeps the consolidated status
    # line live while in Record mode even with the dialog closed — mirrors
    # the dialog-local `record_timer`'s 0.5s cadence, just scoped to the
    # main toolbar instead of the dialog.
    record_status_timer = ui.timer(0.5, refresh_status, active=False)
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
