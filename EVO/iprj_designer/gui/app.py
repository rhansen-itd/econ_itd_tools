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
New/Open/Upload file management (see the New/Open/Upload buttons and the
Ruler tool below).

Usage:
    python gui/app.py [site.iprj | background.png] [--port 8080]

Defaults to sites/Banks/banks.iprj. Open http://localhost:<port> in a
browser. Mouse wheel zooms at the cursor; drag pans (in Pan mode, or with
the middle button in any mode). Use New/Open/Upload BG in the toolbar to
switch projects without restarting the app.

Keys: l draw · e edit toggle · s sensor mode · r ruler · g snap ·
u / Ctrl-Z undo · Esc cancel · digits/d + Enter dimension entry ·
n/b cycle selection · arrows nudge · x/Del delete · Ctrl-drag copies the
selected zone · p / double-click zone properties · f fit view · Ctrl-S save.

Ruler tool: click to set the first point, then move the mouse (or drag) to
see the live distance in feet; click again — or release a drag — to set the
second point. Click again to start a new measurement; Esc cancels a
measurement in progress. The last ruler stays visible until cleared (the
"clear markers & ruler" toolbar button) or replaced.

Template tool: pick a template from the toolbar dropdown, switch to the
Template tool, and click the stop-bar reference point (where the stop bar
meets the left edge of the leftmost lane). With a centerline drawn, that
one click places the whole detector set along the nearest centerline (live
preview under the cursor); with no centerline, click again to aim upstream
and place along that straight line. Centerline-placed zones stay attached:
reshaping the centerline re-stations them. The .iprj cannot store the
attachment itself, so reopening a project re-derives it — zones that are
still exact station/offset rectangles on a centerline re-attach
automatically (a notification reports how many).

Centerline tool: pick the active centerline from its selector (or add a new
one for another approach), then click along it starting at the stop bar
(station 0) and continuing upstream; click-drag repositions a vertex, x/Del
removes the selected one. The status/position readouts show live station +
offset while the tool is active. All centerlines in the project render at
once; only the active one is editable.
"""

from __future__ import annotations

import argparse
import atexit
import base64
import io
import math
import os
import sys
import tempfile
import time
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nicegui import ui

from gui.drawing import (DIM_OFF, CenterlineController, DrawingController,
                         derive_attachments, insert_zone, is_placeholder,
                         next_output_number)
from gui.viewport import Viewport
from model import domain, units
from model.centerline import load_centerlines, save_centerlines
from model.iprj_io import (Background, Condition, EventZone, Project, Sensor,
                           load_iprj, save_iprj)
from model.templates import (expand_and_place, expand_and_place_on_centerline,
                             load_template)

REPO = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"

PHASE_COLORS = ["#d62728", "#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd",
                "#8c564b", "#e377c2", "#bcbd22", "#17becf"]

# Vendor-confirmed ZoneType names (see model/domain.py): 0 Motion,
# 1 Presence, 2 Sidewalk.
ZONE_TYPE_NAMES = {int(t): f"{int(t)} — {name}"
                   for t, name in domain.ZONE_TYPE_NAMES.items()}

# Vendor-default condition factory moved to the model layer in Phase 2.
new_condition = domain.default_condition


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
    def __init__(self, project: Project, source: Path):
        self.project = project
        self.source = source
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
        self.mode = "Pan"
        self.show_zones = True     # layer toggles (background is CSS-only)
        self.show_labels = True
        self.show_sensors = True
        self.markers: list[tuple[float, float]] = []  # world px
        self.cal_points: list[tuple[float, float]] = []  # world px, pending 2-pt
        self.drag_anchor: tuple[float, float] | None = None
        self.sensor_drag: dict | None = None  # in-flight sensor move
        # 2-point ruler (Phase 1): click to start, click again (or a real
        # drag-release) to end; ruler_pending is true between the two.
        self.ruler_start: tuple[float, float] | None = None  # world px
        self.ruler_end: tuple[float, float] | None = None    # world px
        self.ruler_pending = False
        # px per SVG unit shrinks as we zoom in; keep overlay strokes readable
        self.overlay_px = 2.0
        # template placement (Session 6.3): ref click -> aim click -> place
        self.template = None  # ApproachTemplate | None
        self.template_ref: tuple[float, float] | None = None  # world px
        self.template_cursor: tuple[float, float] | None = None  # world px
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
        self.ctrl = DrawingController(project.sensors[0].event_zones,
                                      self.ft_per_px, self.next_output)
        # Attachments don't persist in the .iprj, so re-derive them: zones
        # that are exact station/offset rectangles on a loaded centerline
        # follow centerline edits again after reopening the project.
        self.derived_attachments = derive_attachments(
            self.centerlines, [s.event_zones for s in project.sensors])

    def next_output(self) -> int:
        return next_output_number(s.event_zones for s in self.project.sensors)

    def active_zones(self):
        return self.project.sensors[self.active_si].event_zones

    def set_active_sensor(self, si: int) -> None:
        self.active_si = si
        self.ctrl.retarget(self.active_zones())

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

    def centerline_for(self, p) -> CenterlineController | None:
        """The drawn centerline nearest world point *p* (smallest |offset|
        of its projection) — the datum template placement follows — or None
        when no controller has a usable (≥2 distinct points) datum yet."""
        best, best_off = None, None
        for ctrl in self.centerlines:
            c = ctrl.current()
            if c is None:
                continue
            off = abs(c.project(p)[1])
            if best_off is None or off < best_off:
                best, best_off = ctrl, off
        return best

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
        if self.mode == "Ruler" and self.ruler_start is not None and self.ruler_pending:
            return f"{base}   |   distance: {self._ruler_reading(self.ruler_start, (wx, wy))}"
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
        if any(cl.current() is not None for cl in self.centerlines):
            return (f"mode: template | {self.template.name} | click the "
                    "stop-bar reference point (left edge of the leftmost "
                    "lane) — detectors follow the nearest centerline")
        if self.template_ref is None:
            return (f"mode: template | {self.template.name} | click the "
                    "stop-bar reference point (left edge of the leftmost lane)")
        return (f"mode: template | {self.template.name} | aim upstream, "
                "click to place  [Esc cancels]")

    # -- overlay ------------------------------------------------------------

    def svg(self) -> str:
        bg = self.bg
        w2i = lambda p: units.world_to_image(bg, p)
        lw = self.overlay_px / max(self.viewport.scale, 0.05)
        font = 7 * lw
        parts = []
        for si, sensor in enumerate(self.project.sensors):
            for zi, zone in enumerate(sensor.event_zones):
                if not self.show_zones or not zone.enable or len(zone.points) < 3:
                    continue
                color = PHASE_COLORS[(zone.phase_number or 0) % len(PHASE_COLORS)]
                pts = [w2i(p) for p in zone.points]
                selected = (si == self.active_si and self.ctrl.mode == "edit"
                            and zi == self.ctrl.selected)
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
            for zone in sensor.ignore_zones:
                if not self.show_zones or not zone.enable or len(zone.points) < 3:
                    continue
                parts.append(_polygon([w2i(p) for p in zone.points], fill="none",
                                      stroke="yellow", stroke_width=lw,
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
        for wp in self.markers:
            x, y = w2i(wp)
            parts.append(_cross(x, y, 5 * lw, "#00e5ff", lw))
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
            cl_ctrl = self.centerline_for(cursor) if cursor is not None else None
            placed = []
            fpp = self.ft_per_px()
            if cl_ctrl is not None:
                cx, cy = w2i(cursor)
                parts.append(_cross(cx, cy, 5 * lw, "#00e5ff", lw))
                if fpp is not None:
                    try:
                        placed = expand_and_place_on_centerline(
                            self.template, cl_ctrl.points, cursor, 1.0 / fpp)
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
                                                      upstream, 1.0 / fpp)
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
            si, zi = v.active_si, v.ctrl.selected
            if v.mode != "Edit":
                ui.notify("select a zone in Edit mode first", type="warning")
                return
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

            def add_cond_row(cond: Condition):
                with conds_col, ui.row().classes("items-center gap-2") as row_el:
                    entry = {
                        "cond": cond,
                        "en": ui.checkbox(value=bool(cond.enable)),
                        "out": ui.number("output", value=cond.output_number or 0,
                                         min=0, precision=0).classes("w-20"),
                        "cls": ui.number("class", value=cond.condition_class or 0,
                                         min=0, precision=0).classes("w-16"),
                        "vmin": ui.number("v min (mph)", precision=1,
                                          value=round(units.kmh_to_mph(
                                              cond.velocity_min or 0.0), 1)).classes("w-28"),
                        "vmax": ui.number("v max (mph)", precision=1,
                                          value=round(units.kmh_to_mph(
                                              cond.velocity_max or 0.0), 1)).classes("w-28"),
                    }
                    ui.button(icon="delete",
                              on_click=lambda e=entry, r=row_el:
                              (cond_rows.remove(e), conds_col.remove(r))) \
                        .props("flat dense")
                cond_rows.append(entry)

            with ui.row().classes("w-full items-center"):
                ui.label("Conditions").classes("text-base")
                ui.button("Add condition",
                          on_click=lambda: add_cond_row(
                              new_condition(int(output.value or 0))))
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
                    c.output_number = int(r["out"].value or 0)
                    c.condition_class = int(r["cls"].value or 0)
                    c.velocity_min = units.mph_to_kmh(float(r["vmin"].value or 0.0))
                    c.velocity_max = units.mph_to_kmh(float(r["vmax"].value or 0.0))
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
        v.set_active_sensor(e.value)
        refresh_overlay()
        refresh_status()

    def add_sensor():
        s = Sensor()
        s.position_x, s.position_y = units.image_to_world(
            v.bg, (v.image_w / 2, v.image_h / 2))
        v.project.sensors.append(s)
        v.set_active_sensor(len(v.project.sensors) - 1)
        update_sensor_options()
        tool.value = "Sensor"
        refresh_overlay()
        ui.notify(f"S{len(v.project.sensors)} placed at image center — drag to position")

    # -- centerlines ---------------------------------------------------------

    def update_centerline_options():
        centerline_sel.set_options(
            {i: f"C{i + 1}" for i in range(len(v.centerlines))},
            value=v.active_cli)

    def change_active_centerline(e):
        if e.value is None or e.value == v.active_cli:
            return
        v.set_active_centerline(e.value)
        refresh_overlay()
        refresh_status()

    def add_centerline():
        v.add_centerline()
        update_centerline_options()
        tool.value = "Centerline"
        refresh_overlay()
        refresh_status()
        ui.notify(f"C{len(v.centerlines)} ready — click the stop bar to start it")

    # -- template placement ------------------------------------------------------

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
        refresh_overlay()
        refresh_status()

    def place_template(pw):
        fpp = v.ft_per_px()
        if fpp is None:
            ui.notify("calibrate the background before placing a template",
                      type="warning")
            v.template_ref = None
            refresh_overlay()
            refresh_status()
            return
        cl_ctrl = v.centerline_for(pw)
        if cl_ctrl is not None:
            # curvilinear (Session 7.5): the click is the stop-bar reference;
            # direction and curvature come from the nearest centerline
            placed = expand_and_place_on_centerline(v.template, cl_ctrl.points,
                                                    pw, 1.0 / fpp)
        else:
            upstream = (pw[0] - v.template_ref[0], pw[1] - v.template_ref[1])
            if math.hypot(*upstream) < 1e-6:
                ui.notify("click a point away from the reference to aim",
                          type="warning")
                return
            placed = expand_and_place(v.template, v.template_ref, upstream,
                                      1.0 / fpp)
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
        along = (f" along C{v.centerlines.index(cl_ctrl) + 1}"
                 if cl_ctrl is not None else "")
        ui.notify(f"placed {len(placed)} detectors from {v.template.name}{along} "
                  f"(outputs {placed[0].spec.output_number}-"
                  f"{placed[-1].spec.output_number})")

    # -- save --------------------------------------------------------------------

    def do_save(path: Path):
        v.project.date = time.strftime("%Y_%m_%d_%H:%M:%S")
        save_centerlines(v.project, [cl.points for cl in v.centerlines])
        save_iprj(v.project, path)
        v.source = path
        title_label.set_text(f"iprj Designer — {path.name}")
        ui.notify(f"saved {path}")

    def save():
        if v.source.suffix.lower() == ".iprj":
            do_save(v.source)
        else:
            save_as()

    def save_as():
        with ui.dialog() as dialog, ui.card():
            ui.label("Save project as:")
            path_in = ui.input("path", value=str(v.source.with_suffix(".iprj"))) \
                .style("min-width: 420px")

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

    # -- mouse handling (offsetX/Y == image px: element kept at natural size)

    def refresh_status():
        if v.mode in ("Draw", "Edit"):
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
        elif v.mode == "Ruler":
            status_label.set_text(v.ruler_status())
        else:
            status_label.set_text(f"mode: {v.mode.lower()}")
        snap_switch.set_value(v.ctrl.snap_enabled)  # no-op when already equal
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
        sel_key = None
        if v.mode == "Edit" and 0 <= v.ctrl.selected < len(v.active_zones()):
            sel_key = f"{v.active_si}:{v.ctrl.selected}"
        zone_table.selected = [r for r in rows if r["key"] == sel_key]
        zone_table.update()

    def select_zone_key(key: str):
        si, zi = (int(x) for x in key.split(":"))
        if si != v.active_si:
            sensor_sel.set_value(si)  # on_change retargets the controller
        if v.mode != "Edit":
            tool.value = "Edit"       # on_change syncs the controller mode
        v.ctrl.selected = zi
        refresh_overlay()
        refresh_status()

    def on_table_select(e):
        if e.selection:
            select_zone_key(e.selection[0]["key"])
        elif v.mode == "Edit" and v.ctrl.selected != -1:
            v.ctrl.selected = -1
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
            ui.notify("switch to Edit mode to delete", type="warning")
            return
        v.ctrl.delete_selected()
        refresh_overlay()
        refresh_status()

    def set_layer(attr: str, on: bool):
        setattr(v, attr, bool(on))
        refresh_overlay()

    def set_bg_visible(on: bool):
        ii.classes(remove="bg-off") if on else ii.classes(add="bg-off")

    def toggle_zone_panel():
        zone_panel.set_visibility(not zone_panel.visible)

    def clear_markers_and_ruler():
        v.markers.clear()
        v.ruler_start = None
        v.ruler_end = None
        v.ruler_pending = False
        refresh_overlay()
        refresh_status()

    def on_down(e):
        p = (e.args["offsetX"], e.args["offsetY"])
        button = e.args.get("button", 0)
        if button == 1 or (button == 0 and v.mode == "Pan"):
            v.drag_anchor = p
        elif button == 0 and v.mode == "Marker":
            v.markers.append(units.image_to_world(v.bg, p))
            refresh_overlay()
            ui.notify(f"marker at {v.describe(p)}")
        elif button == 0 and v.mode == "Calibrate 2-pt":
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
        elif button == 0 and v.mode in ("Draw", "Edit"):
            v.ctrl.mouse_down(units.image_to_world(v.bg, p),
                              ctrl=bool(e.args.get("ctrlKey")))
            refresh_overlay()
            refresh_status()
        elif button == 0 and v.mode == "Template":
            if v.template is None:
                ui.notify("pick a template first", type="warning")
                return
            pw = units.image_to_world(v.bg, p)
            if v.centerline_for(pw) is not None:
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
        elif button == 0 and v.mode == "Ruler":
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

    def on_move(e):
        p = (e.args["offsetX"], e.args["offsetY"])
        pos_label.set_text(v.describe(p))
        if v.drag_anchor is not None and e.args.get("buttons", 0):
            v.viewport.drag_to(v.drag_anchor, p)
            apply_transform()
        elif v.sensor_drag is not None and e.args.get("buttons", 0) & 1:
            pw = units.image_to_world(v.bg, p)
            d = v.sensor_drag
            s = v.project.sensors[d["si"]]
            s.position_x = d["orig"][0] + pw[0] - d["anchor"][0]
            s.position_y = d["orig"][1] + pw[1] - d["anchor"][1]
            if math.dist(pw, d["anchor"]) > v.ctrl.handle_radius / 3:
                d["moved"] = True
            refresh_overlay()
        elif v.mode in ("Draw", "Edit"):
            dragging = bool(e.args.get("buttons", 0) & 1)
            v.ctrl.mouse_move(units.image_to_world(v.bg, p), dragging)
            # only redraw while something tracks the mouse
            if v.ctrl.pending or dragging or v.ctrl.snap_enabled:
                refresh_overlay()
        elif v.mode == "Template" and v.template is not None:
            # cursor tracked from the first hover: with a centerline the
            # preview follows the mouse before any click
            v.template_cursor = units.image_to_world(v.bg, p)
            refresh_overlay()
        elif v.mode == "Centerline":
            dragging = bool(e.args.get("buttons", 0) & 1)
            v.centerline_ctrl.mouse_move(units.image_to_world(v.bg, p), dragging)
            if dragging:
                refresh_overlay()
        elif v.mode == "Ruler" and v.ruler_pending:
            v.ruler_end = units.image_to_world(v.bg, p)
            refresh_overlay()

    def on_up(e):
        v.drag_anchor = None
        if v.sensor_drag is not None:
            d, v.sensor_drag = v.sensor_drag, None
            if not d["moved"]:
                sensor_properties(d["si"])
        elif v.mode in ("Draw", "Edit"):
            p = (e.args["offsetX"], e.args["offsetY"])
            v.ctrl.mouse_up(units.image_to_world(v.bg, p))
            v.reproject_attachments()  # a drag may have moved an attached zone
            refresh_overlay()
            refresh_status()
        elif v.mode == "Centerline":
            p = (e.args["offsetX"], e.args["offsetY"])
            v.centerline_ctrl.mouse_up(units.image_to_world(v.bg, p))
            refresh_overlay()
            refresh_status()
        elif v.mode == "Ruler" and v.ruler_pending:
            # a real click-drag-release finishes the measurement in one
            # gesture; a plain click leaves it pending for a second click
            p = (e.args["offsetX"], e.args["offsetY"])
            pw = units.image_to_world(v.bg, p)
            if math.dist(pw, v.ruler_start) > v.ctrl.handle_radius / 3:
                v.ruler_end = pw
                v.ruler_pending = False
                refresh_overlay()
                refresh_status()

    def on_dblclick(e):
        # the two mousedowns already selected the zone under the cursor
        if v.mode == "Edit":
            zone_properties()

    async def on_key(e):
        if not e.action.keydown:
            return
        name = e.key.name
        if e.action.repeat and name != "Backspace" \
                and not name.startswith("Arrow"):
            return
        if e.modifiers.ctrl and name == "s":
            save()
            return
        if name == "f":
            await fit_view()
            return
        if name == "l":
            tool.value = "Draw"  # on_change syncs the controller
            return
        if name == "e":
            tool.value = "Edit" if v.mode != "Edit" else "Draw"
            return
        if name == "s":
            tool.value = "Sensor"
            return
        if name == "r":
            tool.value = "Ruler"
            return
        if name in ("p", "Enter") and v.mode == "Edit" \
                and v.ctrl.dim_stage == DIM_OFF:
            zone_properties()
            return
        if name == "Escape" and v.mode == "Template" and v.template_ref is not None:
            v.template_ref = None
            v.template_cursor = None
            refresh_overlay()
            refresh_status()
            return
        if name == "Escape" and v.mode == "Ruler" and v.ruler_pending:
            v.ruler_start = None
            v.ruler_end = None
            v.ruler_pending = False
            refresh_overlay()
            refresh_status()
            return
        if v.mode in ("Draw", "Edit") and v.ctrl.key(name, e.modifiers.ctrl):
            v.reproject_attachments()  # nudge/undo may have moved attached zones
            refresh_overlay()
            refresh_status()
        elif v.mode == "Centerline" and v.centerline_ctrl.key(name, e.modifiers.ctrl):
            refresh_overlay()
            refresh_status()

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
        if e.value != "Ruler" and v.ruler_pending:
            v.ruler_start = None
            v.ruler_end = None
            v.ruler_pending = False
        refresh_overlay()
        refresh_status()

    def on_wheel(e):
        factor = 0.9 ** (e.args["deltaY"] / 100.0)
        v.viewport.zoom_at((e.args["offsetX"], e.args["offsetY"]), factor)
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

    with ui.row().classes("w-full items-center gap-2 px-2 no-wrap overflow-x-auto"):
        title_label = ui.label(f"iprj Designer — {v.source.name}") \
            .classes("text-lg text-white whitespace-nowrap")
        with ui.button(icon="note_add", on_click=new_project).props("flat dense"):
            ui.tooltip("new project (blank or from an uploaded image)")
        with ui.button(icon="folder_open", on_click=open_existing).props("flat dense"):
            ui.tooltip("open an existing .iprj file")
        ui.separator().props("vertical")
        tool = ui.toggle(["Pan", "Draw", "Edit", "Sensor", "Marker",
                          "Calibrate 2-pt", "Template", "Centerline", "Ruler"],
                         value="Pan", on_change=change_tool).props("dense")
        with tool:
            ui.tooltip("accelerators: l draw · e edit toggle · s sensor · "
                       "r ruler · Esc cancel")
        snap_switch = ui.switch("snap", on_change=toggle_snap).props("dense")
        with snap_switch:
            ui.tooltip("vertex/midpoint snapping (g)")
        with ui.button(icon="undo", on_click=do_undo).props("flat dense"):
            ui.tooltip("undo (u / Ctrl-Z)")
        with ui.button(icon="delete", on_click=do_delete).props("flat dense"):
            ui.tooltip("delete selected zone (x / Del)")
        with ui.button(icon="tune", on_click=lambda: zone_properties()) \
                .props("flat dense"):
            ui.tooltip("zone properties (p / Enter / double-click)")
        ui.separator().props("vertical")
        sensor_sel = ui.select(
            {i: f"S{i + 1}" for i in range(len(v.project.sensors))},
            value=v.active_si, label="sensor",
            on_change=change_active_sensor).classes("w-24").props("dense")
        with ui.button(icon="add_circle", on_click=add_sensor).props("flat dense"):
            ui.tooltip("add a sensor at image center")
        with ui.button(icon="straighten", on_click=calibrate_by_size) \
                .props("flat dense"):
            ui.tooltip("calibrate by known image width/height "
                       "(two-point: use the Calibrate 2-pt tool)")
        ui.separator().props("vertical")
        centerline_sel = ui.select(
            {i: f"C{i + 1}" for i in range(len(v.centerlines))},
            value=v.active_cli, label="centerline",
            on_change=change_active_centerline).classes("w-28").props("dense")
        with ui.button(icon="add_road", on_click=add_centerline).props("flat dense"):
            ui.tooltip("add a new centerline (another approach)")
        ui.separator().props("vertical")
        template_sel = ui.select(template_files(), label="template",
                                 on_change=change_template) \
            .classes("w-48").props("dense clearable")
        with template_sel:
            ui.tooltip("approach template to place (Template tool: click the "
                       "stop-bar reference point — follows the nearest "
                       "centerline, or a second aim click without one)")
        ui.separator().props("vertical")
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
        with ui.button(icon="wrong_location",
                       on_click=clear_markers_and_ruler).props("flat dense"):
            ui.tooltip("clear markers & ruler")
        ui.space()
        with ui.button(icon="save", on_click=save).props("flat dense"):
            ui.tooltip("save (Ctrl-S)")
        ui.button("Save As…", on_click=save_as).props("flat dense")
        with ui.button(icon="view_sidebar", on_click=toggle_zone_panel) \
                .props("flat dense"):
            ui.tooltip("show/hide the zone table")

    ui.keyboard(on_key=on_key)  # ignores keys typed into dialogs/inputs

    with ui.row().classes("w-full no-wrap gap-0"):
        with ui.element("div").props("id=viewport").classes("grow overflow-hidden") \
                .style("height: calc(100vh - 120px); position: relative; "
                       "background: #111; cursor: crosshair;"):
            ii = ui.interactive_image(v.image_file, content=v.svg(), cross="#00e5ff")
            ii.style(f"width: {v.image_w}px; height: {v.image_h}px; "
                     f"max-width: none; position: absolute;")
            ii.on("mousedown", on_down,
                  ["offsetX", "offsetY", "button", "buttons", "ctrlKey"])
            ii.on("mousemove", on_move, ["offsetX", "offsetY", "buttons"],
                  throttle=0.03)
            ii.on("mouseup", on_up, ["offsetX", "offsetY"])
            ii.on("dblclick", on_dblclick, ["offsetX", "offsetY"])
            ii.on("wheel.prevent", on_wheel, ["deltaY", "offsetX", "offsetY"])
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
                rows=zone_rows(), row_key="key", selection="single",
                on_select=on_table_select, pagination=0) \
                .classes("w-full").props("dense flat hide-bottom")
            zone_table.on("rowClick", on_table_row_click)
            zone_table.on("rowDblclick", on_table_row_dblclick)
            ui.label("click: select · double-click: properties") \
                .classes("text-xs text-gray-500 px-1")

    with ui.row().classes("w-full justify-between px-2"):
        status_label = ui.label("mode: pan").classes("text-white font-mono")
        pos_label = ui.label("—").classes("text-white font-mono")
        scale_label = ui.label(status_scale()).classes("text-white font-mono")

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
    state = {"viewer": Viewer(open_project(args.path), args.path)}
    ui.run(lambda: build_ui(state["viewer"], state), port=args.port,
           title="iprj Designer", reload=False, show=False, dark=True)


if __name__ in {"__main__", "__mp_main__"}:
    main()
