"""Load/save .iprj project files (see IPRJ_FORMAT.md).

The dataclasses mirror the file's own coordinate system: world pixels, y-down.
Unit conversion to feet/meters lives in model/units.py; nothing here converts.

Round-trip contract: load_iprj normalizes the origin (coords.normalize_origin)
so the background image's top-left is world (0,0) — every coordinate value is
translated by (-Background_PosX, -Background_PosY); this deliberately departs
from vendor byte-fidelity (ROADMAP Item 11). load_iprj -> save_iprj then
preserves every attribute key, all non-coordinate values, and all geometry
relative to the image; Background_PosX/PosY save as 0. Numeric formatting may
be normalized and element order follows the vendor's canonical order.
Unrecognized keys are kept verbatim in the owning object's `extra` dict, so
files written by other tools survive intact.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import quoteattr

from .coords import normalize_origin

Point = tuple[float, float]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Condition:
    enable: int | None = 0
    output_number: int | None = 0
    condition_class: int | None = 0
    direction: int | None = 0
    velocity_min: float | None = 0.0
    velocity_max: float | None = 0.0
    queuelength_min: float | None = 0.0
    queuelength_max: float | None = 0.0
    event_message_delay: int | None = 0
    event_message_extend: int | None = 0
    eta_min: float | None = 0.0
    eta_max: float | None = 0.0
    nr_pedest_min: int | None = 0
    nr_pedest_max: int | None = 0
    nr_cars_min: int | None = 0
    nr_cars_max: int | None = 0
    nr_small_trucks_min: int | None = 0
    nr_small_trucks_max: int | None = 0
    nr_big_trucks_min: int | None = 0
    nr_big_trucks_max: int | None = 0
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class EventZone:
    enable: int | None = 1
    zone_name: str | None = ""
    zone_type: int | None = 0
    phase_number: int | None = 0
    event_message_delay: int | None = 0
    event_message_extend: int | None = 0
    output_number: int | None = 0
    eta_enable: int | None = 0
    eta_point_x: float | None = 0.0
    eta_point_y: float | None = 0.0
    points: list[Point] = field(default_factory=list)  # world px, y-down
    conditions: list[Condition] = field(default_factory=list)
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class IgnoreZone:
    enable: int | None = 1
    ignore_everything: int | None = 0
    zone_name: str | None = ""
    points: list[Point] = field(default_factory=list)
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class Sensor:
    position_x: float | None = 0.0
    position_y: float | None = 0.0
    azimuth_angle: float | None = 0.0
    elevation_angle: float | None = 0.0
    road_gradient_angle: float | None = 0.0
    installation_height: float | None = 6.0  # meters
    rain_interference_threshold: float | None = 30.0
    highway_mode: int | None = 0
    max_stop_time: int | None = 300
    frequency_channel: int | None = 1
    gps_lat: float | None = 0.0
    gps_lng: float | None = 0.0
    event_zones: list[EventZone] = field(default_factory=list)
    ignore_zones: list[IgnoreZone] = field(default_factory=list)
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class Lineal:
    enable: int | None = 0
    point_0: Point | None = None
    point_1: Point | None = None
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class TextLabel:
    enable: int | None = 0
    text: str | None = ""
    position_x: float | None = 0.0
    position_y: float | None = 0.0
    font_size: int | None = 0
    font_bold: int | None = 0
    font_underline: int | None = 0
    font_italic: int | None = 0
    rotation_angle: float | None = 0.0
    textcolor_red: int | None = 0
    textcolor_green: int | None = 0
    textcolor_blue: int | None = 0
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class Background:
    """Background image placement plus the scale calibration.

    The image's top-left corner sits at (pos_x, pos_y) in world pixels.
    meter_per_pixel is the operative scale but vendor files round it to two
    decimals; the reference pair + reference_length carry full precision
    (see units.effective_meter_per_pixel).
    """

    image_base64: str | None = None
    pos_x: float | None = 0.0
    pos_y: float | None = 0.0
    rotation: float | None = 0.0
    scale: float | None = 100.0
    reference_length: float | None = None  # meters between ref points
    meter_per_pixel: float | None = None
    ref0_x: float | None = None
    ref0_y: float | None = None
    ref1_x: float | None = None
    ref1_y: float | None = None
    # File-fidelity detail: converter-written files spell the key
    # "MetersPerPixel"; vendor files use "MeterPerPixel".
    meter_per_pixel_key: str = "MeterPerPixel"
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class Project:
    background: Background = field(default_factory=Background)
    sensors: list[Sensor] = field(default_factory=list)
    lineals: list[Lineal] = field(default_factory=list)
    text_labels: list[TextLabel] = field(default_factory=list)
    date: str | None = None  # vendor format "2025_07_16_11:41:42"
    version: str = "1.1"
    product_code: str = "5220"
    extra: dict[str, str] = field(default_factory=dict)  # Zoomfaktor, PlotPreferences_*, ...


# ---------------------------------------------------------------------------
# Value conversion
# ---------------------------------------------------------------------------

def _pop_float(d: dict, key: str) -> float | None:
    v = d.pop(key, None)
    return None if v is None else float(v)


def _pop_int(d: dict, key: str) -> int | None:
    v = d.pop(key, None)
    return None if v is None else int(float(v))


def _fmt(v) -> str:
    if isinstance(v, float):
        # Vendor style is fixed two decimals; fall back to repr when that
        # would lose value (e.g. MeterPerPixel 0.0762 in converter files).
        s = f"{v:.2f}"
        return s if float(s) == v else repr(v)
    return str(v)


def _pop_points(d: dict, prefix: str) -> list[Point]:
    points = []
    for k in range(len(d)):  # upper bound; indices are contiguous
        xk, yk = f"{prefix}_{k}_X", f"{prefix}_{k}_Y"
        if xk not in d and yk not in d:
            break
        points.append((float(d.pop(xk)), float(d.pop(yk))))
    return points


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

_SENSOR_SCALARS = {
    "Position_X": ("position_x", _pop_float),
    "Position_Y": ("position_y", _pop_float),
    "AzimuthAngle": ("azimuth_angle", _pop_float),
    "ElevationAngle": ("elevation_angle", _pop_float),
    "RoadGradientAngle": ("road_gradient_angle", _pop_float),
    "InstallationHeight": ("installation_height", _pop_float),
    "RainInterferenceThreshold": ("rain_interference_threshold", _pop_float),
    "HighwayMode": ("highway_mode", _pop_int),
    "MaxStopTime": ("max_stop_time", _pop_int),
    "FrequencyChannel": ("frequency_channel", _pop_int),
    "Gps_lat": ("gps_lat", _pop_float),
    "Gps_lng": ("gps_lng", _pop_float),
}

_ZONE_SCALARS = {
    "Enable": ("enable", _pop_int),
    "ZoneName": ("zone_name", lambda d, k: d.pop(k, None)),
    "ZoneType": ("zone_type", _pop_int),
    "PhaseNumber": ("phase_number", _pop_int),
    "EventMessageDelay": ("event_message_delay", _pop_int),
    "EventMessageExtend": ("event_message_extend", _pop_int),
    "OutputNumber": ("output_number", _pop_int),
    "EtaEnable": ("eta_enable", _pop_int),
    "EtaPoint_X": ("eta_point_x", _pop_float),
    "EtaPoint_Y": ("eta_point_y", _pop_float),
}

_CONDITION_SCALARS = {
    "Enable": ("enable", _pop_int),
    "OutputNumber": ("output_number", _pop_int),
    "ConditionClass": ("condition_class", _pop_int),
    "Direction": ("direction", _pop_int),
    "VelocityMin": ("velocity_min", _pop_float),
    "VelocityMax": ("velocity_max", _pop_float),
    "QueuelengthMin": ("queuelength_min", _pop_float),
    "QueuelengthMax": ("queuelength_max", _pop_float),
    "EventMessageDelay": ("event_message_delay", _pop_int),
    "EventMessageExtend": ("event_message_extend", _pop_int),
    "EtaMin": ("eta_min", _pop_float),
    "EtaMax": ("eta_max", _pop_float),
    "NrPedestMin": ("nr_pedest_min", _pop_int),
    "NrPedestMax": ("nr_pedest_max", _pop_int),
    "NrCarsMin": ("nr_cars_min", _pop_int),
    "NrCarsMax": ("nr_cars_max", _pop_int),
    "NrSmallTrucksMin": ("nr_small_trucks_min", _pop_int),
    "NrSmallTrucksMax": ("nr_small_trucks_max", _pop_int),
    "NrBigTrucksMin": ("nr_big_trucks_min", _pop_int),
    "NrBigTrucksMax": ("nr_big_trucks_max", _pop_int),
}

_IGNORE_SCALARS = {
    "Enable": ("enable", _pop_int),
    "IgnoreEverything": ("ignore_everything", _pop_int),
    "ZoneName": ("zone_name", lambda d, k: d.pop(k, None)),
}

_TEXTLABEL_SCALARS = {
    "Enable": ("enable", _pop_int),
    "Text": ("text", lambda d, k: d.pop(k, None)),
    "Position_X": ("position_x", _pop_float),
    "Position_Y": ("position_y", _pop_float),
    "FontSize": ("font_size", _pop_int),
    "FontBold": ("font_bold", _pop_int),
    "FontUnderline": ("font_underline", _pop_int),
    "FontItalic": ("font_italic", _pop_int),
    "RotationAngle": ("rotation_angle", _pop_float),
    "Textcolor_Red": ("textcolor_red", _pop_int),
    "Textcolor_Green": ("textcolor_green", _pop_int),
    "Textcolor_Blue": ("textcolor_blue", _pop_int),
}


def _build(cls, raw: dict, scalars: dict):
    kwargs = {}
    for attr_name, (field_name, popper) in scalars.items():
        kwargs[field_name] = popper(raw, attr_name)
    return cls(**kwargs)


def _indexed_list(buckets: dict[int, dict]) -> list[dict]:
    if not buckets:
        return []
    n = max(buckets) + 1
    return [buckets.get(i, {}) for i in range(n)]


def load_iprj(path: str | Path) -> Project:
    root = ET.parse(path).getroot()
    attrs: dict[str, str] = {}
    for elem in root.iter("Configuration"):
        attrs.update(elem.attrib)

    product = root.find("ProductInformation")
    project = Project(
        date=root.get("date"),
        version=root.get("Version") or "1.1",
        product_code=(product.get("ProductCode") if product is not None else None) or "5220",
    )

    # Bucket the flat namespace into per-entity raw dicts (insertion-ordered).
    bg: dict[str, str] = {}
    sensors: dict[int, dict] = {}
    zones: dict[tuple[int, int], dict] = {}
    conds: dict[tuple[int, int, int], dict] = {}
    ignores: dict[tuple[int, int], dict] = {}
    lineals: dict[int, dict] = {}
    labels: dict[int, dict] = {}

    bg_keys = {
        "BackgroundImage", "Background_PosX", "Background_PosY",
        "BackgroundImageRotation", "BackgroundImageScale", "ReferenceLength",
        "MeterPerPixel", "MetersPerPixel",
        "MeterReference0_X", "MeterReference0_Y",
        "MeterReference1_X", "MeterReference1_Y",
    }
    sensor_re = re.compile(r"Radarsensor_(\d+)_(.+)$")
    zone_re = re.compile(r"EventZone_(\d+)_(.+)$")
    cond_re = re.compile(r"Condition_(\d+)_(.+)$")
    ignore_re = re.compile(r"IgnoreZone_(\d+)_(.+)$")
    lineal_re = re.compile(r"Lineals_(\d+)_(.+)$")
    label_re = re.compile(r"Textlabel_(\d+)_(.+)$")

    for key, value in attrs.items():
        if key in bg_keys:
            bg[key] = value
            continue
        if key == "Radarsensor_nrOfSensors":
            continue  # derived from sensor keys on save
        m = sensor_re.match(key)
        if m:
            si, rest = int(m.group(1)), m.group(2)
            mz = zone_re.match(rest)
            if mz:
                zi, zrest = int(mz.group(1)), mz.group(2)
                mc = cond_re.match(zrest)
                if mc:
                    conds.setdefault((si, zi, int(mc.group(1))), {})[mc.group(2)] = value
                else:
                    zones.setdefault((si, zi), {})[zrest] = value
                continue
            mi = ignore_re.match(rest)
            if mi:
                ignores.setdefault((si, int(mi.group(1))), {})[mi.group(2)] = value
                continue
            sensors.setdefault(si, {})[rest] = value
            continue
        m = lineal_re.match(key)
        if m:
            lineals.setdefault(int(m.group(1)), {})[m.group(2)] = value
            continue
        m = label_re.match(key)
        if m:
            labels.setdefault(int(m.group(1)), {})[m.group(2)] = value
            continue
        project.extra[key] = value

    # Background / calibration
    background = Background(
        image_base64=bg.pop("BackgroundImage", None),
        pos_x=_pop_float(bg, "Background_PosX"),
        pos_y=_pop_float(bg, "Background_PosY"),
        rotation=_pop_float(bg, "BackgroundImageRotation"),
        scale=_pop_float(bg, "BackgroundImageScale"),
        reference_length=_pop_float(bg, "ReferenceLength"),
        ref0_x=_pop_float(bg, "MeterReference0_X"),
        ref0_y=_pop_float(bg, "MeterReference0_Y"),
        ref1_x=_pop_float(bg, "MeterReference1_X"),
        ref1_y=_pop_float(bg, "MeterReference1_Y"),
    )
    if "MeterPerPixel" in bg:
        background.meter_per_pixel = _pop_float(bg, "MeterPerPixel")
    elif "MetersPerPixel" in bg:
        background.meter_per_pixel = _pop_float(bg, "MetersPerPixel")
        background.meter_per_pixel_key = "MetersPerPixel"
    project.background = background

    # Sensors with nested zones/conditions/ignore zones
    for si, raw in enumerate(_indexed_list(sensors)):
        sensor = _build(Sensor, raw, _SENSOR_SCALARS)
        sensor.extra = raw
        project.sensors.append(sensor)

    for (si, zi), raw in sorted(zones.items()):
        zone = _build(EventZone, raw, _ZONE_SCALARS)
        raw.pop("NrOfZonePoints", None)  # derived from points on save
        zone.points = _pop_points(raw, "ZonePoint")
        zone.extra = raw
        while si >= len(project.sensors):
            project.sensors.append(Sensor())
        zlist = project.sensors[si].event_zones
        while zi >= len(zlist):
            zlist.append(EventZone())
        zlist[zi] = zone

    for (si, zi, ci), raw in sorted(conds.items()):
        cond = _build(Condition, raw, _CONDITION_SCALARS)
        cond.extra = raw
        while si >= len(project.sensors):
            project.sensors.append(Sensor())
        zlist = project.sensors[si].event_zones
        while zi >= len(zlist):
            zlist.append(EventZone())
        clist = zlist[zi].conditions
        while ci >= len(clist):
            clist.append(Condition())
        clist[ci] = cond

    for (si, ii), raw in sorted(ignores.items()):
        zone = _build(IgnoreZone, raw, _IGNORE_SCALARS)
        raw.pop("NrOfZonePoints", None)
        zone.points = _pop_points(raw, "ZonePoint")
        zone.extra = raw
        ilist = project.sensors[si].ignore_zones
        while ii >= len(ilist):
            ilist.append(IgnoreZone())
        ilist[ii] = zone

    for raw in _indexed_list(lineals):
        lineal = Lineal(enable=_pop_int(raw, "Enable"))
        pts = _pop_points(raw, "Point")
        lineal.point_0 = pts[0] if len(pts) > 0 else None
        lineal.point_1 = pts[1] if len(pts) > 1 else None
        lineal.extra = raw
        project.lineals.append(lineal)

    for raw in _indexed_list(labels):
        label = _build(TextLabel, raw, _TEXTLABEL_SCALARS)
        label.extra = raw
        project.text_labels.append(label)

    return normalize_origin(project)


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def _emit(items: list, prefix: str, obj, scalars: dict):
    for attr_name, (field_name, _) in scalars.items():
        v = getattr(obj, field_name)
        if v is not None:
            items.append((prefix + attr_name, _fmt(v)))


def _emit_points(items: list, prefix: str, points: list[Point]):
    for k, (x, y) in enumerate(points):
        items.append((f"{prefix}_{k}_X", _fmt(float(x))))
        items.append((f"{prefix}_{k}_Y", _fmt(float(y))))


def _emit_extra(items: list, prefix: str, extra: dict[str, str]):
    for k, v in extra.items():
        items.append((prefix + k, v))


def iprj_attributes(project: Project) -> list[tuple[str, str]]:
    """Flatten a Project into (key, value) pairs in vendor-canonical order."""
    items: list[tuple[str, str]] = []
    bg = project.background
    for key, v in [
        ("BackgroundImage", bg.image_base64),
        ("Background_PosX", bg.pos_x),
        ("Background_PosY", bg.pos_y),
        ("BackgroundImageRotation", bg.rotation),
        ("BackgroundImageScale", bg.scale),
        ("ReferenceLength", bg.reference_length),
        (bg.meter_per_pixel_key, bg.meter_per_pixel),
        ("MeterReference0_X", bg.ref0_x),
        ("MeterReference0_Y", bg.ref0_y),
        ("MeterReference1_X", bg.ref1_x),
        ("MeterReference1_Y", bg.ref1_y),
    ]:
        if v is not None:
            items.append((key, v if isinstance(v, str) else _fmt(v)))
    _emit_extra(items, "", bg.extra)
    _emit_extra(items, "", project.extra)

    items.append(("Radarsensor_nrOfSensors", str(len(project.sensors))))
    for si, sensor in enumerate(project.sensors):
        sp = f"Radarsensor_{si}_"
        _emit(items, sp, sensor, _SENSOR_SCALARS)
        _emit_extra(items, sp, sensor.extra)
        for zi, zone in enumerate(sensor.event_zones):
            zp = f"{sp}EventZone_{zi}_"
            if zone.enable is not None:
                items.append((zp + "Enable", _fmt(zone.enable)))
            if zone.zone_name is not None:
                items.append((zp + "ZoneName", zone.zone_name))
            items.append((zp + "NrOfZonePoints", str(len(zone.points))))
            for attr_name in ("ZoneType", "PhaseNumber", "EventMessageDelay",
                              "EventMessageExtend", "OutputNumber", "EtaEnable",
                              "EtaPoint_X", "EtaPoint_Y"):
                v = getattr(zone, _ZONE_SCALARS[attr_name][0])
                if v is not None:
                    items.append((zp + attr_name, _fmt(v)))
            _emit_extra(items, zp, zone.extra)
            _emit_points(items, zp + "ZonePoint", zone.points)
            for ci, cond in enumerate(zone.conditions):
                cp = f"{zp}Condition_{ci}_"
                _emit(items, cp, cond, _CONDITION_SCALARS)
                _emit_extra(items, cp, cond.extra)
        for ii, zone in enumerate(sensor.ignore_zones):
            ip = f"{sp}IgnoreZone_{ii}_"
            _emit(items, ip, zone, _IGNORE_SCALARS)
            items.append((ip + "NrOfZonePoints", str(len(zone.points))))
            _emit_extra(items, ip, zone.extra)
            _emit_points(items, ip + "ZonePoint", zone.points)

    for li, lineal in enumerate(project.lineals):
        lp = f"Lineals_{li}_"
        if lineal.enable is not None:
            items.append((lp + "Enable", _fmt(lineal.enable)))
        pts = [p for p in (lineal.point_0, lineal.point_1) if p is not None]
        _emit_points(items, lp + "Point", pts)
        _emit_extra(items, lp, lineal.extra)

    for ti, label in enumerate(project.text_labels):
        tp = f"Textlabel_{ti}_"
        _emit(items, tp, label, _TEXTLABEL_SCALARS)
        _emit_extra(items, tp, label.extra)

    return items


def save_iprj(project: Project, path: str | Path) -> None:
    """Write vendor form: <Config> root, one <Configuration> per attribute."""
    date = project.date or time.strftime("%Y_%m_%d_%H:%M:%S")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<Config date="{date}" Version="{project.version}">',
        f'    <ProductInformation ProductCode="{project.product_code}"/>',
    ]
    for key, value in iprj_attributes(project):
        lines.append(f"    <Configuration {key}={quoteattr(value)}/>")
    lines.append("</Config>")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
