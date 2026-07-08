"""Draw/edit state machine for zone loops — pure python, no GUI imports.

Ported from the interaction model of pyatspm's ``video/calibrate.py`` (free
polygon loops, snap toggle, edit mode with drag/Ctrl-drag-copy, undo),
upgraded with the dimensioned-rectangle workflow: click a corner, aim with
the mouse, type the two side lengths in feet. Free polygon draw takes any
number of corners and commits on an explicit finish — Enter, or the GUI's
double-click via `finish_polygon()` (ROADMAP Item 7); only 2-click segments
auto-commit at a fixed count.

Phase 3.2a generalizes the controller along two axes (PHASE3_UI_PLAN §4/§6):

* **Draw kinds** — a `DrawKind` descriptor bundles what differs between
  element kinds (factory, slot-insertion, placeholder test, polygon vs
  2-click segment shape) so the same click/snap/dimension/undo machinery
  draws event zones, ignore zones, and generic lineals. `retarget` switches
  both the live list and the kind; the undo stack survives because every op
  carries the list it touched.
* **Multi-select** — `selection` (ordered index list) plus `anchor` (the
  primary member) replace the single index; `selected` remains as a
  compatibility property. Group move/nudge/delete reuse the existing
  ``("batch", …)`` undo entry. Shift-click toggles membership (Ctrl-drag
  still copies); `marquee_select` takes a rubber-band rectangle.

Phase 3.2c adds `selection_centroid`/`rotate_selection`: the pivot seed and
the batch-undo commit for the GUI's 2-click rotate workflow (the click
tracking and live preview angle live in `gui/app.py`, alongside the other
Edit-tool sub-interactions like the marquee).

The controller operates entirely in world-pixel coordinates (y-down); the
GUI converts mouse events before feeding them in and renders from the state
exposed here (``pending``, ``preview_polygon()``, ``snap_indicator``,
``selected``/``selection``, ``status()``, ``warning``). Feet enter only
through the ``ft_per_px`` supplier, so an uncalibrated background simply
disables dimensioned draw.
"""

from __future__ import annotations

import copy
import itertools
import re
from dataclasses import dataclass, field
from typing import Callable

from model import domain, geometry
from model.bands import Owner
from model.iprj_io import EventZone, Lineal, Point, TextLabel

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


def bulk_reassign(source_zones: list, selection, *, phase: int | None = None,
                  output_delta: int = 0, target_zones: list | None = None) -> list:
    """Apply a bulk edit to the zones at *selection* indices of *source_zones*
    (ROADMAP Item 26); returns the edited zone objects in selection order so
    the caller can re-select them (their indices may shift after a move).

    - *phase*: set every selected zone's ``phase_number`` (None leaves it).
    - *output_delta*: add to each zone's ``output_number``, clamped at 0 — a
      relative nudge (+1 / -1), never a set-to-N.
    - *target_zones*: when given and not *source_zones*, move each selected
      zone into it (identity-pop from source + `insert_zone`), which routes a
      sensor change between the _1_2/_3_4 files exactly as the single-zone
      Properties move does. Fields not named are left untouched."""
    edited = [source_zones[i] for i in selection if 0 <= i < len(source_zones)]
    for z in edited:
        if phase is not None:
            z.phase_number = int(phase)
        if output_delta:
            z.output_number = max(0, (z.output_number or 0) + output_delta)
    if target_zones is not None and target_zones is not source_zones:
        for z in edited:
            for i, s in enumerate(source_zones):
                if s is z:
                    del source_zones[i]
                    break
            insert_zone(target_zones, z)
    return edited


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


def element_points(el) -> list[Point]:
    """The editable vertex list of any drawable element. A `Lineal` stores
    its two endpoints as scalar fields; a `TextLabel` is anchored at a single
    point; everything else carries `.points`."""
    if isinstance(el, Lineal):
        return [p for p in (el.point_0, el.point_1) if p is not None]
    if isinstance(el, TextLabel):
        return [(el.position_x, el.position_y)]
    return el.points


def set_element_points(el, pts: list[Point]) -> None:
    if isinstance(el, Lineal):
        el.point_0, el.point_1 = pts[0], pts[1]
    elif isinstance(el, TextLabel):
        el.position_x, el.position_y = pts[0]
    else:
        el.points = pts


def _element_name(el) -> str:
    if isinstance(el, TextLabel):
        return (el.text or "").strip() or "text label"
    return getattr(el, "zone_name", "") or \
        ("lineal" if isinstance(el, Lineal) else "zone")


# -- band ownership (ROADMAP Item 22) -----------------------------------------
# Generic lineals and text labels are project-wide but route to a sensor file
# by index band (model/bands.py). The GUI carries that intent as a transient
# `_owner` attribute on the working object — no on-disk tag; save materializes
# it into a band. Zones need none (they live in a sensor's list already).

def element_owner(el) -> Owner:
    return getattr(el, "_owner", Owner.GENERAL)


def set_element_owner(el, owner: Owner) -> None:
    el._owner = owner


# Text-label styling fields a draw-time draft carries onto a placed label
# (ROADMAP Item 22 — the Draw-mode editor bar); the anchor is the click point.
_LABEL_DRAFT_FIELDS = (
    "text", "font_size", "font_bold", "font_italic", "font_underline",
    "rotation_angle", "textcolor_red", "textcolor_green", "textcolor_blue")


def _apply_label_draft(label: TextLabel, draft: TextLabel) -> None:
    """Copy the draft's text/styling onto *label*, leaving its position."""
    for f in _LABEL_DRAFT_FIELDS:
        setattr(label, f, getattr(draft, f))


@dataclass(frozen=True)
class DrawKind:
    """Draw-target descriptor (PHASE3_UI_PLAN §4.1): everything that differs
    between element kinds, leaving the controller's interaction machinery
    untouched. ``make`` receives the committed points plus a 1-based ordinal
    (count of real elements + 1) for default naming; ``insert`` is the
    slot-else-append helper and may raise ValueError at the vendor cap,
    which the controller surfaces via ``warning``."""

    name: str                                   # "loop" | "ignore" | "lineal" | "text label"
    shape: str                                  # "polygon" (free multi-click/dim) | "segment" (2-click) | "point" (1-click)
    make: Callable[[list[Point], int], object]
    insert: Callable[[list, object], int]
    is_placeholder: Callable[[object], bool]
    numbered: bool = False                      # assign next_output on commit/copy
    # Generic lineals share the iprj Lineal pool with centerline chains: an
    # endpoint coincident with any other lineal/centerline vertex merges into
    # a chain on reload (model/domain.py), so their kind must never snap.
    snappable: bool = True
    # Project-wide, band-owned kinds (generic lineals, text labels): the
    # controller stamps a fresh element's `_owner` from its owner_supplier on
    # commit so a re-save routes it to the right sensor file (ROADMAP Item 22).
    owned: bool = False
    style: dict = field(default_factory=dict)   # render hints for the GUI svg()


LOOP_KIND = DrawKind(
    name="loop", shape="polygon",
    make=lambda pts, seq: EventZone(enable=1, zone_name=f"Zone {seq}",
                                    points=pts),
    insert=insert_zone, is_placeholder=is_placeholder, numbered=True,
    style={})  # phase-colored fill — the GUI's existing zone rendering

IGNORE_KIND = DrawKind(
    name="ignore zone", shape="polygon",
    make=lambda pts, seq: domain.new_ignore_zone(pts, name=f"Ignore {seq}"),
    insert=domain.insert_ignore_zone,
    is_placeholder=domain.is_placeholder_ignore,
    style={"stroke": "#ffd54f", "dash": "6 4"})  # yellow dashed, per svg()

LINEAL_KIND = DrawKind(
    name="lineal", shape="segment",
    make=lambda pts, seq: domain.new_lineal(pts[0], pts[1]),
    insert=domain.insert_lineal, is_placeholder=domain.is_placeholder_lineal,
    snappable=False, owned=True,
    style={"stroke": "#9e9e9e", "width": 1})  # thin gray ≠ centerline green

LABEL_KIND = DrawKind(
    name="text label", shape="point",
    make=lambda pts, seq: domain.new_label(pts[0], f"Label {seq}"),
    insert=domain.insert_label, is_placeholder=domain.is_placeholder_label,
    snappable=False, owned=True,
    style={"fill": "#ffd54f"})  # amber text ≠ zone name labels (white)


class DrawingController:
    """Mutates a live element list (a sensor's zones, its ignore zones, or
    the project lineal pool — per the active `DrawKind`) in world px."""

    def __init__(self, zones: list,
                 ft_per_px: Callable[[], float | None],
                 next_output: Callable[[], int] | None = None,
                 kind: DrawKind = LOOP_KIND,
                 owner_supplier: Callable[[], Owner] | None = None,
                 label_draft: Callable[[], TextLabel] | None = None,
                 on_commit: Callable[[object], None] | None = None):
        self.zones = zones
        self.ft_per_px = ft_per_px
        self.next_output = next_output
        self.kind = kind
        # Supplies the band Owner stamped onto a freshly drawn owned element
        # (ROADMAP Item 22); None leaves owner unset (defaults to GENERAL).
        self.owner_supplier = owner_supplier
        # Supplies the draft TextLabel whose text/styling a click adopts when
        # placing a text label (the Draw-mode editor bar); the clicked point
        # is the anchor. None -> the kind's own `make` default is kept.
        self.label_draft = label_draft
        # Called with each freshly committed element after it lands in the list
        # (ROADMAP Item 27): the GUI uses it to give a drawn event zone the
        # centerline membership picked in the CL dropdown. Bulk placements
        # (`insert_many`) and Edit-mode copies bypass it — they own their own
        # membership handling.
        self.on_commit = on_commit

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

        self.selection: list[int] = []    # selected indices, in selection order
        self.anchor = -1                  # primary/last-clicked member
        self._drag_vertex: int | None = None
        self._drag_body: dict | None = None
        self._nudging = False         # coalesces an arrow-key burst into one undo op
        # ops carry the zones list they touched, so undo works across sensor
        # retargets: ("add", zones, zone) | ("replace", zones, i, old, new) |
        # ("delete", zones, i, zone) | ("points", zone, pts) |
        # ("batch", [sub_op, ...]) — a bulk insert (e.g. a template) or a
        # group move/delete undone as one step, in reverse sub_op order
        self._undo: list[tuple] = []
        self.message = ""             # transient feedback for the status line
        self.warning = ""             # cap/guard errors the GUI should notify

    # -- selection -------------------------------------------------------------

    @property
    def selected(self) -> int:
        """Compatibility view of the selection: its anchor, or -1."""
        return self.anchor if self.selection else -1

    @property
    def dragging(self) -> bool:
        """Whether a vertex or body drag is in progress — the GUI's signal
        (PHASE3_UI_PLAN §5/§6.2) that an Edit-tool mouse-down landed on
        something, so an empty-canvas drag is a marquee instead."""
        return self._drag_vertex is not None or self._drag_body is not None

    @selected.setter
    def selected(self, i: int) -> None:
        if i is None or i < 0:
            self.selection, self.anchor = [], -1
        else:
            self.selection, self.anchor = [i], i

    def toggle_select(self, i: int) -> None:
        """Shift-click: toggle *i* in/out of the selection set."""
        if i in self.selection:
            self.selection.remove(i)
            if self.anchor == i:
                self.anchor = self.selection[-1] if self.selection else -1
        else:
            self.selection.append(i)
            self.anchor = i

    def select_many(self, indices: list[int], additive: bool = False) -> None:
        """Replace (or, *additive*, extend) the selection; the last index
        becomes the anchor."""
        if not additive:
            self.selection = []
        for i in indices:
            if i not in self.selection:
                self.selection.append(i)
        if self.selection:
            self.anchor = self.selection[-1]
        else:
            self.anchor = -1

    def marquee_select(self, corner_a: Point, corner_b: Point,
                       additive: bool = False) -> list[int]:
        """Select every enabled element whose geometry touches the
        rubber-band rectangle; returns the hit indices."""
        hits = [i for i in self._real_indices()
                if self.zones[i].enable and geometry.polygon_intersects_rect(
                    element_points(self.zones[i]), corner_a, corner_b)]
        self.select_many(hits, additive)
        return hits

    # -- helpers -------------------------------------------------------------

    def _polygons(self) -> list[list[Point]]:
        return [element_points(z) for z in self.zones]

    def _real_indices(self) -> list[int]:
        return [i for i, z in enumerate(self.zones)
                if not self.kind.is_placeholder(z)]

    def _snapped(self, p: Point, exclude: int | None = None) -> Point:
        self.snap_indicator = None
        if not self.snap_enabled or not self.kind.snappable:
            return p
        target = geometry.find_snap(p, self._polygons(), self.snap_radius, exclude)
        if target is not None:
            self.snap_indicator = target
            return target
        return p

    def _commit_element(self, points: list[Point]) -> None:
        pts = [(float(x), float(y)) for x, y in points]
        el = self.kind.make(pts, len(self._real_indices()) + 1)
        if isinstance(el, TextLabel) and self.label_draft is not None:
            _apply_label_draft(el, self.label_draft())
        if self.kind.numbered and self.next_output is not None:
            el.output_number = self.next_output()
        if self.kind.owned and self.owner_supplier is not None:
            set_element_owner(el, self.owner_supplier())
        if self._insert(el) == -1:
            return  # vendor cap; warning already set
        name = getattr(el, "zone_name", "") or self.kind.name
        out = getattr(el, "output_number", 0)
        self.message = f"placed {name}" + (f" (output {out})" if out else "")
        if self.on_commit is not None:
            self.on_commit(el)

    def _insert(self, el) -> int:
        """Insert via the kind's slot-else-append helper, recording the undo
        op; returns the index used, or -1 (with ``warning`` set) when the
        vendor cap rejects it."""
        zones = self.zones
        slot = next((i for i, z in enumerate(zones)
                     if self.kind.is_placeholder(z)), None)
        old = zones[slot] if slot is not None else None
        try:
            idx = self.kind.insert(zones, el)
        except ValueError as exc:  # vendor cap (10 ignore / 100 lineals)
            self.message = self.warning = str(exc)
            return -1
        if idx == slot:
            self._undo.append(("replace", zones, idx, old, el))
        else:
            self._undo.append(("add", zones, el))
        return idx

    def insert_many(self, zones: list[EventZone]) -> list[int]:
        """Insert every zone in *zones* (placeholder slot else append, same
        rule as `_insert`) as one undoable operation: a single `undo()` call
        removes all of them, restoring any placeholder slots they took over.
        Used for bulk placements (e.g. an approach template) so undo doesn't
        require one press per detector."""
        sub_ops: list[tuple] = []
        indices = []
        for zone in zones:
            for i, z in enumerate(self.zones):
                if self.kind.is_placeholder(z):
                    sub_ops.append(("replace", self.zones, i, z, zone))
                    self.zones[i] = zone
                    indices.append(i)
                    break
            else:
                self.zones.append(zone)
                sub_ops.append(("add", self.zones, zone))
                indices.append(len(self.zones) - 1)
        self._undo.append(("batch", sub_ops))
        return indices

    def _reset_dim(self) -> None:
        self.dim_stage = DIM_OFF
        self.dim_buffer = ""
        self.dim_length1_ft = 0.0
        self.dim_dir = None

    def _hit_zone(self, p: Point) -> int:
        for i in range(len(self.zones) - 1, -1, -1):  # topmost first
            z = self.zones[i]
            if not z.enable:
                continue
            pts = element_points(z)
            if len(pts) >= 3 and \
                    geometry.polygon_hit(p, pts, self.handle_radius / 2):
                return i
            if len(pts) == 2 and geometry.point_segment_distance(
                    p, pts[0], pts[1]) <= self.handle_radius / 2:
                return i
            if len(pts) == 1 and geometry.dist(p, pts[0]) <= self.handle_radius:
                return i
        return -1

    # -- mouse ---------------------------------------------------------------

    def mouse_down(self, p: Point, ctrl: bool = False, shift: bool = False) -> None:
        self.message = ""
        self.warning = ""
        self._nudging = False
        if self.mode == "draw":
            if self.dim_stage != DIM_OFF:
                return  # dimensions are committed with Enter, not clicks
            self.pending.append(self._snapped(p))
            # points commit on the first click, segments on the second;
            # polygons keep accepting corners until finish_polygon()
            # (Enter/double-click).
            fixed = {"point": 1, "segment": 2}.get(self.kind.shape)
            if fixed is not None and len(self.pending) == fixed:
                self._commit_element(self.pending)
                self.pending = []
        elif self.mode == "edit":
            if self.selected != -1 and not shift:
                zone = self.zones[self.selected]
                pts = element_points(zone)
                for i, pt in enumerate(pts):
                    if geometry.dist(p, pt) <= self.handle_radius:
                        self._drag_vertex = i
                        self._undo.append(("points", zone, list(pts)))
                        return
            hit = self._hit_zone(p)
            if hit == -1:
                return
            if shift:
                self.toggle_select(hit)
                return
            if ctrl:
                zone = copy.deepcopy(self.zones[hit])
                if getattr(zone, "zone_name", None) is not None:
                    zone.zone_name = bumped_name(zone.zone_name)
                if self.kind.numbered and self.next_output is not None:
                    zone.output_number = self.next_output()
                idx = self._insert(zone)
                if idx == -1:
                    return  # vendor cap; warning already set
                self.selected = idx
                self._drag_body = {"anchor": p,
                                   "orig": {idx: list(element_points(zone))}}
                return
            if hit in self.selection and len(self.selection) > 1:
                # group drag: keep the set, re-anchor on the grabbed member
                self.anchor = hit
                orig = {i: list(element_points(self.zones[i]))
                        for i in self.selection}
                self._undo.append(("batch", [("points", self.zones[i], list(o))
                                             for i, o in orig.items()]))
            else:
                self.selected = hit
                orig = {hit: list(element_points(self.zones[hit]))}
                self._undo.append(("points", self.zones[hit], list(orig[hit])))
            self._drag_body = {"anchor": p, "orig": orig}

    def mouse_move(self, p: Point, dragging: bool = False) -> None:
        self.cursor = p
        if self.mode == "draw":
            # live snap indicator for the next click / preview vertex
            self._snapped(p)
        elif self.mode == "edit" and dragging:
            if self._drag_vertex is not None and self.selected != -1:
                zone = self.zones[self.selected]
                pts = list(element_points(zone))
                pts[self._drag_vertex] = self._snapped(p, self.selected)
                set_element_points(zone, pts)
            elif self._drag_body is not None:
                dx = p[0] - self._drag_body["anchor"][0]
                dy = p[1] - self._drag_body["anchor"][1]
                for i, orig in self._drag_body["orig"].items():
                    set_element_points(self.zones[i],
                                       [(x + dx, y + dy) for x, y in orig])

    def mouse_up(self, p: Point) -> None:
        if self._drag_vertex is not None:
            self._drag_vertex = None
        elif self._drag_body is not None:
            # snap-on-release stays single-zone; a group already moved as one
            if self.snap_enabled and self.kind.snappable \
                    and len(self._drag_body["orig"]) == 1 and self.selected != -1:
                zone = self.zones[self.selected]
                pts = element_points(zone)
                corr = geometry.translation_to_snap(
                    pts, self._polygons(), self.snap_radius, self.selected)
                if corr is not None:
                    set_element_points(
                        zone, [(x + corr[0], y + corr[1]) for x, y in pts])
            self._drag_body = None
        self.snap_indicator = None

    # -- keyboard ------------------------------------------------------------

    def key(self, name: str, ctrl: bool = False) -> bool:
        """Handle a key press; returns True if it changed anything.

        Mode/tool accelerators (`d`/`l`/`e`/`z`/`i`…) are handled at the app
        level per PHASE3_UI_PLAN §2.1 — the controller no longer owns any
        set-mode shortcut. `v` is the edit-mode insert-vertex action."""
        self.message = ""
        self.warning = ""
        if name not in ARROWS:
            self._nudging = False
        if name == "g":
            self.snap_enabled = not self.snap_enabled
            if not self.snap_enabled:
                self.snap_indicator = None
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
        # dimension entry starts by typing a digit after the first corner
        # (the old `d` trigger is gone — `d` is the Draw tool accelerator,
        # PHASE3_UI_PLAN §2.1) and only for polygon kinds: a segment is two
        # clicks, no dimensions.
        starts_dim = name.isdigit() and len(name) == 1 \
            and self.kind.shape == "polygon"
        if self.dim_stage == DIM_OFF:
            if name == "Enter":
                return self.finish_polygon()
            if not starts_dim or len(self.pending) != 1:
                if starts_dim and not self.pending:
                    self.message = "click the first corner before typing dimensions"
                    return True
                return False
            if self.ft_per_px() is None:
                self.message = "calibrate the background before dimensioned draw"
                return True
            self.dim_stage = DIM_LENGTH1
            self.dim_buffer = name
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
        self._commit_element(rect)
        self.pending = []
        self._reset_dim()
        return True

    def _key_edit(self, name: str) -> bool:
        if name == "v":
            self.insert_vertex()
            return True
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
        """Move the selection one small step; a burst of arrow presses
        coalesces into a single undo op (single zone or group batch)."""
        targets = [self.zones[i] for i in self.selection if i < len(self.zones)]
        if not targets:
            return False
        fpp = self.ft_per_px()
        step = NUDGE_FT / fpp if fpp else 2.0  # world px
        if not (self._nudging and self._undo
                and self._same_nudge_op(self._undo[-1], targets)):
            if len(targets) == 1:
                self._undo.append(
                    ("points", targets[0], list(element_points(targets[0]))))
            else:
                self._undo.append(("batch", [
                    ("points", z, list(element_points(z))) for z in targets]))
        self._nudging = True
        for zone in targets:
            set_element_points(zone, [(x + ux * step, y + uy * step)
                                      for x, y in element_points(zone)])
        unit = f"{NUDGE_FT:g} ft" if fpp else f"{step:g} px"
        self.message = f"nudged {unit}" if len(targets) == 1 \
            else f"nudged {len(targets)} zones {unit}"
        return True

    @staticmethod
    def _same_nudge_op(op: tuple, targets: list) -> bool:
        """Whether *op* is the undo entry an in-progress nudge burst of
        *targets* wrote — the coalescing test."""
        if len(targets) == 1:
            return op[0] == "points" and op[1] is targets[0]
        return (op[0] == "batch" and len(op[1]) == len(targets)
                and all(sub[0] == "points" and sub[1] is z
                        for sub, z in zip(op[1], targets)))

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

    def record_points_undo(self, zone, old_points: list[Point]) -> None:
        """Push a ``("points", zone, old_points)`` undo entry for an edit
        made outside this controller (e.g. `CenterlineController.move_attached`
        re-stationing a zone from a dialog) — same shape `_nudge`/`_undo_one`
        already use, so `undo()` restores it exactly as it would a drag."""
        self._undo.append(("points", zone, list(old_points)))

    def retarget(self, zones: list, kind: DrawKind | None = None) -> None:
        """Point the controller at another element list (active-sensor
        switch, or a draw-kind switch when *kind* is given). In-progress
        interactions and the selection reset; the undo stack survives
        because each op carries the list it touched."""
        self.zones = zones
        if kind is not None:
            self.kind = kind
        self.pending = []
        self._reset_dim()
        self._drag_vertex = None
        self._drag_body = None
        self._nudging = False
        self.snap_indicator = None
        self.selected = -1

    def finish_polygon(self) -> bool:
        """Commit the pending free-draw polygon — the explicit finish for
        ROADMAP Item 7. Enter routes here from `_key_draw`; the GUI's
        double-click handler calls it directly. The double-click's own two
        clicks land as pending points before the dblclick event arrives, so
        trailing points coincident with their predecessor (within half the
        vertex grab radius — GUI-rescaled on zoom like the hit tests) are
        dropped before committing. Fewer than 3 surviving corners leaves the
        draw pending with a message. Segments (2-click auto-commit) and
        dimension entry (Enter commits via `_commit_dimension`) never reach
        here. Returns True if it handled the gesture."""
        if self.mode != "draw" or self.kind.shape != "polygon" \
                or self.dim_stage != DIM_OFF or not self.pending:
            return False
        self.message = ""
        self.warning = ""
        pts = list(self.pending)
        tol = self.handle_radius / 2
        while len(pts) >= 2 and geometry.dist(pts[-1], pts[-2]) <= tol:
            pts.pop()
        if len(pts) < 3:
            self.message = f"a {self.kind.name} needs at least 3 corners"
            return True
        self._commit_element(pts)
        self.pending = []
        self.snap_indicator = None
        return True

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
        if op[0] == "batch":
            _, sub_ops = op
            for sub in reversed(sub_ops):
                self._undo_one(sub)
            kinds = {sub[0] for sub in sub_ops}
            if kinds == {"points"}:
                self.message = f"undid group move of {len(sub_ops)} zones"
            elif kinds == {"delete"}:
                self.message = f"restored {len(sub_ops)} zones"
            else:
                self.message = f"undid placement of {len(sub_ops)} zones"
        else:
            self._undo_one(op)

    def _undo_one(self, op: tuple) -> None:
        if op[0] == "add":
            _, zones, zone = op
            idx = next((i for i, z in enumerate(zones) if z is zone), None)
            if idx is None:
                self.message = "nothing to undo"
                return
            zones.pop(idx)
            if zones is self.zones and self.selected >= len(zones):
                self.selected = len(zones) - 1
            self.message = f"undid add of {_element_name(zone)}"
        elif op[0] == "replace":
            _, zones, idx, old, new = op
            if idx < len(zones) and zones[idx] is new:
                zones[idx] = old
            if zones is self.zones and self.selected == idx:
                self.selected = -1
            self.message = f"undid add of {_element_name(new)}"
        elif op[0] == "delete":
            _, zones, idx, zone = op
            zones.insert(idx, zone)
            if zones is self.zones:
                self.selected = idx
            self.message = f"restored {_element_name(zone)}"
        elif op[0] == "points":
            _, zone, pts = op
            set_element_points(zone, pts)
            self.message = "undid move"

    def delete_selected(self) -> None:
        if self.mode != "edit" or not self.selection:
            self.message = "nothing selected"
            return
        if len(self.selection) == 1:
            idx = self.selection[0]
            zone = self.zones.pop(idx)
            self._undo.append(("delete", self.zones, idx, zone))
            self.message = f"deleted {_element_name(zone)}"
            self.selected = min(idx, len(self.zones) - 1)
            return
        # group delete: high index first so recorded indices stay valid;
        # batch undo replays reversed, restoring low-to-high
        sub_ops = []
        for idx in sorted(self.selection, reverse=True):
            if idx >= len(self.zones):
                continue
            zone = self.zones.pop(idx)
            sub_ops.append(("delete", self.zones, idx, zone))
        self._undo.append(("batch", sub_ops))
        self.message = f"deleted {len(sub_ops)} zones"
        self.selected = -1

    def insert_vertex(self, p: Point | None = None) -> bool:
        """Insert a vertex into the single selected element, on the edge
        nearest *p* (default: the current cursor) — the Edit-tool `v`
        action (ROADMAP Item 5). One undoable "points" op; like any manual
        vertex edit, the GUI should `reproject` a centerline-attached zone
        afterward. Lineals store exactly two endpoints and are refused.
        Returns True if a vertex was added."""
        self.message = ""
        self.warning = ""
        self._nudging = False
        if self.mode != "edit" or len(self.selection) != 1 \
                or self.selection[0] >= len(self.zones):
            self.message = "select a single zone to add a vertex"
            return False
        zone = self.zones[self.selection[0]]
        if isinstance(zone, Lineal):
            self.message = "a lineal has fixed endpoints — can't add a vertex"
            return False
        if isinstance(zone, TextLabel):
            self.message = "a text label is a single point — can't add a vertex"
            return False
        if p is None:
            p = self.cursor
        if p is None:
            self.message = "point at an edge to add a vertex"
            return False
        pts = list(element_points(zone))
        if len(pts) < 2:
            self.message = "select a single zone to add a vertex"
            return False
        self._undo.append(("points", zone, list(pts)))
        idx, new_pt = geometry.nearest_edge_insertion(p, pts)
        pts.insert(idx, new_pt)
        set_element_points(zone, pts)
        self.message = f"added vertex to {_element_name(zone)}"
        return True

    def selection_centroid(self) -> Point | None:
        """Combined-points centroid of every selected element — the pivot
        seed shown before the user clicks to place one (PHASE3_UI_PLAN
        §6.4). None with nothing selected."""
        pts = [p for i in self.selection if i < len(self.zones)
               for p in element_points(self.zones[i])]
        return geometry.polygon_centroid(pts) if pts else None

    def rotate_selection(self, angle_deg: float, pivot: Point) -> list:
        """Rotate every selected element's points by *angle_deg* about
        *pivot* (model.geometry conventions) as one batch undo op. Returns
        the rotated elements so the GUI can detach any that were following
        a centerline — a hand-rotate breaks the exact station/offset fit an
        attachment relies on (PHASE3_UI_PLAN §6.4). A near-zero angle (two
        clicks with no mouse movement between them) is a no-op: nothing is
        touched and the empty return tells the caller there's nothing to
        detach either."""
        targets = [self.zones[i] for i in self.selection if i < len(self.zones)]
        if not targets or abs(angle_deg) < 1e-9:
            return []
        self._undo.append(("batch", [("points", z, list(element_points(z)))
                                     for z in targets]))
        for z in targets:
            set_element_points(
                z, geometry.rotate_points(element_points(z), angle_deg, pivot))
        self.message = f"rotated {len(targets)} element" \
            + ("" if len(targets) == 1 else "s")
        return targets

    # -- render state --------------------------------------------------------

    def preview_polygon(self) -> list[Point] | None:
        """The in-progress shape to render, tracking the mouse."""
        if self.mode != "draw" or not self.pending:
            return None
        cursor = self.snap_indicator or self.cursor
        if self.dim_stage == DIM_OFF:
            pts = list(self.pending)
            # segments cap at 2 points; a free polygon rubber-bands forever
            if cursor is not None and \
                    (self.kind.shape != "segment" or len(pts) < 2):
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
            if self.kind.shape == "point":
                parts.append(f"click to place a {self.kind.name}")
            elif self.kind.shape == "segment":
                parts.append("click the end point" if self.pending
                             else f"click the start point of a {self.kind.name}")
            elif self.dim_stage == DIM_LENGTH1:
                parts.append(f"side 1 (ft): {self.dim_buffer}_  [aim with mouse, Enter]")
            elif self.dim_stage == DIM_LENGTH2:
                parts.append(f"side 1 = {self.dim_length1_ft:g} ft | "
                             f"side 2 (ft): {self.dim_buffer}_  [mouse picks side, Enter]")
            elif self.pending:
                n = len(self.pending)
                hint = "  [or type a length]" if n == 1 else \
                    "  [Enter/double-click finishes]" if n >= 3 else ""
                parts.append(f"corner {n + 1}{hint}")
            else:
                parts.append("click a corner (type digits after the 1st for a dimensioned rect)")
        elif len(self.selection) > 1:
            parts.append(f"selected: {len(self.selection)} zones"
                         "  [drag moves all, arrows nudge, x deletes,"
                         " Shift-click toggles]")
        elif self.selected != -1 and self.selected < len(self.zones):
            z = self.zones[self.selected]
            name = getattr(z, "zone_name", "") or f"#{self.selected + 1}"
            parts.append(f"selected: {name}"
                         "  [drag body/corner, Ctrl-drag copies, arrows nudge,"
                         " x deletes, n/b cycles]")
        else:
            parts.append("click a zone to select")
        if self.message:
            parts.append(self.message)
        return " | ".join(parts)


# Tolerance (world px) for recognizing an engine-placed zone on open: the
# vendor format rounds coordinates to 2 decimals (≤0.005 px per coordinate,
# ≤ ~0.02 px through a projection), while hand-drawn slop is a screen pixel
# or more. 0.05 sits an order of magnitude above one and below the other.
ATTACH_TOL = 0.05


def _corner_candidates(p: Point, datum, tol: float) -> list[tuple[float, float]]:
    """All (station, offset) readings of *p*, one per datum segment whose
    reading ``locate`` confirms. ``project`` alone returns only the globally
    nearest reading, which is the wrong one for a corner on the concave
    side of a bend (e.g. a decision zone straddling the vertex)."""
    cands = []
    pts, stations = datum.points, datum.stations
    for i in range(len(pts) - 1):
        tx, ty = geometry.unit_vector(pts[i], pts[i + 1])
        dx, dy = p[0] - pts[i][0], p[1] - pts[i][1]
        s = stations[i] + dx * tx + dy * ty
        nx, ny = geometry.offset_normal((tx, ty))
        off = dx * nx + dy * ny
        if geometry.dist(datum.point_at(s, off), p) <= tol:
            cands.append((s, off))
    return cands


def _is_so_rectangle(so, tol: float) -> bool:
    """Exactly two distinct stations x two distinct offsets, one corner in
    each quadrant — the signature of an engine-placed detector."""
    ss = sorted(s for s, _ in so)
    oo = sorted(o for _, o in so)
    if ss[1] - ss[0] > tol or ss[3] - ss[2] > tol \
            or oo[1] - oo[0] > tol or oo[3] - oo[2] > tol:
        return False  # not two clean pairs
    if ss[2] - ss[1] <= tol or oo[2] - oo[1] <= tol:
        return False  # degenerate (zero length or width)
    s_mid, o_mid = (ss[1] + ss[2]) / 2, (oo[1] + oo[2]) / 2
    return len({(s > s_mid, o > o_mid) for s, o in so}) == 4


def station_offset_rectangle(points, datum, tol: float = ATTACH_TOL):
    """Per-corner (station, offset) if *points* is a station/offset-aligned
    rectangle on *datum* (see `_is_so_rectangle`) — trying every combination
    of per-segment corner readings (a few at most), so zones straddling a
    bend are recognized too. Returns None for anything hand-drawn."""
    if len(points) != 4:
        return None
    cands = [_corner_candidates(p, datum, tol) for p in points]
    if any(not c for c in cands):
        return None
    for so in itertools.product(*cands):
        if _is_so_rectangle(so, tol):
            return list(so)
    return None


def derive_attachments(centerlines, zone_lists) -> int:
    """Re-attach zones that look engine-placed along one of *centerlines*.

    Session 7.5 attachments are session-local (the .iprj format has nowhere
    to carry them), so on project open this reconstructs them: a zone that
    is an exact station/offset rectangle on a centerline was almost
    certainly placed along it — and a user who drew one that precisely by
    hand gets the re-stationing they would expect anyway. A zone matching
    several centerlines (e.g. parallel datums) attaches to the laterally
    nearest. Returns the number of zones attached.

    ROADMAP Item 26 makes membership explicit and persisted (membership
    labels), so this geometric derivation is now a backward-compat fallback:
    zones already attached (by a membership label re-parse) are skipped, and
    the GUI only runs this at all when the loaded project carries no
    membership labels (a pre-Item-26 file)."""
    datums = [(cl, cl.current()) for cl in centerlines]
    already = {k for cl in centerlines for k in cl.attached}
    n = 0
    for zones in zone_lists:
        for z in zones:
            if is_placeholder(z) or not z.enable or id(z) in already:
                continue
            best = None
            for cl, datum in datums:
                if datum is None:
                    continue
                so = station_offset_rectangle(z.points, datum)
                if so is None:
                    continue
                off = min(abs(o) for _, o in so)
                if best is None or off < best[0]:
                    best = (off, cl, so)
            if best is not None:
                best[1].attach(z, best[2])
                n += 1
    return n


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

    Session 7.5: zones placed along this centerline register here via
    `attach` (their per-corner station/offset from
    `model.templates.place_detectors_on_centerline`); every geometry edit
    re-stations them (`restation`), so attached detectors follow the
    curve as it is reshaped — including through undo, since zone points are
    purely derived from (points, attachment coords). The GUI calls
    `reproject` after manual zone edits so a hand-adjusted zone keeps its
    adjusted station/offset instead of snapping back. Which zones are attached
    (the membership) is persisted explicitly since ROADMAP Item 26 — as a
    `"name: slots"` text label (each member's (sensor, zone-index) slot)
    re-parsed on load and re-attached by projection, no geometry matching. The
    per-corner station/offset itself is not stored: it is re-derived from the
    live geometry on load. `derive_attachments`
    (geometric guessing) survives only as a fallback for pre-Item-26 files with
    no membership label.
    """

    def __init__(self, ft_per_px: Callable[[], float | None]):
        self.ft_per_px = ft_per_px
        # Display name (Item 20) — e.g. "N_CL" for the north approach. Empty
        # means "unnamed"; the GUI falls back to C{n}. Persisted (Item 22) as
        # a no-rotation text label at the far end, carried by `name_label`;
        # re-derived on load via model.labels.match_name_labels.
        self.name: str = ""
        # The managed centerline-name TextLabel in the GUI's label pool
        # (ROADMAP Item 22), or None until the centerline is named. Its band
        # follows `owner`; the GUI keeps its text/position in sync.
        self.name_label: "TextLabel | None" = None
        # The managed centerline-membership TextLabel (ROADMAP Item 26): a
        # top-left "name: slots" label persisting which zones belong to this
        # centerline, or None until it has a name and members. Band follows
        # `owner` like the name label; the GUI syncs its text before save.
        self.membership_label: "TextLabel | None" = None
        # File band this centerline (and its name label) is written to on the
        # two-file split (ROADMAP Item 21/22): GENERAL -> both files.
        self.owner: Owner = Owner.GENERAL
        self.points: list[Point] = []
        self.cursor: Point | None = None
        self.selected: int = -1
        self.handle_radius = 10.0  # vertex grab radius, world px; GUI rescales on zoom
        self._dragging = False
        self._undo: list[list[Point]] = []
        # id(zone) -> (zone, per-corner (station, offset) in world px)
        self.attached: dict[int, tuple[EventZone, list[tuple[float, float]]]] = {}
        self.message = ""

    def current(self) -> "geometry.Centerline | None":
        try:
            return geometry.Centerline(self.points)
        except ValueError:
            return None

    def far_end(self) -> Point | None:
        """The vertex furthest from the stop bar (station 0 is ``points[0]``)
        — where the centerline-name label sits (ROADMAP Item 22)."""
        return self.points[-1] if self.points else None

    def _snapshot(self) -> None:
        self._undo.append(list(self.points))

    def _hit_vertex(self, p: Point) -> int:
        for i, pt in enumerate(self.points):
            if geometry.dist(p, pt) <= self.handle_radius:
                return i
        return -1

    # -- attached zones (Session 7.5) ------------------------------------------

    def attach(self, zone: EventZone, corners_so: list[tuple[float, float]]) -> None:
        """Register *zone* as placed at *corners_so* (per-corner
        station/offset, world px) so centerline edits re-station it."""
        self.attached[id(zone)] = (zone, [tuple(c) for c in corners_so])

    def attach_projected(self, zone: EventZone) -> bool:
        """Make *zone* a member of this centerline (ROADMAP Item 26),
        deriving its per-corner station/offset from the current datum by
        projection — the explicit-membership equivalent of the geometric
        `derive_attachments`, but it accepts any zone shape, not only an exact
        station/offset rectangle. Returns False (no change) when there is no
        valid datum yet."""
        c = self.current()
        if c is None:
            return False
        self.attach(zone, [c.project(p) for p in zone.points])
        return True

    def detach(self, zone: EventZone) -> bool:
        """Drop *zone*'s membership if present; returns whether it was a
        member (ROADMAP Item 26)."""
        return self.attached.pop(id(zone), None) is not None

    def member_zones(self) -> list[EventZone]:
        """The zones currently attached to this centerline (ROADMAP Item 26).
        Membership is persisted by each zone's (sensor, zone-index) slot, which
        only the project knows, so the slot lookup lives in the GUI
        (`Viewer.member_slots`); the controller just owns the set."""
        return [zone for zone, _ in self.attached.values()]

    def restation(self) -> None:
        """Recompute every attached zone's points from its stored
        station/offset corners — called after any centerline geometry
        change. With fewer than two distinct points there is no datum, so
        zones stay put until the centerline is valid again."""
        c = self.current()
        if c is None:
            return
        for zone, corners in self.attached.values():
            zone.points = [c.point_at(s, off) for s, off in corners]

    def reproject(self) -> None:
        """Re-derive stored station/offset corners from each attached
        zone's current points — the GUI calls this after manual zone edits
        (drag/nudge/undo) so the adjustment sticks through later centerline
        edits. Zones whose points still match their stored corners keep
        the exact placement coordinates (`project` can differ minutely from
        the placed values near corners and past the ends)."""
        c = self.current()
        if c is None:
            return
        for key, (zone, corners) in self.attached.items():
            if len(zone.points) == len(corners) and all(
                    geometry.dist(p, c.point_at(s, off)) < 1e-6
                    for p, (s, off) in zip(zone.points, corners)):
                continue
            self.attached[key] = (zone, [c.project(p) for p in zone.points])

    def zone_station(self, zone: EventZone) -> float | None:
        """Station (world px) of *zone*'s downstream edge — the minimum
        corner station, i.e. the setback edge nearest the stop bar (the
        same edge `model.templates.DetectorSpec.setback_ft` measures to).
        None if *zone* isn't attached here."""
        entry = self.attached.get(id(zone))
        if entry is None:
            return None
        return min(s for s, _ in entry[1])

    def move_attached(self, zone: EventZone, *, station: float | None = None,
                      delta: float | None = None) -> list[Point] | None:
        """Re-station *zone* along the centerline — the typed/precise
        equivalent of a manual drag + `reproject`. Exactly one of *station*
        (absolute, measured at the zone's downstream edge per
        `zone_station`) or *delta* (relative; positive = upstream, matching
        the station direction) must be given, both in world px — the GUI
        converts feet via `ft_per_px` before calling.

        Every stored corner shifts by the same station amount with offsets
        unchanged, so the zone keeps its shape in station/offset space and
        follows any bends. Returns the zone's previous points so the caller
        can record a ``("points", zone, old)`` undo op on the
        `DrawingController` stack; None if *zone* isn't attached or the
        centerline has no valid datum."""
        if (station is None) == (delta is None):
            raise ValueError("give exactly one of station= or delta=")
        entry = self.attached.get(id(zone))
        c = self.current()
        if entry is None or c is None:
            return None
        _, corners = entry
        if station is not None:
            delta = station - min(s for s, _ in corners)
        old = list(zone.points)
        new_corners = [(s + delta, off) for s, off in corners]
        self.attached[id(zone)] = (zone, new_corners)
        zone.points = [c.point_at(s, off) for s, off in new_corners]
        return old

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
            self.restation()
        self._dragging = True

    def mouse_move(self, p: Point, dragging: bool = False) -> None:
        self.cursor = p
        if dragging and self._dragging and self.selected != -1:
            self.points[self.selected] = p
            self.restation()

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
        self.restation()
        self.message = "deleted vertex"
        return True

    def undo(self) -> None:
        if not self._undo:
            self.message = "nothing to undo"
            return
        self.points = self._undo.pop()
        self.selected = min(self.selected, len(self.points) - 1)
        self.restation()
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
