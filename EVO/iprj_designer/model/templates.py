"""Approach-template schema and JSON I/O (ROADMAP Session 6, Phase 4.1).

An ApproachTemplate captures the reusable settings a traffic engineer would
fill in for one intersection approach: lane geometry, design speed, and the
detector rows to place.

Phase 4.1 rebuilt the schema around a hybrid "math seeds flexible defaults"
model:

* The template's editable source of truth is its ``detectors`` list of
  `TemplateDetector` rows (kind, spanned lanes, length, setback, output
  offset, phase role). `seed_detectors` fills that list with ITE-kinematic
  defaults — including a chain of advance detectors sized for *continuous
  dilemma-zone coverage* from ``extension_time_s`` — but expansion only ever
  reads what is stored, so a user override (Phase 4.2 grid editor, or the
  JSON itself) fully replaces the computed value. The math is a smart
  baseline, never a placement-time constraint.
* ``direction`` / ``thru_phase`` / ``lt_phase`` / ``base_output`` may each be
  a baked literal **or** a placeholder (``None`` = "prompt at placement",
  resolved from a `PlacementContext`). Output numbering is Base + Offset:
  each row stores ``output_offset`` and the assigned output is
  ``base_output + output_offset`` (output-only numbering — the unit's output
  channel maps 1:1 to the controller input it drives; see the 2026-07-03
  decisions-log entry).
* Lateral offsets are measured from the approach's **anchor lane line**
  (Station 0's lateral origin), defaulting to the lane line between the
  leading exclusive left-turn lanes and the thru lanes — see
  `default_anchor_lane_line`. Lanes left of the anchor get negative offsets.

Session 6.2's expansion/placement pipeline is unchanged in shape:
`expand_template` -> `DetectorSpec`s in the approach-local frame, then
`place_detectors` (straight, Session 6.2) or `place_detectors_on_centerline`
(curvilinear, Session 7.5) map them to world coordinates. Nothing here
imports GUI code.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Sequence

from .geometry import Centerline
from .iprj_io import Point

# Lane movement is one or more of these letters, e.g. "T", "L", "TR".
MOVEMENT_CHARS = "LTR"

# Compass direction of the approach itself (e.g. "N" = the approach on the
# north side of the intersection, which carries southbound traffic) — not
# the direction traffic travels. Naming convention (SB/NB/EB/WB prefixes)
# is derived from this in expansion.
DIRECTIONS = ("N", "S", "E", "W")

# Detector kinds the seeder generates and the auto-namer knows.
# `TemplateDetector` accepts other kind strings; they get a generic name.
DETECTOR_KINDS = ("count", "stop_bar", "dilemma", "advance")

# Template fields that may be placeholders: None on the template means
# "prompt at placement", filled from a PlacementContext; a present value is
# a baked literal that placement never overrides.
PLACEHOLDER_FIELDS = ("direction", "thru_phase", "lt_phase", "base_output")


def _validate_movement(movement: str) -> str:
    m = (movement or "").upper()
    if not m or any(c not in MOVEMENT_CHARS for c in m):
        raise ValueError(
            f"lane movement must be one or more of {list(MOVEMENT_CHARS)}, got {movement!r}")
    return m


def _validate_phase(phase: int | str) -> int | str:
    """A row phase is the role "thru"/"lt" (resolved at placement) or a
    literal controller phase number."""
    if phase in ("thru", "lt"):
        return phase
    if isinstance(phase, bool) or not isinstance(phase, (int, float)) \
            or int(phase) != phase:
        raise ValueError(f'detector phase must be "thru", "lt", or an integer, '
                         f"got {phase!r}")
    return int(phase)


@dataclass
class Lane:
    movement: str  # e.g. "L", "T", "TR" -- one or more of MOVEMENT_CHARS
    width_ft: float = 12.0
    advance_detector: bool = True  # seeding input: lane-by-lane toggle

    def __post_init__(self):
        self.movement = _validate_movement(self.movement)


@dataclass
class TemplateDetector:
    """One detector row of a template (Phase 4.1 schema).

    Rows are the editable source of truth for expansion: `seed_detectors`
    fills them with kinematic defaults, and any stored value — hand-edited
    JSON or the Phase 4.2 grid editor — fully replaces the computed one.
    """
    kind: str  # "count" | "stop_bar" | "dilemma" | "advance" | custom
    spanning_lanes: list[int]  # 0-based lane indices, contiguous, left→right
    length_ft: float  # along travel
    setback_ft: float  # stop bar -> downstream edge, positive upstream
    output_offset: int  # assigned output = Base Output + this
    phase: int | str = "thru"  # "thru" | "lt" role, or a literal phase number

    def __post_init__(self):
        span = [int(i) for i in self.spanning_lanes]
        if not span:
            raise ValueError("spanning_lanes must name at least one lane")
        if span[0] < 0 or span != list(range(span[0], span[0] + len(span))):
            raise ValueError("spanning_lanes must be contiguous ascending "
                             f"0-based lane indices, got {self.spanning_lanes!r}")
        self.spanning_lanes = span
        if self.length_ft <= 0:
            raise ValueError(f"detector length must be positive, got {self.length_ft!r}")
        self.output_offset = int(self.output_offset)
        self.phase = _validate_phase(self.phase)


# Continuous dilemma-zone coverage (Phase 4.1)
# --------------------------------------------
# Advance detection must hold the thru phase continuously from the first
# advance detector all the way into the dilemma-zone detector: after a
# vehicle at design speed leaves a detector, the controller carries the call
# another ``extension_time_s`` (the detection-channel extension / passage
# gap), during which the vehicle travels v * t_ext. Coverage is continuous
# when the clear gap between one detector's downstream edge and the next
# detector's upstream edge never exceeds that carry distance:
#
#     gap_max = v * t_ext
#
# `advance_setbacks_ft` therefore chains advance detectors downstream from
# the safe stopping distance at a pitch of (length + v * t_ext) until the
# remaining gap to the dilemma detector's upstream edge is within gap_max —
# one detector at low speeds (45 mph needs two at the 1.0 s default).
# DEFAULT_EXTENSION_TIME_S = 1.0 s is a typical detection-channel extension
# for advance loops; it's a per-template field (``extension_time_s``), and
# like every seeded number the resulting setbacks land in editable schema
# rows rather than being recomputed at placement.
DEFAULT_EXTENSION_TIME_S = 1.0


@dataclass
class ApproachTemplate:
    schema_version: int = 2
    name: str = "New approach"
    speed_mph: float = 45.0
    extension_time_s: float = DEFAULT_EXTENSION_TIME_S
    lanes: list[Lane] = field(default_factory=lambda: [Lane("T")])
    count_loops: bool = True  # seeding input: place a count loop per lane
    # Placeholder-able fields (PLACEHOLDER_FIELDS): None = prompt at placement.
    direction: str | None = None
    thru_phase: int | None = None
    lt_phase: int | None = None
    base_output: int | None = None
    # Station 0's lateral origin as a lane-line index (line i is the left
    # edge of lanes[i]; len(lanes) is the right edge of the last lane).
    # None = the default_anchor_lane_line rule.
    anchor_lane_line: int | None = None
    # Detector rows; empty = expand seeded defaults (see seed_detectors).
    detectors: list[TemplateDetector] = field(default_factory=list)

    def __post_init__(self):
        if self.direction is not None and self.direction not in DIRECTIONS:
            raise ValueError(f"direction must be one of {DIRECTIONS} or None "
                             f"(prompt at placement), got {self.direction!r}")
        if not self.lanes:
            raise ValueError("template must have at least one lane")
        if self.extension_time_s <= 0:
            raise ValueError(f"extension_time_s must be positive, "
                             f"got {self.extension_time_s!r}")
        if self.anchor_lane_line is not None and \
                not 0 <= self.anchor_lane_line <= len(self.lanes):
            raise ValueError(f"anchor_lane_line must be 0..{len(self.lanes)}, "
                             f"got {self.anchor_lane_line!r}")
        for det in self.detectors:
            if det.spanning_lanes[-1] >= len(self.lanes):
                raise ValueError(f"{det.kind!r} detector spans lane "
                                 f"{det.spanning_lanes[-1]} but the template has "
                                 f"only {len(self.lanes)} lanes")


@dataclass
class PlacementContext:
    """Placement-time values for a template's placeholder fields (the
    Phase 4.3 placement prompt fills one of these). Only fields the
    template leaves as None are read; baked literals always win."""
    direction: str | None = None
    thru_phase: int | None = None
    lt_phase: int | None = None
    base_output: int | None = None


def lane_config_str(lanes: list[Lane]) -> str:
    """Compact display form, e.g. "12'L | 12'T | 12'T | 12'R"."""
    return " | ".join(f"{lane.width_ft:g}'{lane.movement}" for lane in lanes)


def template_to_dict(t: ApproachTemplate) -> dict:
    return asdict(t)


def template_from_dict(d: dict) -> ApproachTemplate:
    lanes = [Lane(**lane) for lane in d.get("lanes", [])]
    detectors = [TemplateDetector(**row) for row in d.get("detectors", [])]
    # Ignore unknown keys so legacy/foreign templates still load (notably the
    # retired `starting_input`); `schema_version` is not passed through — the
    # in-memory object is always current-schema, upgraded on load.
    known = {f.name for f in fields(ApproachTemplate)} \
        - {"lanes", "detectors", "schema_version"}
    kwargs = {k: v for k, v in d.items() if k in known}
    # v1 compat: `starting_output` was the baked first output number; with
    # seeded offsets running 0, 1, 2, ... it maps exactly onto the Base
    # Output literal.
    if "base_output" not in d and d.get("starting_output") is not None:
        kwargs["base_output"] = int(d["starting_output"])
    return ApproachTemplate(lanes=lanes, detectors=detectors, **kwargs)


def load_template(path: str | Path) -> ApproachTemplate:
    return template_from_dict(json.loads(Path(path).read_text()))


def save_template(template: ApproachTemplate, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(template_to_dict(template), indent=2) + "\n")


# ---------------------------------------------------------------------------
# Anchor point (Phase 4.1) — Station 0's lateral origin
# ---------------------------------------------------------------------------

def lane_line_offsets_ft(lanes: Sequence[Lane]) -> list[float]:
    """Lateral position of each lane line measured from the leftmost lane's
    left edge: len(lanes) + 1 values, line i = left edge of lanes[i]."""
    xs = [0.0]
    for lane in lanes:
        xs.append(xs[-1] + lane.width_ft)
    return xs


def default_anchor_lane_line(lanes: Sequence[Lane]) -> int:
    """Default Station-0 anchor: the lane line between the exclusive
    left-turn lanes and the thru lanes — the right side of the last lane in
    the leading block of movement-"L" lanes (0, the leftmost lane's left
    edge, when the approach has no leading exclusive LT lane)."""
    n = 0
    for lane in lanes:
        if lane.movement != "L":
            break
        n += 1
    return n


def anchor_lane_line_index(template: ApproachTemplate) -> int:
    """The template's anchor lane line: the explicit override if set, else
    the default rule."""
    if template.anchor_lane_line is not None:
        return template.anchor_lane_line
    return default_anchor_lane_line(template.lanes)


# ---------------------------------------------------------------------------
# Kinematics — ITE distances that seed the default rows
# ---------------------------------------------------------------------------
#
# Approach-local frame
# --------------------
# Expansion lays detectors out in an abstract approach frame:
#
# * ``setback_ft`` — signed distance from the stop bar to the detector edge
#   nearest the intersection, measured positive *upstream* (into the
#   approach, toward oncoming traffic). The detector extends ``length_ft``
#   further upstream from that edge. Negative setbacks are past the stop
#   bar: a count loop at -15 spans 10–15 ft beyond the bar (counting
#   departures), a 30 ft stop-bar zone at -5 straddles the bar, covering
#   25 ft of approach.
# * ``lateral_offset_ft`` — from the anchor lane line (see
#   `default_anchor_lane_line`) to the detector's left edge, increasing
#   toward the driver's right; lanes left of the anchor sit at negative
#   offsets. (Before Phase 4.1 the origin was the leftmost lane's left
#   edge — the anchor generalizes it.)
#
# ITE kinematic seeding
# ---------------------
# Speeds convert as v [ft/s] = speed_mph * 5280/3600.
#
# Advance detection starts at the ITE safe stopping distance — the farthest
# point from which a driver alerted at the detector can still stop
# comfortably at the stop bar:
#
#     SSD = v * t_pr + v^2 / (2 * a)
#
# with t_pr = 1.0 s perception-reaction time (the ITE Traffic Detector
# Handbook detection-design value, not AASHTO's 2.5 s geometric-design PRT)
# and a = 10.0 ft/s^2 comfortable deceleration (~3.0 m/s^2).
# 45 mph -> 283.8 ft.
#
# The dilemma-zone detector's downstream edge sits at the downstream end of
# the ITE indecision zone — 2.5 s of travel from the stop bar, the point by
# which ~90% of drivers are committed to proceed:
#
#     d_dz = v * 2.5 s
#
# 45 mph -> 165.0 ft.
#
# Between those two, `advance_setbacks_ft` chains advance detectors for
# continuous coverage (see the DEFAULT_EXTENSION_TIME_S block above).
#
# Which rows `seed_detectors` generates (offset order 0, 1, 2, ...):
#
# 1. Count loops (if ``count_loops``): 5 ft x lane width per lane, -15 ft.
# 2. Stop-bar zones: 30 ft x lane width per lane, -5 ft.
# 3. Dilemma zone (if any thru lane): 20 ft long, spanning from the first
#    thru lane to the last (any non-thru lane sandwiched between is
#    spanned too).
# 4. Advance detectors: 10 ft x lane width per chain setback (upstream row
#    first), per thru lane whose ``advance_detector`` toggle is on (the
#    toggle is ignored on turn-only lanes — advance/dilemma detection
#    extends the thru phase).
#
# Phase roles: a lane is "lt" only when its movement is exactly "L"; every
# other lane (T, R, and shared TR/LT lanes) is "thru".

FT_PER_S_PER_MPH = 5280.0 / 3600.0

# ITE kinematic assumptions (see block comment above)
PERCEPTION_REACTION_TIME_S = 1.0
COMFORTABLE_DECEL_FT_S2 = 10.0
DILEMMA_ZONE_END_TRAVEL_TIME_S = 2.5

# Fixed default detector geometry (ft) — lengths are along travel
COUNT_LOOP_LENGTH_FT = 5.0
COUNT_LOOP_SETBACK_FT = -15.0
STOP_BAR_LENGTH_FT = 30.0
STOP_BAR_SETBACK_FT = -5.0
DILEMMA_LENGTH_FT = 20.0
ADVANCE_LENGTH_FT = 10.0

# Approach side -> travel-direction naming prefix (a north approach carries
# southbound traffic).
TRAFFIC_DIRECTION = {"N": "SB", "S": "NB", "E": "WB", "W": "EB"}


def safe_stopping_distance_ft(speed_mph: float) -> float:
    """ITE safe stopping distance: v*t_pr + v^2/(2a) (see module notes)."""
    v = speed_mph * FT_PER_S_PER_MPH
    return v * PERCEPTION_REACTION_TIME_S + v * v / (2.0 * COMFORTABLE_DECEL_FT_S2)


def advance_setback_ft(speed_mph: float) -> float:
    """The first (upstream-most) advance detector sits at the safe stopping
    distance."""
    return safe_stopping_distance_ft(speed_mph)


def dilemma_setback_ft(speed_mph: float) -> float:
    """Downstream end of the indecision zone: 2.5 s of travel."""
    return speed_mph * FT_PER_S_PER_MPH * DILEMMA_ZONE_END_TRAVEL_TIME_S


def advance_setbacks_ft(
    speed_mph: float,
    extension_time_s: float = DEFAULT_EXTENSION_TIME_S,
    detector_length_ft: float = ADVANCE_LENGTH_FT,
) -> list[float]:
    """Advance-detector setback chain for continuous dilemma-zone coverage.

    Starts at the safe stopping distance and steps downstream by
    ``detector_length_ft + v * extension_time_s`` (so each clear gap equals
    the distance the extension carries a call at design speed) until the
    remaining gap to the dilemma detector's upstream edge is bridged by the
    extension. Upstream-most first."""
    v = speed_mph * FT_PER_S_PER_MPH
    hold_ft = v * extension_time_s
    dz_upstream_edge = dilemma_setback_ft(speed_mph) + DILEMMA_LENGTH_FT
    setbacks = [safe_stopping_distance_ft(speed_mph)]
    while setbacks[-1] - dz_upstream_edge > hold_ft:
        setbacks.append(setbacks[-1] - (detector_length_ft + hold_ft))
    return setbacks


def seed_detectors(template: ApproachTemplate) -> list[TemplateDetector]:
    """ITE-kinematic default rows for a template (the Phase 4.1 seeding).

    Reads ``lanes``, ``speed_mph``, ``extension_time_s`` and the
    ``count_loops`` / per-lane ``advance_detector`` toggles; returns rows
    with output offsets 0..n-1 in generation order. The result is meant to
    be *stored and edited* (the Phase 4.2 grid editor materializes it onto
    ``template.detectors``); `expand_template` also falls back to it when
    the detectors list is empty. It never overrides stored rows."""
    lanes = template.lanes
    rows: list[TemplateDetector] = []

    def add(kind: str, span: list[int], length: float, setback: float,
            phase: int | str) -> None:
        rows.append(TemplateDetector(kind=kind, spanning_lanes=span,
                                     length_ft=length, setback_ft=setback,
                                     output_offset=len(rows), phase=phase))

    def lane_phase(lane: Lane) -> str:
        return "lt" if lane.movement == "L" else "thru"

    if template.count_loops:
        for i, lane in enumerate(lanes):
            add("count", [i], COUNT_LOOP_LENGTH_FT, COUNT_LOOP_SETBACK_FT,
                lane_phase(lane))
    for i, lane in enumerate(lanes):
        add("stop_bar", [i], STOP_BAR_LENGTH_FT, STOP_BAR_SETBACK_FT,
            lane_phase(lane))
    thru_idx = [i for i, lane in enumerate(lanes) if "T" in lane.movement]
    if thru_idx:
        add("dilemma", list(range(thru_idx[0], thru_idx[-1] + 1)),
            DILEMMA_LENGTH_FT, dilemma_setback_ft(template.speed_mph), "thru")
        for setback in advance_setbacks_ft(template.speed_mph,
                                           template.extension_time_s):
            for i in thru_idx:
                if lanes[i].advance_detector:
                    add("advance", [i], ADVANCE_LENGTH_FT, setback, "thru")
    return rows


# ---------------------------------------------------------------------------
# Template expansion — detector rows -> placed detector list
# ---------------------------------------------------------------------------

@dataclass
class DetectorSpec:
    """One detector in the approach-local frame (conventions above)."""
    kind: str  # "count" | "stop_bar" | "dilemma" | "advance" | custom
    name: str
    output_number: int
    phase: int
    length_ft: float  # along travel
    width_ft: float  # across lanes
    setback_ft: float  # stop bar -> downstream edge, positive upstream
    lateral_offset_ft: float  # anchor lane line -> detector's left edge


@dataclass
class PlacedDetector:
    spec: DetectorSpec
    points: list[Point]  # 4 corners in world coordinates (y-down), drawing order
    # Per-corner (station, offset) in the placement centerline's coordinates
    # (world units, same order as ``points``) when placed curvilinearly —
    # the attachment record that lets a centerline edit re-station the zone.
    corners_so: list[tuple[float, float]] | None = None


def _numbered(base_names: list[str]) -> list[str]:
    """Append " 1", " 2", ... to names that occur more than once (in
    order), leaving unique names bare — "SBT Count 1" but "SBL Count"."""
    totals = Counter(base_names)
    seen: Counter[str] = Counter()
    out = []
    for name in base_names:
        if totals[name] > 1:
            seen[name] += 1
            name = f"{name} {seen[name]}"
        out.append(name)
    return out


def _detector_rows(template: ApproachTemplate) -> list[TemplateDetector]:
    return template.detectors if template.detectors else seed_detectors(template)


def missing_placeholders(
    template: ApproachTemplate,
    context: PlacementContext | None = None,
) -> list[str]:
    """The placeholder fields expansion would still need, in
    PLACEHOLDER_FIELDS order — what the Phase 4.3 placement prompt must ask
    for. Usage-aware: a phase role is only required if some detector row
    actually carries it; direction (naming) and base_output (numbering) are
    always required."""
    ctx = context or PlacementContext()
    roles = {row.phase for row in _detector_rows(template)}
    needed = {"direction", "base_output"} \
        | ({"thru_phase"} if "thru" in roles else set()) \
        | ({"lt_phase"} if "lt" in roles else set())
    return [f for f in PLACEHOLDER_FIELDS if f in needed
            and getattr(template, f) is None and getattr(ctx, f) is None]


def _resolve_placeholders(
    template: ApproachTemplate,
    context: PlacementContext | None,
) -> tuple[str, int | None, int | None, int]:
    missing = missing_placeholders(template, context)
    if missing:
        raise ValueError("template needs placement values for: "
                         + ", ".join(missing))
    ctx = context or PlacementContext()

    def pick(name: str):
        value = getattr(template, name)  # a baked literal always wins
        return value if value is not None else getattr(ctx, name)

    direction = pick("direction")
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}, got {direction!r}")
    return direction, pick("thru_phase"), pick("lt_phase"), int(pick("base_output"))


def _movement_label(lanes: Sequence[Lane], span: Sequence[int]) -> str:
    """Movement letters of the spanned lanes, deduplicated in order —
    "T" for a thru lane (or several), "LT" for a shared/merged span."""
    return "".join(dict.fromkeys(c for i in span for c in lanes[i].movement))


def _base_name(kind: str, prefix: str, label: str, phase: int) -> str:
    if kind == "count":
        return f"{prefix}{label} Count"
    if kind == "stop_bar":
        return f"Ph {phase} {prefix}{label} Stop Bar"
    if kind == "dilemma":
        return f"Ph {phase} Dilemma"
    if kind == "advance":
        return f"Ph {phase} Advance"
    return f"Ph {phase} {prefix}{label} {kind.replace('_', ' ').title()}"


def expand_template(
    template: ApproachTemplate,
    context: PlacementContext | None = None,
) -> list[DetectorSpec]:
    """Expand a template's detector rows into specs in the approach-local
    frame, with auto-generated names.

    Reads the stored ``detectors`` rows (falling back to `seed_detectors`
    when the list is empty), resolves placeholder fields from ``context``
    (raising ValueError naming any still missing — see
    `missing_placeholders`), assigns each output as ``base_output +
    output_offset``, and measures lateral offsets from the anchor lane
    line."""
    rows = _detector_rows(template)
    direction, thru_phase, lt_phase, base_output = \
        _resolve_placeholders(template, context)
    prefix = TRAFFIC_DIRECTION[direction]
    line_x = lane_line_offsets_ft(template.lanes)
    anchor_x = line_x[anchor_lane_line_index(template)]

    def phase_of(row: TemplateDetector) -> int:
        if row.phase == "thru":
            return thru_phase
        if row.phase == "lt":
            return lt_phase
        return row.phase

    names = _numbered([
        _base_name(row.kind, prefix,
                   _movement_label(template.lanes, row.spanning_lanes),
                   phase_of(row))
        for row in rows])
    return [
        DetectorSpec(kind=row.kind, name=name,
                     output_number=base_output + row.output_offset,
                     phase=phase_of(row), length_ft=row.length_ft,
                     width_ft=line_x[row.spanning_lanes[-1] + 1]
                     - line_x[row.spanning_lanes[0]],
                     setback_ft=row.setback_ft,
                     lateral_offset_ft=line_x[row.spanning_lanes[0]] - anchor_x)
        for row, name in zip(rows, names)
    ]


def place_detectors(
    specs: list[DetectorSpec],
    stop_bar_ref: Point,
    upstream_dir: Point,
    units_per_ft: float = 1.0,
) -> list[PlacedDetector]:
    """Place specs in world coordinates (y-down, like the iprj file).

    ``stop_bar_ref`` is the point where the stop bar crosses the template's
    anchor lane line — the lateral-offset origin of the specs (by default
    the line between the exclusive-left block and the thru lanes; lanes
    left of it carry negative offsets). ``upstream_dir`` points upstream,
    away from the intersection (any nonzero length). With y-down
    coordinates the driver's-right lateral axis is (u_y, -u_x); in a y-up
    frame left/right would mirror. ``units_per_ft`` converts feet to the
    caller's coordinate unit (e.g. pass px-per-ft to place in world px).
    """
    ux, uy = upstream_dir
    norm = math.hypot(ux, uy)
    if norm <= 0:
        raise ValueError("upstream_dir must have nonzero length")
    ux, uy = ux / norm, uy / norm
    rx, ry = uy, -ux  # driver's right, y-down

    def corner(lateral_ft: float, upstream_ft: float) -> Point:
        return (stop_bar_ref[0] + (rx * lateral_ft + ux * upstream_ft) * units_per_ft,
                stop_bar_ref[1] + (ry * lateral_ft + uy * upstream_ft) * units_per_ft)

    placed = []
    for s in specs:
        l0, l1 = s.lateral_offset_ft, s.lateral_offset_ft + s.width_ft
        g0, g1 = s.setback_ft, s.setback_ft + s.length_ft
        placed.append(PlacedDetector(spec=s, points=[
            corner(l0, g0), corner(l1, g0), corner(l1, g1), corner(l0, g1)]))
    return placed


def expand_and_place(
    template: ApproachTemplate,
    stop_bar_ref: Point,
    upstream_dir: Point,
    units_per_ft: float = 1.0,
    context: PlacementContext | None = None,
) -> list[PlacedDetector]:
    """One-call form for the GUI: expand, then place (see both functions)."""
    return place_detectors(expand_template(template, context), stop_bar_ref,
                           upstream_dir, units_per_ft)


# ---------------------------------------------------------------------------
# Curvilinear placement (Session 7.5) — place along a centerline datum
# ---------------------------------------------------------------------------
#
# Instead of extruding the approach-local frame along one straight upstream
# vector, each detector corner is mapped to a (station, offset) on a
# `model.geometry.Centerline` and located there, so far-upstream detectors
# follow the approach's curvature and every corner takes its orientation
# from the local segment direction.
#
# Sign mapping between the two frames (both y-down):
#
# * The centerline is drawn stop bar first (station 0) and upstream from
#   there, so ``setback_ft`` (positive upstream) adds directly to station.
# * `Centerline` offsets are positive to the right of *increasing station*
#   — the upstream direction — which is the driver's LEFT (the driver
#   travels downstream). ``lateral_offset_ft`` grows toward the driver's
#   right, so it *subtracts* from offset.
#
# The anchor reference point is projected onto the centerline; detectors
# are laid out relative to that projection, so the click keeps its
# straight-placement meaning (where the stop bar crosses the anchor lane
# line) and the centerline itself may be drawn anywhere across the
# approach. Stations past the drawn end extrapolate along the terminal
# segment (`Centerline` behavior), so a datum drawn a little short still
# places the advance detectors.


def place_detectors_on_centerline(
    specs: list[DetectorSpec],
    centerline_points: Sequence[Point],
    stop_bar_ref: Point,
    units_per_ft: float = 1.0,
) -> list[PlacedDetector]:
    """Place specs along a centerline datum (conventions above).

    ``centerline_points`` is the datum polyline in world coordinates,
    station 0 at the stop bar; ``stop_bar_ref`` is the same reference point
    as `place_detectors` takes. Returned detectors carry ``corners_so`` so
    the caller can re-station them after later centerline edits.
    """
    cl = Centerline(centerline_points)
    s_ref, off_ref = cl.project(stop_bar_ref)

    placed = []
    for s in specs:
        l0, l1 = s.lateral_offset_ft, s.lateral_offset_ft + s.width_ft
        g0, g1 = s.setback_ft, s.setback_ft + s.length_ft
        corners_so = [
            (s_ref + g * units_per_ft, off_ref - l * units_per_ft)
            for l, g in ((l0, g0), (l1, g0), (l1, g1), (l0, g1))]
        placed.append(PlacedDetector(
            spec=s,
            points=[cl.point_at(st, off) for st, off in corners_so],
            corners_so=corners_so))
    return placed


def expand_and_place_on_centerline(
    template: ApproachTemplate,
    centerline_points: Sequence[Point],
    stop_bar_ref: Point,
    units_per_ft: float = 1.0,
    context: PlacementContext | None = None,
) -> list[PlacedDetector]:
    """One-call curvilinear form for the GUI: expand, then place along the
    centerline (see both functions)."""
    return place_detectors_on_centerline(expand_template(template, context),
                                         centerline_points, stop_bar_ref,
                                         units_per_ft)
