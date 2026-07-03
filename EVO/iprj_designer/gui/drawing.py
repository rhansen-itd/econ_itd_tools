"""Draw/edit state machine for zone loops — pure python, no GUI imports.

Ported from the interaction model of pyatspm's ``video/calibrate.py`` (free
4-point loops, snap toggle, edit mode with drag/Ctrl-drag-copy, undo),
upgraded with the dimensioned-rectangle workflow: click a corner, aim with
the mouse, type the two side lengths in feet.

The controller operates entirely in world-pixel coordinates (y-down); the
GUI converts mouse events before feeding them in and renders from the state
exposed here (``pending``, ``preview_polygon()``, ``snap_indicator``,
``selected``, ``status()``). Feet enter only through the ``ft_per_px``
supplier, so an uncalibrated background simply disables dimensioned draw.
"""

from __future__ import annotations

import copy
import re
from typing import Callable

from model import geometry
from model.iprj_io import EventZone, Point

# Stages of dimensioned-rectangle entry
DIM_OFF = 0      # not entering dimensions
DIM_LENGTH1 = 1  # typing first length; mouse aims the first side
DIM_LENGTH2 = 2  # typing second length; mouse picks the extrude side

NUDGE_FT = 0.5   # arrow-key nudge step when calibrated
ARROWS = {"ArrowLeft": (-1, 0), "ArrowRight": (1, 0),
          "ArrowUp": (0, -1), "ArrowDown": (0, 1)}  # world px is y-down


def is_placeholder(zone: EventZone) -> bool:
    """Vendor files pad each sensor to 64 zones with disabled, empty slots."""
    return not zone.enable and not (zone.zone_name or "").strip() \
        and not zone.points


def insert_zone(zones: list[EventZone], zone: EventZone) -> int:
    """Put a new zone in the first placeholder slot (vendor behavior — keeps
    within the fixed 64-slot array) or append; returns the index used."""
    for i, z in enumerate(zones):
        if is_placeholder(z):
            zones[i] = zone
            return i
    zones.append(zone)
    return len(zones) - 1


def next_output_number(zone_lists) -> int:
    """Next free OutputNumber across every sensor's zones (outputs are
    detector-rack channels, shared project-wide)."""
    nums = [z.output_number for zl in zone_lists for z in zl
            if not is_placeholder(z) and z.output_number]
    return max(nums, default=0) + 1


def bumped_name(name: str | None) -> str:
    """'SBT Count 1' -> 'SBT Count 2'; names without a trailing number pass
    through unchanged (copies of numbered lane loops are the fast path)."""
    m = re.match(r"^(.*?)(\d+)\s*$", name or "")
    if m:
        return f"{m.group(1)}{int(m.group(2)) + 1}"
    return name or ""


class DrawingController:
    """Mutates a live ``list[EventZone]`` (a sensor's zones) in world px."""

    def __init__(self, zones: list[EventZone],
                 ft_per_px: Callable[[], float | None],
                 next_output: Callable[[], int] | None = None):
        self.zones = zones
        self.ft_per_px = ft_per_px
        self.next_output = next_output

        self.mode = "draw"            # "draw" | "edit"
        self.snap_enabled = False
        self.snap_radius = 12.0       # world px; GUI rescales on zoom
        self.handle_radius = 10.0     # vertex grab radius, world px

        self.pending: list[Point] = []    # clicked corners of an unfinished loop
        self.cursor: Point | None = None  # last hover position
        self.snap_indicator: Point | None = None

        self.dim_stage = DIM_OFF
        self.dim_buffer = ""
        self.dim_length1_ft = 0.0
        self.dim_dir: Point | None = None  # frozen when length 1 is committed

        self.selected = -1
        self._drag_vertex: int | None = None
        self._drag_body: dict | None = None
        self._nudging = False         # coalesces an arrow-key burst into one undo op
        # ops carry the zones list they touched, so undo works across sensor
        # retargets: ("add", zones, zone) | ("replace", zones, i, old, new) |
        # ("delete", zones, i, zone) | ("points", zone, pts)
        self._undo: list[tuple] = []
        self.message = ""             # transient feedback for the status line

    # -- helpers -------------------------------------------------------------

    def _polygons(self) -> list[list[Point]]:
        return [z.points for z in self.zones]

    def _real_indices(self) -> list[int]:
        return [i for i, z in enumerate(self.zones) if not is_placeholder(z)]

    def _snapped(self, p: Point, exclude: int | None = None) -> Point:
        self.snap_indicator = None
        if not self.snap_enabled:
            return p
        target = geometry.find_snap(p, self._polygons(), self.snap_radius, exclude)
        if target is not None:
            self.snap_indicator = target
            return target
        return p

    def _commit_zone(self, points: list[Point]) -> None:
        zone = EventZone(enable=1,
                         zone_name=f"Zone {len(self._real_indices()) + 1}",
                         points=[(float(x), float(y)) for x, y in points])
        if self.next_output is not None:
            zone.output_number = self.next_output()
        self._insert(zone)
        self.message = f"placed {zone.zone_name}" + (
            f" (output {zone.output_number})" if zone.output_number else "")

    def _insert(self, zone: EventZone) -> int:
        for i, z in enumerate(self.zones):
            if is_placeholder(z):
                self._undo.append(("replace", self.zones, i, z, zone))
                self.zones[i] = zone
                return i
        self.zones.append(zone)
        self._undo.append(("add", self.zones, zone))
        return len(self.zones) - 1

    def _reset_dim(self) -> None:
        self.dim_stage = DIM_OFF
        self.dim_buffer = ""
        self.dim_length1_ft = 0.0
        self.dim_dir = None

    def _hit_zone(self, p: Point) -> int:
        for i in range(len(self.zones) - 1, -1, -1):  # topmost first
            z = self.zones[i]
            if z.enable and len(z.points) >= 3 and \
                    geometry.polygon_hit(p, z.points, self.handle_radius / 2):
                return i
        return -1

    # -- mouse ---------------------------------------------------------------

    def mouse_down(self, p: Point, ctrl: bool = False) -> None:
        self.message = ""
        self._nudging = False
        if self.mode == "draw":
            if self.dim_stage != DIM_OFF:
                return  # dimensions are committed with Enter, not clicks
            self.pending.append(self._snapped(p))
            if len(self.pending) == 4:
                self._commit_zone(self.pending)
                self.pending = []
        elif self.mode == "edit":
            if self.selected != -1:
                zone = self.zones[self.selected]
                for i, pt in enumerate(zone.points):
                    if geometry.dist(p, pt) <= self.handle_radius:
                        self._drag_vertex = i
                        self._undo.append(("points", zone, list(zone.points)))
                        return
            hit = self._hit_zone(p)
            if hit == -1:
                return
            self.selected = hit
            zone = self.zones[hit]
            if ctrl:
                zone = copy.deepcopy(zone)
                zone.zone_name = bumped_name(zone.zone_name)
                if self.next_output is not None:
                    zone.output_number = self.next_output()
                self.selected = self._insert(zone)
            else:
                self._undo.append(("points", zone, list(zone.points)))
            self._drag_body = {"anchor": p, "orig": list(zone.points)}

    def mouse_move(self, p: Point, dragging: bool = False) -> None:
        self.cursor = p
        if self.mode == "draw":
            # live snap indicator for the next click / preview vertex
            self._snapped(p)
        elif self.mode == "edit" and dragging:
            if self._drag_vertex is not None and self.selected != -1:
                zone = self.zones[self.selected]
                zone.points[self._drag_vertex] = self._snapped(p, self.selected)
            elif self._drag_body is not None:
                dx = p[0] - self._drag_body["anchor"][0]
                dy = p[1] - self._drag_body["anchor"][1]
                self.zones[self.selected].points = [
                    (x + dx, y + dy) for x, y in self._drag_body["orig"]]

    def mouse_up(self, p: Point) -> None:
        if self._drag_vertex is not None:
            self._drag_vertex = None
        elif self._drag_body is not None:
            if self.snap_enabled and self.selected != -1:
                zone = self.zones[self.selected]
                corr = geometry.translation_to_snap(
                    zone.points, self._polygons(), self.snap_radius, self.selected)
                if corr is not None:
                    zone.points = [(x + corr[0], y + corr[1]) for x, y in zone.points]
            self._drag_body = None
        self.snap_indicator = None

    # -- keyboard ------------------------------------------------------------

    def key(self, name: str, ctrl: bool = False) -> bool:
        """Handle a key press; returns True if it changed anything."""
        self.message = ""
        if name not in ARROWS:
            self._nudging = False
        if name == "g":
            self.snap_enabled = not self.snap_enabled
            if not self.snap_enabled:
                self.snap_indicator = None
            return True
        if name == "e":
            self.set_mode("edit" if self.mode == "draw" else "draw")
            return True
        if name == "l":
            self.set_mode("draw")
            return True
        if name == "u" or (ctrl and name == "z"):
            self.undo()
            return True
        if name == "Escape":
            return self.cancel()

        if self.mode == "draw":
            return self._key_draw(name)
        return self._key_edit(name)

    def _key_draw(self, name: str) -> bool:
        starts_dim = name == "d" or (name.isdigit() and len(name) == 1)
        if self.dim_stage == DIM_OFF:
            if not starts_dim or len(self.pending) != 1:
                if starts_dim and not self.pending:
                    self.message = "click the first corner before typing dimensions"
                    return True
                return False
            if self.ft_per_px() is None:
                self.message = "calibrate the background before dimensioned draw"
                return True
            self.dim_stage = DIM_LENGTH1
            self.dim_buffer = name if name.isdigit() else ""
            return True

        # in dimension entry
        if name.isdigit() and len(name) == 1 or name == ".":
            if not (name == "." and "." in self.dim_buffer):
                self.dim_buffer += name
            return True
        if name == "Backspace":
            self.dim_buffer = self.dim_buffer[:-1]
            return True
        if name == "Enter":
            return self._commit_dimension()
        return False

    def _commit_dimension(self) -> bool:
        try:
            length_ft = float(self.dim_buffer)
        except ValueError:
            length_ft = 0.0
        if length_ft <= 0:
            self.message = "enter a length in feet, then Enter"
            return True
        if self.dim_stage == DIM_LENGTH1:
            if self.cursor is None or \
                    geometry.unit_vector(self.pending[0], self.cursor) is None:
                self.message = "aim with the mouse to set the direction"
                return True
            self.dim_dir = geometry.unit_vector(self.pending[0], self.cursor)
            self.dim_length1_ft = length_ft
            self.dim_stage = DIM_LENGTH2
            self.dim_buffer = ""
            return True
        # DIM_LENGTH2 — place the rectangle, extruded toward the mouse side
        fpp = self.ft_per_px()
        if fpp is None:
            self._reset_dim()
            return True
        rect = geometry.dimensioned_rect(
            self.pending[0], self.dim_dir,
            self.dim_length1_ft / fpp, length_ft / fpp,
            self.cursor if self.cursor is not None else self.pending[0])
        self._commit_zone(rect)
        self.pending = []
        self._reset_dim()
        return True

    def _key_edit(self, name: str) -> bool:
        if name in ("n", "b"):
            real = self._real_indices()
            if not real:
                return False
            step = 1 if name == "n" else -1
            if self.selected in real:
                self.selected = real[(real.index(self.selected) + step) % len(real)]
            else:
                self.selected = real[-1]
            return True
        if name in ("Delete", "x"):
            self.delete_selected()
            return True
        if name in ARROWS:
            return self._nudge(*ARROWS[name])
        return False

    def _nudge(self, ux: float, uy: float) -> bool:
        """Move the selected zone one small step; a burst of arrow presses
        coalesces into a single undo op."""
        if self.selected == -1 or self.selected >= len(self.zones):
            return False
        zone = self.zones[self.selected]
        fpp = self.ft_per_px()
        step = NUDGE_FT / fpp if fpp else 2.0  # world px
        if not (self._nudging and self._undo
                and self._undo[-1][0] == "points" and self._undo[-1][1] is zone):
            self._undo.append(("points", zone, list(zone.points)))
        self._nudging = True
        zone.points = [(x + ux * step, y + uy * step) for x, y in zone.points]
        self.message = f"nudged {NUDGE_FT:g} ft" if fpp else f"nudged {step:g} px"
        return True

    # -- commands ------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.pending = []
        self._reset_dim()
        self._drag_vertex = None
        self._drag_body = None
        self._nudging = False
        self.snap_indicator = None
        if mode == "edit" and self.selected == -1:
            real = self._real_indices()
            self.selected = real[-1] if real else -1

    def retarget(self, zones: list[EventZone]) -> None:
        """Point the controller at another sensor's zone list (active-sensor
        switch). In-progress interactions reset; the undo stack survives
        because each op carries the list it touched."""
        self.zones = zones
        self.pending = []
        self._reset_dim()
        self._drag_vertex = None
        self._drag_body = None
        self._nudging = False
        self.snap_indicator = None
        self.selected = -1

    def cancel(self) -> bool:
        """Escape: back out one level (dimension entry → pending → selection)."""
        if self.dim_stage != DIM_OFF:
            self._reset_dim()
            return True
        if self.pending:
            self.pending = []
            return True
        if self.selected != -1:
            self.selected = -1
            return True
        return False

    def undo(self) -> None:
        if self.dim_stage != DIM_OFF:
            self._reset_dim()
            self.message = "dimension entry cancelled"
            return
        if self.pending:
            self.pending.pop()
            self.message = "removed last point"
            return
        if not self._undo:
            self.message = "nothing to undo"
            return
        op = self._undo.pop()
        if op[0] == "add":
            _, zones, zone = op
            idx = next((i for i, z in enumerate(zones) if z is zone), None)
            if idx is None:
                self.message = "nothing to undo"
                return
            zones.pop(idx)
            if zones is self.zones and self.selected >= len(zones):
                self.selected = len(zones) - 1
            self.message = f"undid add of {zone.zone_name or 'zone'}"
        elif op[0] == "replace":
            _, zones, idx, old, new = op
            if idx < len(zones) and zones[idx] is new:
                zones[idx] = old
            if zones is self.zones and self.selected == idx:
                self.selected = -1
            self.message = f"undid add of {new.zone_name or 'zone'}"
        elif op[0] == "delete":
            _, zones, idx, zone = op
            zones.insert(idx, zone)
            if zones is self.zones:
                self.selected = idx
            self.message = f"restored {zone.zone_name or 'zone'}"
        elif op[0] == "points":
            _, zone, pts = op
            zone.points = pts
            self.message = "undid move"

    def delete_selected(self) -> None:
        if self.mode != "edit" or self.selected == -1:
            self.message = "nothing selected"
            return
        zone = self.zones.pop(self.selected)
        self._undo.append(("delete", self.zones, self.selected, zone))
        self.message = f"deleted {zone.zone_name or 'zone'}"
        self.selected = min(self.selected, len(self.zones) - 1)

    # -- render state --------------------------------------------------------

    def preview_polygon(self) -> list[Point] | None:
        """The in-progress shape to render, tracking the mouse."""
        if self.mode != "draw" or not self.pending:
            return None
        cursor = self.snap_indicator or self.cursor
        if self.dim_stage == DIM_OFF:
            pts = list(self.pending)
            if cursor is not None and len(pts) < 4:
                pts.append(cursor)
            return pts
        fpp = self.ft_per_px()
        origin = self.pending[0]
        if fpp is None or cursor is None:
            return [origin]
        if self.dim_stage == DIM_LENGTH1:
            u = geometry.unit_vector(origin, cursor)
            if u is None:
                return [origin]
            length = self._buffer_ft()
            if length is None:  # no number yet: rubber-band to the mouse
                return [origin, cursor]
            return [origin, (origin[0] + u[0] * length / fpp,
                             origin[1] + u[1] * length / fpp)]
        # DIM_LENGTH2: frozen first side, live extrusion
        length2 = self._buffer_ft()
        if length2 is None:  # follow the mouse's perpendicular distance
            u = self.dim_dir
            length2_px = abs((cursor[0] - origin[0]) * -u[1] +
                             (cursor[1] - origin[1]) * u[0])
            if length2_px <= 0:
                length2_px = 1e-6
        else:
            length2_px = length2 / fpp
        return geometry.dimensioned_rect(origin, self.dim_dir,
                                         self.dim_length1_ft / fpp, length2_px,
                                         cursor)

    def _buffer_ft(self) -> float | None:
        try:
            v = float(self.dim_buffer)
            return v if v > 0 else None
        except ValueError:
            return None

    def status(self) -> str:
        parts = [f"mode: {self.mode}", f"snap: {'ON' if self.snap_enabled else 'off'}"]
        if self.mode == "draw":
            if self.dim_stage == DIM_LENGTH1:
                parts.append(f"side 1 (ft): {self.dim_buffer}_  [aim with mouse, Enter]")
            elif self.dim_stage == DIM_LENGTH2:
                parts.append(f"side 1 = {self.dim_length1_ft:g} ft | "
                             f"side 2 (ft): {self.dim_buffer}_  [mouse picks side, Enter]")
            elif self.pending:
                parts.append(f"corner {len(self.pending) + 1}/4"
                             + ("  [or type a length]" if len(self.pending) == 1 else ""))
            else:
                parts.append("click a corner (type digits after the 1st for a dimensioned rect)")
        else:
            if self.selected != -1 and self.selected < len(self.zones):
                z = self.zones[self.selected]
                parts.append(f"selected: {z.zone_name or f'#{self.selected + 1}'}"
                             "  [drag body/corner, Ctrl-drag copies, arrows nudge,"
                             " x deletes, n/b cycles]")
            else:
                parts.append("click a zone to select")
        if self.message:
            parts.append(self.message)
        return " | ".join(parts)


class CenterlineController:
    """Draw/edit a single approach centerline — station 0 at the first
    point (the stop bar), stations increasing upstream (see
    ``model/templates.py``'s setback convention). Pure python, no NiceGUI
    imports; the live station/offset readout wraps the current points in a
    `model.geometry.Centerline` (`current()`).

    Interaction is deliberately minimal: a click either grabs an existing
    vertex (within `handle_radius`) or appends a new one at the end, and
    either way the same mouse-down/drag/up gesture can then reposition it
    before release. Undo is whole-list snapshots rather than
    `DrawingController`'s op stack — this is a single small polyline, not a
    collection of zones.
    """

    def __init__(self, ft_per_px: Callable[[], float | None]):
        self.ft_per_px = ft_per_px
        self.points: list[Point] = []
        self.cursor: Point | None = None
        self.selected: int = -1
        self.handle_radius = 10.0  # vertex grab radius, world px; GUI rescales on zoom
        self._dragging = False
        self._undo: list[list[Point]] = []
        self.message = ""

    def current(self) -> "geometry.Centerline | None":
        try:
            return geometry.Centerline(self.points)
        except ValueError:
            return None

    def _snapshot(self) -> None:
        self._undo.append(list(self.points))

    def _hit_vertex(self, p: Point) -> int:
        for i, pt in enumerate(self.points):
            if geometry.dist(p, pt) <= self.handle_radius:
                return i
        return -1

    # -- mouse -----------------------------------------------------------------

    def mouse_down(self, p: Point) -> None:
        self.message = ""
        i = self._hit_vertex(p)
        self._snapshot()
        if i != -1:
            self.selected = i
        else:
            self.points.append(p)
            self.selected = len(self.points) - 1
        self._dragging = True

    def mouse_move(self, p: Point, dragging: bool = False) -> None:
        self.cursor = p
        if dragging and self._dragging and self.selected != -1:
            self.points[self.selected] = p

    def mouse_up(self, p: Point) -> None:
        self._dragging = False

    def end_drag(self) -> None:
        """Release an in-progress vertex drag without a matching mouse_up
        (e.g. the toolbar switches away from the Centerline tool mid-drag)."""
        self._dragging = False

    # -- keyboard ----------------------------------------------------------------

    def key(self, name: str, ctrl: bool = False) -> bool:
        self.message = ""
        if name in ("x", "Delete"):
            return self.delete_selected()
        if name == "u" or (ctrl and name == "z"):
            self.undo()
            return True
        if name == "Escape" and self.selected != -1:
            self.selected = -1
            return True
        return False

    def delete_selected(self) -> bool:
        if not (0 <= self.selected < len(self.points)):
            self.message = "select a vertex to delete"
            return False
        self._snapshot()
        self.points.pop(self.selected)
        self.selected = min(self.selected, len(self.points) - 1)
        self.message = "deleted vertex"
        return True

    def undo(self) -> None:
        if not self._undo:
            self.message = "nothing to undo"
            return
        self.points = self._undo.pop()
        self.selected = min(self.selected, len(self.points) - 1)
        self.message = "undid centerline edit"

    # -- render state / readout ---------------------------------------------------

    def station_readout(self, p: Point) -> str | None:
        """Live 'station NNN ft, offset NN ft L/R' for *p*, or None until
        there are enough points for a datum."""
        c = self.current()
        if c is None:
            return None
        station, offset = c.project(p)
        fpp = self.ft_per_px()
        if fpp is None:
            return f"station {station:.1f} px, offset {offset:+.1f} px"
        side = "R" if offset >= 0 else "L"
        return f"station {station * fpp:.1f} ft, offset {abs(offset) * fpp:.1f} ft {side}"

    def status(self) -> str:
        if not self.points:
            return ("mode: centerline | click the stop bar to start "
                    "(station 0), then click upstream")
        parts = [f"mode: centerline | {len(self.points)} point"
                 + ("s" if len(self.points) != 1 else "")]
        parts.append("click to extend, drag a vertex to reshape, x deletes selected")
        if self.message:
            parts.append(self.message)
        return " | ".join(parts)
