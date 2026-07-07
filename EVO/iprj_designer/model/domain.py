"""Econolite Evo domain codes and entity-model helpers — pure python.

Vendor codes below were read straight out of the Evo (Epiq) software by the
project owner (2026-07-03 session); they resolve the enum items IPRJ_FORMAT.md
had marked "(open)". The structural insight that shaped this module: the file
format writes the *same* full attribute set for every condition — there is no
per-type schema on disk. Which fields are meaningful is decided by the owning
zone's ``ZoneType``:

* **Presence** — output, delay, extension, queue length, and the per-class
  vehicle count filters are relevant.
* **Motion** — vehicle class (``ConditionClass``), direction, delay,
  extension, velocity, and ETA are relevant.
* **Sidewalk** — the vendor UI allows no conditions at all.

Everything else in a condition simply keeps its defaults, which is why all
conditions in the wild look alike attribute-wise.

Also here: placeholder/slot-insertion helpers for Ignore Zones and generic
(non-centerline) Lineals, mirroring ``gui/drawing.insert_zone``'s
fill-a-placeholder-slot-else-append vendor behavior.
"""

from __future__ import annotations

from enum import IntEnum

from .iprj_io import Condition, IgnoreZone, Lineal, Point, TextLabel

# Vendor placeholder-array capacities (per IPRJ_FORMAT.md survey): the vendor
# writes fixed-size arrays of this many slots, so treat them as hard caps.
MAX_EVENT_ZONES = 64      # per sensor
MAX_CONDITIONS = 10       # per event zone
MAX_IGNORE_ZONES = 10     # per sensor
MAX_LINEALS = 100         # per project
MAX_TEXTLABELS = 100      # per project
MAX_ZONE_POINTS = 10      # polygon vertices (10 is the most seen in the wild)


# ---------------------------------------------------------------------------
# Zone (loop) types
# ---------------------------------------------------------------------------

class ZoneType(IntEnum):
    """``ZoneType`` codes as the vendor UI names them.

    The Session 1 survey's guesses ("standard"/"stop bar"/"legacy") are
    superseded; the observed data still agrees — stop-bar zones in the field
    files are type 1 because stop-bar detection is presence detection.
    """

    MOTION = 0
    PRESENCE = 1
    SIDEWALK = 2


ZONE_TYPE_NAMES = {
    ZoneType.MOTION: "Motion",
    ZoneType.PRESENCE: "Presence",
    ZoneType.SIDEWALK: "Sidewalk",
}


# ---------------------------------------------------------------------------
# Condition codes
# ---------------------------------------------------------------------------

class VehicleClass(IntEnum):
    """``ConditionClass`` — the vehicle-class filter of a Motion condition
    (not a condition-type discriminator; see module docstring)."""

    ALL = 0
    CAR = 1
    BIKE_PED = 2
    SMALL_TRUCK = 3
    BIG_TRUCK = 4
    CAR_BIG_TRUCK = 5
    CAR_SMALL_TRUCK = 6
    CAR_SMALL_BIG_TRUCK = 7


VEHICLE_CLASS_NAMES = {
    VehicleClass.ALL: "All",
    VehicleClass.CAR: "Car",
    VehicleClass.BIKE_PED: "Bike/Ped",
    VehicleClass.SMALL_TRUCK: "Small truck",
    VehicleClass.BIG_TRUCK: "Big truck",
    VehicleClass.CAR_BIG_TRUCK: "Car + big truck",
    VehicleClass.CAR_SMALL_TRUCK: "Car + small truck",
    VehicleClass.CAR_SMALL_BIG_TRUCK: "Car + small + big truck",
}


class Direction(IntEnum):
    """``Direction`` of a Motion condition, relative to the sensor."""

    BOTH = 0
    APPROACHING = 1
    RECEDING = 2


DIRECTION_NAMES = {
    Direction.BOTH: "Both directions",
    Direction.APPROACHING: "Approaching sensor",
    Direction.RECEDING: "Receding from sensor",
}


# Vendor wide-open filter sentinels (observed in the field files; the vendor
# UI shows these as min 0 / max 9999 in user units).
SPEED_DEFAULT_MIN_MPH = 0.0
SPEED_DEFAULT_MAX_MPH = 9999.0
VELOCITY_MAX_SENTINEL_KMH = 16091.79  # 9999 mph as the vendor stores it
QUEUE_MAX_SENTINEL_M = 3047.70        # 9999 ft
ETA_MAX_SENTINEL_S = 999.0
COUNT_MAX_SENTINEL = 255


# Which Condition fields the vendor UI exposes per zone type (field names of
# iprj_io.Condition). enable is implicit; sidewalk zones take no conditions.
# output_number is listed for Motion too: the enabled speed conditions in the
# wild (Franklin, Banks) all carry a real OutputNumber.
_PRESENCE_FIELDS = (
    "output_number", "event_message_delay", "event_message_extend",
    "queuelength_min", "queuelength_max",
    "nr_pedest_min", "nr_pedest_max", "nr_cars_min", "nr_cars_max",
    "nr_small_trucks_min", "nr_small_trucks_max",
    "nr_big_trucks_min", "nr_big_trucks_max",
)
_MOTION_FIELDS = (
    "output_number", "condition_class", "direction",
    "event_message_delay", "event_message_extend",
    "velocity_min", "velocity_max", "eta_min", "eta_max",
)

CONDITION_FIELDS: dict[ZoneType, tuple[str, ...]] = {
    ZoneType.PRESENCE: _PRESENCE_FIELDS,
    ZoneType.MOTION: _MOTION_FIELDS,
    ZoneType.SIDEWALK: (),
}


def conditions_allowed(zone_type: int | None) -> bool:
    """Whether the vendor UI lets a zone of this type carry conditions."""
    return bool(condition_fields(zone_type))


def condition_fields(zone_type: int | None) -> tuple[str, ...]:
    """Condition fields relevant for *zone_type*; unknown codes (future
    firmware) fall back to the full union so nothing is hidden."""
    try:
        return CONDITION_FIELDS[ZoneType(zone_type or 0)]
    except ValueError:
        return tuple(dict.fromkeys(_PRESENCE_FIELDS + _MOTION_FIELDS))


def default_condition(output: int = 0) -> Condition:
    """Enabled condition with the vendor's wide-open filter sentinels —
    matches what the vendor writes for a freshly added condition."""
    return Condition(enable=1, output_number=output,
                     velocity_max=VELOCITY_MAX_SENTINEL_KMH,
                     queuelength_max=QUEUE_MAX_SENTINEL_M,
                     eta_max=ETA_MAX_SENTINEL_S,
                     nr_pedest_max=COUNT_MAX_SENTINEL,
                     nr_cars_max=COUNT_MAX_SENTINEL,
                     nr_small_trucks_max=COUNT_MAX_SENTINEL,
                     nr_big_trucks_max=COUNT_MAX_SENTINEL)


# ---------------------------------------------------------------------------
# Ignore Zones
# ---------------------------------------------------------------------------

def is_placeholder_ignore(zone: IgnoreZone) -> bool:
    """Disabled, unnamed, pointless slots — the vendor pads each sensor to
    MAX_IGNORE_ZONES of these."""
    return not zone.enable and not (zone.zone_name or "").strip() \
        and not zone.points


def new_ignore_zone(points: list[Point], name: str = "",
                    ignore_everything: int = 1) -> IgnoreZone:
    """Enabled ignore zone. ``ignore_everything=1`` is the usual field
    setting (38 of the 48 enabled ignore zones in the site survey)."""
    return IgnoreZone(enable=1, ignore_everything=ignore_everything,
                      zone_name=name,
                      points=[(float(x), float(y)) for x, y in points])


def insert_ignore_zone(zones: list[IgnoreZone], zone: IgnoreZone) -> int:
    """Put *zone* in the first placeholder slot else append; returns the
    index used. Raises ValueError past the vendor's 10-slot array."""
    for i, z in enumerate(zones):
        if is_placeholder_ignore(z):
            zones[i] = zone
            return i
    if len(zones) >= MAX_IGNORE_ZONES:
        raise ValueError(f"sensor already has {MAX_IGNORE_ZONES} ignore zones")
    zones.append(zone)
    return len(zones) - 1


# ---------------------------------------------------------------------------
# Generic Lineals (reference/measurement lines)
# ---------------------------------------------------------------------------
#
# The Lineal pool is shared with the centerline encoding
# (model/centerline.py): any Lineal that shares an endpoint with another is
# read back as part of a centerline chain. A generic lineal must therefore
# stay a *lone* segment — never snap its endpoints onto a centerline vertex
# or onto another generic lineal's endpoint, or it will merge into (or
# corrupt) a centerline on the next load.

def is_placeholder_lineal(lineal: Lineal) -> bool:
    """Disabled slot with no real geometry (same test as
    centerline._is_free_slot: zeroed or missing points)."""
    def _zero(p: Point | None) -> bool:
        return p is None or (round(p[0], 2), round(p[1], 2)) == (0.0, 0.0)
    return not lineal.enable and _zero(lineal.point_0) and _zero(lineal.point_1)


def new_lineal(p0: Point, p1: Point) -> Lineal:
    """Enabled two-point reference line."""
    return Lineal(enable=1, point_0=(float(p0[0]), float(p0[1])),
                  point_1=(float(p1[0]), float(p1[1])))


def insert_lineal(lineals: list[Lineal], lineal: Lineal) -> int:
    """Put *lineal* in the first placeholder slot else append; returns the
    index used. Raises ValueError past the vendor's 100-slot array."""
    for i, l in enumerate(lineals):
        if is_placeholder_lineal(l):
            lineals[i] = lineal
            return i
    if len(lineals) >= MAX_LINEALS:
        raise ValueError(f"project already has {MAX_LINEALS} lineals")
    lineals.append(lineal)
    return len(lineals) - 1


# ---------------------------------------------------------------------------
# Text Labels (ROADMAP Item 22 GUI entity)
# ---------------------------------------------------------------------------
#
# The GUI carries text labels as a working pool of *enabled* TextLabels (like
# the generic-lineal pool), round-tripped through the band mechanism in
# model/labels.py on save. New-label defaults follow the vendor's real enabled
# labels: FontSize 12, white text, no style flags, no rotation.

# Defaults for a freshly drawn label (ROADMAP Item 22).
LABEL_FONT_SIZE = 12
LABEL_COLOR = (255, 255, 255)  # white


def is_placeholder_label(label: TextLabel) -> bool:
    """A free slot in the working label pool: any disabled label (enabled
    labels are the project's real annotations). Mirrors model/labels._is_free
    so the GUI draw-kind machinery treats the pool the vendor way."""
    return not label.enable


def new_label(anchor: Point, text: str = "") -> TextLabel:
    """Enabled text label at *anchor* with the ROADMAP Item 22 new-label
    defaults (FontSize 12, white, no style flags, rotation 0°)."""
    r, g, b = LABEL_COLOR
    return TextLabel(enable=1, text=text,
                     position_x=float(anchor[0]), position_y=float(anchor[1]),
                     font_size=LABEL_FONT_SIZE, font_bold=0, font_underline=0,
                     font_italic=0, rotation_angle=0.0,
                     textcolor_red=r, textcolor_green=g, textcolor_blue=b)


def insert_label(labels: list[TextLabel], label: TextLabel) -> int:
    """Put *label* in the first placeholder slot else append; returns the
    index used. Raises ValueError past the vendor's 100-slot array. (The GUI
    pool holds only enabled labels, so this appends in practice — the
    placeholder branch mirrors insert_lineal for shared draw-kind handling.)"""
    for i, l in enumerate(labels):
        if is_placeholder_label(l):
            labels[i] = label
            return i
    if len(labels) >= MAX_TEXTLABELS:
        raise ValueError(f"project already has {MAX_TEXTLABELS} text labels")
    labels.append(label)
    return len(labels) - 1
