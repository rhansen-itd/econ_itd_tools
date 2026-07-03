"""Approach-template schema and JSON I/O (see ROADMAP Session 6).

An ApproachTemplate captures the reusable inputs a traffic engineer would
fill in for one intersection approach: lane geometry, design speed, which
detectors to place, where numbering/phases start.

Session 6.2 (below the schema section) expands a template into a placed
detector list with ITE kinematic distances — see the "Template expansion"
section for the formulas and coordinate conventions. Session 6.3 wires the
expansion into the canvas; Session 7.5 adds the curvilinear variant that
places along a `model.geometry.Centerline` datum instead of one straight
upstream vector. Nothing here imports GUI code.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

from .geometry import Centerline
from .iprj_io import Point

# Lane movement is one or more of these letters, e.g. "T", "L", "TR".
MOVEMENT_CHARS = "LTR"

# Compass direction of the approach itself (e.g. "N" = the approach on the
# north side of the intersection, which carries southbound traffic) — not
# the direction traffic travels. Naming convention (SB/NB/EB/WB prefixes)
# is derived from this in Session 6.2.
DIRECTIONS = ("N", "S", "E", "W")


def _validate_movement(movement: str) -> str:
    m = (movement or "").upper()
    if not m or any(c not in MOVEMENT_CHARS for c in m):
        raise ValueError(
            f"lane movement must be one or more of {list(MOVEMENT_CHARS)}, got {movement!r}")
    return m


@dataclass
class Lane:
    movement: str  # e.g. "L", "T", "TR" -- one or more of MOVEMENT_CHARS
    width_ft: float = 12.0
    advance_detector: bool = True  # lane-by-lane toggle

    def __post_init__(self):
        self.movement = _validate_movement(self.movement)


@dataclass
class ApproachTemplate:
    schema_version: int = 1
    name: str = "New approach"
    speed_mph: float = 45.0
    lanes: list[Lane] = field(default_factory=lambda: [Lane("T")])
    count_loops: bool = True  # global toggle: place a count loop per lane
    starting_input: int = 1
    starting_output: int = 1
    direction: str = "N"
    thru_phase: int = 4
    lt_phase: int = 7

    def __post_init__(self):
        if self.direction not in DIRECTIONS:
            raise ValueError(f"direction must be one of {DIRECTIONS}, got {self.direction!r}")
        if not self.lanes:
            raise ValueError("template must have at least one lane")


def lane_config_str(lanes: list[Lane]) -> str:
    """Compact display form, e.g. "12'L | 12'T | 12'T | 12'R"."""
    return " | ".join(f"{lane.width_ft:g}'{lane.movement}" for lane in lanes)


def template_to_dict(t: ApproachTemplate) -> dict:
    return asdict(t)


def template_from_dict(d: dict) -> ApproachTemplate:
    lanes = [Lane(**lane) for lane in d.get("lanes", [])]
    kwargs = {k: v for k, v in d.items() if k != "lanes"}
    return ApproachTemplate(lanes=lanes, **kwargs)


def load_template(path: str | Path) -> ApproachTemplate:
    return template_from_dict(json.loads(Path(path).read_text()))


def save_template(template: ApproachTemplate, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(template_to_dict(template), indent=2) + "\n")


# ---------------------------------------------------------------------------
# Template expansion (Session 6.2) — template -> placed detector list
# ---------------------------------------------------------------------------
#
# Approach-local frame
# --------------------
# The expansion first lays detectors out in an abstract approach frame:
#
# * ``setback_ft`` — signed distance from the stop bar to the detector edge
#   nearest the intersection, measured positive *upstream* (into the
#   approach, toward oncoming traffic). The detector extends ``length_ft``
#   further upstream from that edge. Negative setbacks are past the stop
#   bar: a count loop at -15 spans 10–15 ft beyond the bar (counting
#   departures), a 30 ft stop-bar zone at -5 straddles the bar, covering
#   25 ft of approach.
# * ``lateral_offset_ft`` — from the left edge of the leftmost lane
#   (driver's perspective, lanes listed left to right) to the detector's
#   left edge, increasing toward the driver's right.
#
# ITE kinematic placement
# -----------------------
# Speeds convert as v [ft/s] = speed_mph * 5280/3600.
#
# Advance detectors sit at the ITE safe stopping distance — the farthest
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
# which ~90% of drivers are committed to proceed (the zone's ~5.5 s upstream
# end is covered by the advance detectors):
#
#     d_dz = v * 2.5 s
#
# 45 mph -> 165.0 ft. The ROADMAP appendix's ~100/~200 ft figures were
# placeholders; these formulas govern.
#
# Which detectors are generated (in input-numbering order):
#
# 1. Count loops (if ``count_loops``): 5 ft x lane width per lane, -15 ft.
# 2. Stop-bar zones: 30 ft x lane width per lane, -5 ft.
# 3. Dilemma zone (if any thru lane): 20 ft long, spanning from the left
#    edge of the first thru lane to the right edge of the last (any
#    non-thru lane sandwiched between is spanned too).
# 4. Advance detectors: 10 ft x lane width, per thru lane whose
#    ``advance_detector`` toggle is on (the toggle is ignored on turn-only
#    lanes — advance/dilemma detection extends the thru phase).
#
# Phases: a lane is on ``lt_phase`` only when its movement is exactly "L";
# every other lane (T, R, and shared TR/LT lanes) is on ``thru_phase``.

FT_PER_S_PER_MPH = 5280.0 / 3600.0

# ITE kinematic assumptions (see block comment above)
PERCEPTION_REACTION_TIME_S = 1.0
COMFORTABLE_DECEL_FT_S2 = 10.0
DILEMMA_ZONE_END_TRAVEL_TIME_S = 2.5

# Fixed detector geometry (ft) — lengths are along travel
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
    """Advance detectors sit at the safe stopping distance."""
    return safe_stopping_distance_ft(speed_mph)


def dilemma_setback_ft(speed_mph: float) -> float:
    """Downstream end of the indecision zone: 2.5 s of travel."""
    return speed_mph * FT_PER_S_PER_MPH * DILEMMA_ZONE_END_TRAVEL_TIME_S


@dataclass
class DetectorSpec:
    """One detector in the approach-local frame (conventions above)."""
    kind: str  # "count" | "stop_bar" | "dilemma" | "advance"
    name: str
    input_number: int
    output_number: int
    phase: int
    length_ft: float  # along travel
    width_ft: float  # across lanes
    setback_ft: float  # stop bar -> downstream edge, positive upstream
    lateral_offset_ft: float  # leftmost lane's left edge -> detector's left edge


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


def expand_template(template: ApproachTemplate) -> list[DetectorSpec]:
    """Expand a template into detector specs in the approach-local frame,
    with auto-generated names and sequential input/output numbers."""
    prefix = TRAFFIC_DIRECTION[template.direction]

    def lane_phase(lane: Lane) -> int:
        return template.lt_phase if lane.movement == "L" else template.thru_phase

    lane_left = []  # left-edge lateral offset per lane
    x = 0.0
    for lane in template.lanes:
        lane_left.append(x)
        x += lane.width_ft

    # (kind, base name, phase, length, width, setback, lateral offset)
    rows: list[tuple[str, str, int, float, float, float, float]] = []
    if template.count_loops:
        for lane, left in zip(template.lanes, lane_left):
            rows.append(("count", f"{prefix}{lane.movement} Count", lane_phase(lane),
                         COUNT_LOOP_LENGTH_FT, lane.width_ft, COUNT_LOOP_SETBACK_FT, left))
    for lane, left in zip(template.lanes, lane_left):
        phase = lane_phase(lane)
        rows.append(("stop_bar", f"Ph {phase} {prefix}{lane.movement} Stop Bar", phase,
                     STOP_BAR_LENGTH_FT, lane.width_ft, STOP_BAR_SETBACK_FT, left))
    thru = [(lane, left) for lane, left in zip(template.lanes, lane_left)
            if "T" in lane.movement]
    if thru:
        span_left = thru[0][1]
        span_right = thru[-1][1] + thru[-1][0].width_ft
        rows.append(("dilemma", f"Ph {template.thru_phase} Dilemma", template.thru_phase,
                     DILEMMA_LENGTH_FT, span_right - span_left,
                     dilemma_setback_ft(template.speed_mph), span_left))
        for lane, left in thru:
            if lane.advance_detector:
                rows.append(("advance", f"Ph {template.thru_phase} Advance",
                             template.thru_phase, ADVANCE_LENGTH_FT, lane.width_ft,
                             advance_setback_ft(template.speed_mph), left))

    names = _numbered([r[1] for r in rows])
    return [
        DetectorSpec(kind=kind, name=name,
                     input_number=template.starting_input + i,
                     output_number=template.starting_output + i,
                     phase=phase, length_ft=length, width_ft=width,
                     setback_ft=setback, lateral_offset_ft=lateral)
        for i, (name, (kind, _, phase, length, width, setback, lateral))
        in enumerate(zip(names, rows))
    ]


def place_detectors(
    specs: list[DetectorSpec],
    stop_bar_ref: Point,
    upstream_dir: Point,
    units_per_ft: float = 1.0,
) -> list[PlacedDetector]:
    """Place specs in world coordinates (y-down, like the iprj file).

    ``stop_bar_ref`` is the point where the stop bar meets the left edge of
    the leftmost lane (driver's perspective); ``upstream_dir`` points
    upstream, away from the intersection (any nonzero length). With y-down
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
) -> list[PlacedDetector]:
    """One-call form for the GUI: expand, then place (see both functions)."""
    return place_detectors(expand_template(template), stop_bar_ref, upstream_dir,
                           units_per_ft)


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
# The stop-bar reference point is projected onto the centerline; detectors
# are laid out relative to that projection, so the click keeps its
# straight-placement meaning (where the stop bar meets the leftmost lane's
# left edge) and the centerline itself may be drawn anywhere across the
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
) -> list[PlacedDetector]:
    """One-call curvilinear form for the GUI: expand, then place along the
    centerline (see both functions)."""
    return place_detectors_on_centerline(expand_template(template),
                                         centerline_points, stop_bar_ref,
                                         units_per_ft)
