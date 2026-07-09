"""Zone-based EVO→map alignment (the overlay-rotation fix).

The EVO fused track frame is rotated by a real, site-specific angle relative
to the site background (Banks ≈ −34°, US95&SH8 ≈ 0°), so the translation-only
alignment in replay.py skews rotated sites. The correct transform is a 2D
similarity, and its parameters are recoverable exactly from data both sides
already carry (OVERLAY_ROTATION_INVESTIGATION.md, resolved 2026-07-09):

* The stream's ``Z;`` GetCfg line lists every configured zone as polygons in
  the EVO fused frame (meters). Each zone is ``sensor_slot, is_ignore,
  phase, output`` then flattened x,y vertices; zones arrive per slot in the
  iprj's slot order, event zones before ignore zones.
* The iprj stores the same zones in world pixels. The vendor tool generated
  one side from the other with a per-sensor similarity (per-sensor fits are
  exact to float precision), so matched zones are perfect correspondences.

A project sensor is identified to its ``Z;`` slot by an ordered *signature*
— the (kind, phase, output, vertex-count) sequence of its nonempty zones —
which needs no decoding of sensor host/IP and self-validates: a signature
that matches nothing (or more than one thing) simply contributes no
correspondences. A least-squares similarity over all matched zone centroids
(complex form, so it cannot produce a reflection) then recovers
rotation+scale+translation with dozens of points spanning the whole site —
the long baseline the reverted 2-sensor auto-fit (H3) lacked. Residual
beyond float noise is inter-sensor placement inconsistency on the map
(~5–7 ft at Banks).

For a site whose image happens to match the EVO frame the fit is ≈identity
(US95&SH8: 1.5°, scale 1.017), so correct sites stay correct. When anything
falls short — no ``Z;`` line, no unambiguous signature match, too few or too
clustered zones, or a residual that says the match is wrong — ``fit``
returns None and callers keep the translation-only fallback.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .iprj_io import Project, Sensor
from .units import effective_meter_per_pixel, m_to_ft, px_to_ft

# Fallback gates: below MIN_ZONES a similarity is under-constrained in
# practice; below MIN_SPREAD_FT the lever arm is too short to trust the
# rotation (the H3 lesson); above MAX_MEAN_RESIDUAL_FT the correspondences
# are evidently wrong (real matched sites sit at 0–7 ft).
MIN_ZONES = 3
MIN_SPREAD_FT = 50.0
MAX_MEAN_RESIDUAL_FT = 30.0


@dataclass(frozen=True)
class RawZone:
    """One zone off a ``Z;`` line, still in EVO meters."""

    slot: int  # sensor slot in the fused stream (0-3)
    is_ignore: bool  # False = event zone, True = ignore zone
    phase: int
    output: int
    points_m: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class ZoneFit:
    """A fitted EVO→world similarity: ``world = a * evo_ft + t`` (complex)."""

    a_re: float  # scale*cos(rot), scale*sin(rot) — kept as floats so the
    a_im: float  # dataclass stays trivially serializable/comparable
    t_x: float  # world feet
    t_y: float
    n_zones: int
    rotation_deg: float
    scale: float
    mean_residual_ft: float
    max_residual_ft: float
    slot_to_sensor: tuple[tuple[int, int], ...]  # (Z; slot, project sensor)

    def apply_m(self, x_m: float, y_m: float) -> tuple[float, float]:
        """EVO meters → world feet (y-down on both sides)."""
        e = complex(m_to_ft(x_m), m_to_ft(y_m))
        w = complex(self.a_re, self.a_im) * e + complex(self.t_x, self.t_y)
        return w.real, w.imag


def parse_zline(line: str) -> list[RawZone]:
    """Decode a ``Z;`` GetCfg line; [] when the line isn't one / is malformed.

    Grammar: ``Z;`` then ``;``-separated zones, each ``slot,is_ignore,phase,
    output`` followed by flattened x,y vertex pairs (≥3 vertices). One bad
    zone invalidates the whole line — a partial zone list would silently
    bias the fit toward the sensors that survived.
    """
    if not line.startswith("Z;"):
        return []
    zones: list[RawZone] = []
    for chunk in line[2:].strip().split(";"):
        vals = chunk.split(",")
        if len(vals) < 4 + 6 or (len(vals) - 4) % 2 != 0:
            return []
        try:
            slot, ign, phase, output = (int(v) for v in vals[:4])
            pts = tuple(
                (float(vals[i]), float(vals[i + 1]))
                for i in range(4, len(vals), 2)
            )
        except ValueError:
            return []
        zones.append(RawZone(slot, bool(ign), phase, output, pts))
    return zones


# A signature entry: (is_ignore, phase, output, n_vertices). Ignore zones
# carry no phase/output in the iprj, so theirs is zeroed on both sides.
_Sig = tuple[tuple[int, int, int, int], ...]


def _sensor_signature(sensor: Sensor) -> _Sig:
    ev = tuple(
        (0, int(z.phase_number or 0), int(z.output_number or 0), len(z.points))
        for z in sensor.event_zones if z.points)
    ig = tuple((1, 0, 0, len(z.points)) for z in sensor.ignore_zones if z.points)
    return ev + ig


def _slot_signature(zones: list[RawZone], slot: int) -> _Sig:
    ev = tuple(
        (0, z.phase, z.output, len(z.points_m))
        for z in zones if z.slot == slot and not z.is_ignore)
    ig = tuple(
        (1, 0, 0, len(z.points_m))
        for z in zones if z.slot == slot and z.is_ignore)
    return ev + ig


def match_slots(project: Project, zones: list[RawZone]) -> dict[int, int]:
    """Identify each ``Z;`` slot with the project sensor whose zone signature
    it equals — empty signatures can't match, and any signature shared by two
    slots or two sensors is dropped entirely (a guess would poison the fit)."""
    slot_sigs = {s: _slot_signature(zones, s) for s in {z.slot for z in zones}}
    sensor_sigs = {i: _sensor_signature(s) for i, s in enumerate(project.sensors)}
    mapping: dict[int, int] = {}
    for slot, ssig in slot_sigs.items():
        if not ssig or list(slot_sigs.values()).count(ssig) > 1:
            continue
        hits = [i for i, sig in sensor_sigs.items() if sig == ssig]
        if len(hits) == 1:
            mapping[slot] = hits[0]
    return mapping


def _centroid(pts: list[tuple[float, float]]) -> tuple[float, float]:
    n = len(pts)
    return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)


def fit(project: Project, zones: list[RawZone]) -> ZoneFit | None:
    """Similarity over matched zone centroids; None → keep translation."""
    mapping = match_slots(project, zones)
    if not mapping:
        return None
    emp = effective_meter_per_pixel(project.background)

    evo: list[complex] = []
    world: list[complex] = []
    for slot, si in sorted(mapping.items()):
        sensor = project.sensors[si]
        iprj_zones = (
            [z for z in sensor.event_zones if z.points]
            + [z for z in sensor.ignore_zones if z.points])
        stream_zones = (
            [z for z in zones if z.slot == slot and not z.is_ignore]
            + [z for z in zones if z.slot == slot and z.is_ignore])
        # match_slots guarantees the two lists pair up index-for-index
        for zs, zi in zip(stream_zones, iprj_zones):
            ec = _centroid(list(zs.points_m))
            mc = _centroid(list(zi.points))
            evo.append(complex(m_to_ft(ec[0]), m_to_ft(ec[1])))
            world.append(complex(px_to_ft(mc[0], emp), px_to_ft(mc[1], emp)))

    n = len(evo)
    if n < MIN_ZONES:
        return None
    if max(abs(p - q) for p in evo for q in evo) < MIN_SPREAD_FT:
        return None

    me = sum(evo) / n
    mw = sum(world) / n
    den = sum(abs(e - me) ** 2 for e in evo)
    if den == 0:
        return None
    a = sum((w - mw) * (e - me).conjugate() for e, w in zip(evo, world)) / den
    t = mw - a * me
    residuals = [abs(a * e + t - w) for e, w in zip(evo, world)]
    mean_res = sum(residuals) / n
    if mean_res > MAX_MEAN_RESIDUAL_FT:
        return None

    return ZoneFit(
        a_re=a.real, a_im=a.imag, t_x=t.real, t_y=t.imag,
        n_zones=n,
        rotation_deg=math.degrees(math.atan2(a.imag, a.real)),
        scale=abs(a),
        mean_residual_ft=mean_res,
        max_residual_ft=max(residuals),
        slot_to_sensor=tuple(sorted(mapping.items())),
    )
