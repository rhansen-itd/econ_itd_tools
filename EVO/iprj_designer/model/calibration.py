"""Per-sensor calibration + group placement — the composed overlay transform.

ROADMAP Item 39, implementing CALIBRATION_ALIGNMENT_PLAN.md (Item 38). Two
transforms that differ in kind, composed in a fixed order:

    EVO frame (m) → per-sensor calibration Cᵢ → group placement G → world feet
                  └── sensors agree ──┘        └ cluster seated on map ┘

* **Calibration** (``RigidDelta`` per sensor) is relational and background-
  blind: it reads only isolated same-vehicle detection pairs and makes the
  sensors *agree with each other*. It is rigid — rotate + translate, never a
  similarity — because the sensors share one physical scale and only their
  eyeballed position/azimuth are wrong. Applied in EVO-meter space, per
  sensor, before the group placement.
* **Group placement** (``ZoneFit`` or ``Placement``) seats the now-locked
  cluster onto the map. The auto value is ``zonefit`` refit over *calibrated*
  zone centroids (plan §1); a manual override edits translation + rotation
  only (plan §3, the value Item 40's group drag writes).

The solver is the rigid sibling of ``zonefit``'s similarity solve: the same
pure-Python complex least-squares with the fitted multiplier normalized to
unit modulus, replacing ``EVO/sensor_calibration.py``'s scipy Powell search
with the exact closed form (plan §2a — scipy/pandas/numpy are not, and must
not become, ``model/`` dependencies). It is reference-anchored: sensor
``reference`` is the gauge fix ``C₀ = identity``; every other sensor solves
against it pairwise (plan §2b; the joint solve over a weak overlap graph is
a documented upgrade, not this cut).

Guardrails carry ``zonefit``'s refuse-don't-guess character (plan §7): a
sensor with too few / too clustered / too inconsistent pairs stays
uncalibrated (identity) and **flagged** — a wrong correction is worse than
none — and nothing here raises on degenerate input.

The one convention-sensitive line is the azimuth commit sign (plan §5c):
``theta_deg`` uses the same rotation sense as ``sensor_calibration.py``'s
field-validated "ADD θ°" recommendation (complex-plane angle in the y-down
EVO frame), and the commit→re-solve round-trip test pins it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Mapping

from . import zonefit
from .units import effective_meter_per_pixel, ft_to_m, ft_to_px, m_to_ft, px_to_ft
from .zonefit import RawZone, ZoneFit

if TYPE_CHECKING:
    from .iprj_io import Project
    from .replay import Frame

# Pairing / trust gates, inherited from EVO/sensor_calibration.py's proven
# values (plan §2c) plus the zonefit-analogue lever-arm and residual gates.
ISOLATION_RADIUS_M = 15.0   # a detection counts only if alone within this
COARSE_MATCH_DIST_M = 10.0  # max distance to pair a detection to the reference
MIN_PAIRS = 50              # below: the fit would be noise -> flagged
MIN_SPREAD_M = 15.0         # ≈ zonefit's 50 ft lever arm: below, rotation is
#                             under-constrained -> translation-only + flagged
MAX_MEAN_RESIDUAL_M = 5.0   # above: pairs are non-rigidly inconsistent (bad
#                             matching, not bad mounting) -> refuse + flag
FRAME_STRIDE = 5            # sample every Nth frame, decorrelating pairs


# --- the per-sensor rigid correction -----------------------------------------


@dataclass(frozen=True)
class RigidDelta:
    """One sensor's calibration correction in EVO meters: ``p' = r·p + d``.

    ``r`` is a unit-modulus complex rotation (no scale — see module doc) kept
    as floats so the dataclass stays trivially serializable/comparable, like
    ``ZoneFit``. ``theta_deg`` is its angle in the y-down EVO frame, the same
    sense ``sensor_calibration.py`` reports ("ADD θ° to azimuth").
    """

    r_re: float
    r_im: float
    d_x: float  # meters
    d_y: float

    @classmethod
    def make(cls, theta_deg: float = 0.0,
             d_m: tuple[float, float] = (0.0, 0.0)) -> RigidDelta:
        th = math.radians(theta_deg)
        return cls(math.cos(th), math.sin(th), d_m[0], d_m[1])

    @property
    def theta_deg(self) -> float:
        return math.degrees(math.atan2(self.r_im, self.r_re))

    def apply_m(self, x_m: float, y_m: float) -> tuple[float, float]:
        p = (complex(self.r_re, self.r_im) * complex(x_m, y_m)
             + complex(self.d_x, self.d_y))
        return p.real, p.imag

    def compose(self, other: RigidDelta) -> RigidDelta:
        """``self ∘ other``: apply *other* first, then *self*."""
        r1, d1 = complex(self.r_re, self.r_im), complex(self.d_x, self.d_y)
        r2, d2 = complex(other.r_re, other.r_im), complex(other.d_x, other.d_y)
        r, d = r1 * r2, r1 * d2 + d1
        return RigidDelta(r.real, r.imag, d.real, d.imag)

    def inverse(self) -> RigidDelta:
        r = complex(self.r_re, self.r_im).conjugate()  # |r| = 1
        d = -(r * complex(self.d_x, self.d_y))
        return RigidDelta(r.real, r.imag, d.real, d.imag)


IDENTITY = RigidDelta(1.0, 0.0, 0.0, 0.0)


# --- pair finding (background-blind, raw EVO meters) --------------------------

# ((ref_x_m, ref_y_m), (sensor_x_m, sensor_y_m)) — one isolated same-vehicle
# detection seen by the reference sensor and by the sensor being calibrated.
Pair = tuple[tuple[float, float], tuple[float, float]]


def find_pairs(
    frames: Iterable[Frame],
    sensor: int,
    reference: int = 0,
    *,
    isolation_radius_m: float = ISOLATION_RADIUS_M,
    coarse_match_dist_m: float = COARSE_MATCH_DIST_M,
    frame_stride: int = FRAME_STRIDE,
) -> list[Pair]:
    """Isolated same-vehicle pairs between *reference* and *sensor*.

    ``sensor_calibration.py``'s gates generalized per sensor (plan §2c): a
    reference detection counts only if no other reference detection is within
    the isolation radius; it pairs to the nearest *sensor* detection within
    the coarse gate, which must itself be isolated among its own sensor's
    detections. Reads only ``x_raw_m``/``y_raw_m`` — never the map.
    """
    pairs: list[Pair] = []
    for f in list(frames)[:: max(frame_stride, 1)]:
        ref_pts = [(p.x_raw_m, p.y_raw_m) for p in f.points if p.sensor == reference]
        sen_pts = [(p.x_raw_m, p.y_raw_m) for p in f.points if p.sensor == sensor]
        if not ref_pts or not sen_pts:
            continue
        for rx, ry in ref_pts:
            if sum(1 for x, y in ref_pts
                   if math.hypot(x - rx, y - ry) < isolation_radius_m) > 1:
                continue
            best = min(sen_pts, key=lambda q: math.hypot(q[0] - rx, q[1] - ry))
            if math.hypot(best[0] - rx, best[1] - ry) >= coarse_match_dist_m:
                continue
            if sum(1 for x, y in sen_pts
                   if math.hypot(x - best[0], y - best[1]) < isolation_radius_m) > 1:
                continue
            pairs.append(((rx, ry), best))
    return pairs


# --- the relational solver -----------------------------------------------------


@dataclass(frozen=True)
class SensorCalibration:
    """One sensor's solve outcome, for the fit-quality readout (plan §7)."""

    sensor: int
    # "reference" | "ok" | "translation_only" | "too_few_pairs" | "no_pairs"
    # | "high_residual" — anything but "reference"/"ok" is flagged.
    status: str
    delta: RigidDelta
    n_pairs: int
    mean_residual_m: float | None = None
    max_residual_m: float | None = None

    @property
    def flagged(self) -> bool:
        return self.status not in ("reference", "ok")


@dataclass(frozen=True)
class Calibration:
    """The solved, locked inter-sensor relationship ``{Cᵢ}`` (plan §2d)."""

    reference: int
    sensors: tuple[SensorCalibration, ...]

    @property
    def deltas(self) -> dict[int, RigidDelta]:
        """Only the trusted corrections; flagged sensors stay identity by
        *absence* (``AlignmentTransform`` treats a missing key as identity),
        so a refused solve can never silently move a sensor."""
        return {s.sensor: s.delta for s in self.sensors
                if s.status in ("ok", "translation_only")}

    @property
    def flagged(self) -> tuple[SensorCalibration, ...]:
        return tuple(s for s in self.sensors if s.flagged)

    def for_sensor(self, sensor: int) -> SensorCalibration | None:
        return next((s for s in self.sensors if s.sensor == sensor), None)


def _solve(pairs: list[Pair], *, rotate: bool) -> tuple[RigidDelta, float, float]:
    """Closed-form rigid LS mapping sensor points onto reference points —
    zonefit's complex kernel with the multiplier normalized to unit modulus
    (plan §2a). Returns (delta, mean_residual_m, max_residual_m)."""
    n = len(pairs)
    dst = [complex(*r) for r, _ in pairs]
    src = [complex(*s) for _, s in pairs]
    ms, md = sum(src) / n, sum(dst) / n
    r = complex(1.0, 0.0)
    if rotate:
        a = sum((d - md) * (s - ms).conjugate() for s, d in zip(src, dst))
        if abs(a) > 0:
            r = a / abs(a)
    d = md - r * ms
    residuals = [abs(r * s + d - t) for s, t in zip(src, dst)]
    delta = RigidDelta(r.real, r.imag, d.real, d.imag)
    return delta, sum(residuals) / n, max(residuals)


def _spread_m(pts: list[tuple[float, float]]) -> float:
    """Bounding-box diagonal — the lever-arm proxy for the rotation gate."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def calibrate(
    frames: Iterable[Frame],
    *,
    reference: int = 0,
    isolation_radius_m: float = ISOLATION_RADIUS_M,
    coarse_match_dist_m: float = COARSE_MATCH_DIST_M,
    min_pairs: int = MIN_PAIRS,
    min_spread_m: float = MIN_SPREAD_M,
    max_mean_residual_m: float = MAX_MEAN_RESIDUAL_M,
    frame_stride: int = FRAME_STRIDE,
) -> Calibration:
    """Solve the relational calibration over every sensor seen in *frames*.

    Reference-anchored (plan §2b): ``C[reference] = identity`` is the gauge
    fix; each other sensor fits the rigid map that carries its detections
    onto the reference's. Never raises on degenerate input — a sensor that
    can't be trusted comes back flagged with an identity delta instead.
    """
    frames = list(frames)
    seen = sorted({p.sensor for f in frames for p in f.points})
    entries: list[SensorCalibration] = []
    for s in seen:
        if s == reference:
            entries.append(SensorCalibration(s, "reference", IDENTITY, 0))
            continue
        pairs = find_pairs(
            frames, s, reference,
            isolation_radius_m=isolation_radius_m,
            coarse_match_dist_m=coarse_match_dist_m,
            frame_stride=frame_stride)
        if not pairs:
            entries.append(SensorCalibration(s, "no_pairs", IDENTITY, 0))
            continue
        if len(pairs) < min_pairs:
            entries.append(SensorCalibration(
                s, "too_few_pairs", IDENTITY, len(pairs)))
            continue
        rotate = _spread_m([p for _, p in pairs]) >= min_spread_m
        delta, mean_r, max_r = _solve(pairs, rotate=rotate)
        if mean_r > max_mean_residual_m:
            entries.append(SensorCalibration(
                s, "high_residual", IDENTITY, len(pairs), mean_r, max_r))
            continue
        entries.append(SensorCalibration(
            s, "ok" if rotate else "translation_only",
            delta, len(pairs), mean_r, max_r))
    return Calibration(reference=reference, sensors=tuple(entries))


# --- group placement -----------------------------------------------------------


@dataclass(frozen=True)
class Placement:
    """An editable group transform with ``ZoneFit``'s shape and ``apply_m``
    signature (plan §3): ``world_ft = a * evo_ft + t`` in complex form. Used
    when there is no ``Z;`` fit (translation seed) or after a manual group
    move; ``AlignmentTransform`` treats it and ``ZoneFit`` interchangeably."""

    a_re: float
    a_im: float
    t_x: float  # world feet
    t_y: float

    @property
    def rotation_deg(self) -> float:
        return math.degrees(math.atan2(self.a_im, self.a_re))

    @property
    def scale(self) -> float:
        return abs(complex(self.a_re, self.a_im))

    def apply_m(self, x_m: float, y_m: float) -> tuple[float, float]:
        """EVO meters → world feet (y-down on both sides) — same math as
        ``ZoneFit.apply_m``."""
        e = complex(m_to_ft(x_m), m_to_ft(y_m))
        w = complex(self.a_re, self.a_im) * e + complex(self.t_x, self.t_y)
        return w.real, w.imag


def translation_placement(
    anchor_ft: tuple[float, float], ref_m: tuple[float, float],
) -> Placement:
    """The no-``Z;`` seed: replay's translation fallback
    ``world = anchor + m_to_ft(p - ref)`` expressed as a Placement (scale 1,
    no rotation), promoted to a single whole-group transform (plan §3)."""
    return Placement(
        1.0, 0.0,
        anchor_ft[0] - m_to_ft(ref_m[0]),
        anchor_ft[1] - m_to_ft(ref_m[1]))


def translated(placement: ZoneFit | Placement,
               dx_ft: float, dy_ft: float) -> Placement:
    """The group-drag edit: shift the seated cluster in world feet. Accepts a
    ``ZoneFit`` seed and returns a ``Placement`` (the manual-override value)."""
    return Placement(placement.a_re, placement.a_im,
                     placement.t_x + dx_ft, placement.t_y + dy_ft)


def rotated_about(placement: ZoneFit | Placement,
                  pivot_ft: tuple[float, float], angle_deg: float) -> Placement:
    """The group-rotate edit: rotate the seated cluster about a world-feet
    pivot. Positive angle follows ``rotation_deg``'s sense (y-down world:
    clockwise on screen). Scale is untouched — the manual handle deliberately
    exposes only translate + rotate (plan §3)."""
    th = math.radians(angle_deg)
    q = complex(math.cos(th), math.sin(th))
    pv = complex(pivot_ft[0], pivot_ft[1])
    a = q * complex(placement.a_re, placement.a_im)
    t = q * (complex(placement.t_x, placement.t_y) - pv) + pv
    return Placement(a.real, a.imag, t.real, t.imag)


def nudged_delta(delta: RigidDelta, placement: ZoneFit | Placement,
                 dw_ft: tuple[float, float]) -> RigidDelta:
    """Shift a per-sensor calibration so its markers move by ``dw_ft`` world
    feet — the *unlocked* group-adjust gesture (plan §4: unlocked drag → one
    sensor's ``Cᵢ``, hand-adjusting the calibration).

    A world-feet move ``Δw`` corresponds to a pre-placement EVO-meter
    translation of ``ft_to_m(Δw / a)`` (``a`` is *placement*'s linear part),
    because ``world = placement(Cᵢ(e_m))`` and adding ``Δd_m`` to ``Cᵢ``'s
    translation moves the world point by ``a · m_to_ft(Δd_m)``. Rotation is
    left untouched — the manual per-sensor handle nudges position only, the
    same restraint the group handle (``translated``) keeps. A degenerate
    zero-scale placement can't be inverted, so the delta passes through."""
    a = complex(placement.a_re, placement.a_im)
    if a == 0:
        return delta
    dm = complex(dw_ft[0], dw_ft[1]) / a
    return RigidDelta(delta.r_re, delta.r_im,
                      delta.d_x + ft_to_m(dm.real),
                      delta.d_y + ft_to_m(dm.imag))


def invert_placement_m(placement: ZoneFit | Placement,
                       x_ft: float, y_ft: float) -> tuple[float, float]:
    """World feet → EVO meters, the inverse of ``apply_m`` (the commit math
    needs it to carry a sensor's stored position into the frame ``Cᵢ`` acts
    on). Raises ValueError on a zero-scale placement — no valid fit or seed
    ever produces one."""
    a = complex(placement.a_re, placement.a_im)
    if a == 0:
        raise ValueError("degenerate placement (zero scale) cannot be inverted")
    e = (complex(x_ft, y_ft) - complex(placement.t_x, placement.t_y)) / a
    return ft_to_m(e.real), ft_to_m(e.imag)


# --- the composed transform ------------------------------------------------------


@dataclass(frozen=True)
class AlignmentTransform:
    """The one overlay transform both replay and live render through (plan
    §1): per-sensor calibration in EVO meters, then the group placement to
    world feet. A sensor missing from ``calib`` passes through untouched, so
    an empty dict reduces the whole pipeline to exactly the placement — the
    plan-§0 zero-regression reduction."""

    calib: Mapping[int, RigidDelta]  # keyed by stream sensor id (oid % 10)
    placement: ZoneFit | Placement
    calibration: Calibration | None = None  # full solve report, for status UI

    def apply(self, sensor: int, x_m: float, y_m: float) -> tuple[float, float]:
        delta = self.calib.get(sensor)
        if delta is not None:
            x_m, y_m = delta.apply_m(x_m, y_m)
        return self.placement.apply_m(x_m, y_m)


def build_alignment(
    project: Project,
    zones: Iterable[RawZone],
    calibration: Calibration | None = None,
    *,
    anchor_ft: tuple[float, float] | None = None,
    ref_m: tuple[float, float] = (0.0, 0.0),
) -> AlignmentTransform | None:
    """Compose the two layers for a site: ``G`` fit by ``zonefit`` over the
    *calibrated* zone centroids (plan §1 — calibration is background-blind,
    so there is no circularity), else the translation seed from *anchor_ft*
    (the no-``Z;`` path, plan §3). With no calibration the ``Z;`` fit is
    bit-identical to today's, and None means the caller keeps the legacy
    per-point translation fallback."""
    deltas = calibration.deltas if calibration is not None else {}
    zones = list(zones)
    placement: ZoneFit | Placement | None = (
        zonefit.fit(project, zones, calib=deltas or None) if zones else None)
    if placement is None:
        if anchor_ft is None:
            return None
        placement = translation_placement(anchor_ft, ref_m)
    return AlignmentTransform(calib=deltas, placement=placement,
                              calibration=calibration)


# --- commit math (plan §5c) -------------------------------------------------------


def committed_sensor_config(
    azimuth_deg: float,
    position_px: tuple[float, float],
    delta: RigidDelta,
    placement: ZoneFit | Placement,
    emp: float,
) -> tuple[float, tuple[float, float]]:
    """Fold one sensor's calibration into its iprj config; returns
    ``(new_azimuth_deg, (new_x_px, new_y_px))``.

    The unique "rotate about the sensor, then move the sensor" decomposition
    of ``Cᵢ``: the azimuth gains ``theta_deg`` (the "ADD θ°" sign of
    ``sensor_calibration.py``, pinned by the commit→re-solve round-trip
    test), and the new position is ``Cᵢ`` applied to the sensor's own
    location. The stored position lives in world px, ``Cᵢ`` acts in EVO
    meters, so the position round-trips px → ft → (G⁻¹) → meters → Cᵢ →
    (G) → ft → px; conjugating a rigid map by the similarity ``G`` keeps it
    rigid with the same rotation angle, which is why the azimuth needs no
    placement term. Positions are in the post-``normalize_origin`` world-px
    frame every loaded Project already uses."""
    pos_ft = (px_to_ft(position_px[0], emp), px_to_ft(position_px[1], emp))
    e_m = invert_placement_m(placement, *pos_ft)
    w_ft = placement.apply_m(*delta.apply_m(*e_m))
    new_px = (ft_to_px(w_ft[0], emp), ft_to_px(w_ft[1], emp))
    return azimuth_deg + delta.theta_deg, new_px


def commit_calibration(
    project: Project,
    alignment: AlignmentTransform,
    slot_to_sensor: Mapping[int, int] | None = None,
) -> dict[int, tuple[float, tuple[float, float]]]:
    """The whole-project commit as a pure function (Item 40 just applies it):
    ``{project sensor index: (new_azimuth_deg, (new_x_px, new_y_px))}`` for
    every sensor carrying a calibration delta. Nothing is mutated.

    Only calibration commits — group placement is either reproducible from
    ``Z;`` every load or belongs to the deferred sidecar, never smeared into
    per-sensor azimuth (plan §5b). *slot_to_sensor* maps stream sensor ids to
    project sensor indices; it defaults from the placement's ``ZoneFit``
    match, so it only needs passing on a no-``Z;`` site. Sensors without a
    mapping or without a stored position are skipped, not guessed."""
    if slot_to_sensor is None:
        slot_to_sensor = dict(
            getattr(alignment.placement, "slot_to_sensor", ()) or ())
    emp = effective_meter_per_pixel(project.background)
    out: dict[int, tuple[float, tuple[float, float]]] = {}
    for slot, delta in alignment.calib.items():
        si = slot_to_sensor.get(slot)
        if si is None or not 0 <= si < len(project.sensors):
            continue
        sensor = project.sensors[si]
        if sensor.position_x is None or sensor.position_y is None:
            continue
        out[si] = committed_sensor_config(
            sensor.azimuth_angle or 0.0,
            (sensor.position_x, sensor.position_y),
            delta, alignment.placement, emp)
    return out
