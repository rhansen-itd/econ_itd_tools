"""EVO recording playback engine (ROADMAP Item 29, RECORD_PLAYBACK_PLAN.md).

Parses a raw EVO recording — the file ``../evo_recorder.py`` writes: an
``HH:MM:SS.mmm`` wall-clock line before every websocket message, ``F;`` track
frames, and a ``C;`` reference line — and aligns every track point into the
designer's canonical world-feet space, anchored to one sensor of the loaded
Project.

The transform is a 2D **similarity** (rotation + uniform scale + translation)
fit from the sensor correspondences the recording itself carries: a ``C;``
line reports *every* sensor's position in the EVO frame (groups of three —
``x, y, confidence`` — per slot, absent sensors written ``?``), and the
loaded Project stores those same sensors' map positions in world pixels. Two
or more matched sensors pin down orientation *and* scale; ``build_align_transform``
Umeyama-fits ``AlignTransform`` over them (``model.replay.AlignTransform.apply``
is the single seam every ``TrackPoint`` passes through).

This resolves the two open items plan §7 left for real data (LIVE_OVERLAY_PLAN
§7): a real capture showed the EVO frame is **rotated** relative to the map
(≈27° at Banks, ≈4.5° at US95&SH8) — a single-anchor pure translation left
that rotation in, so tracks came out visibly skewed — and that the EVO
metric distance and the map's calibrated distance disagree by a few percent
(stored MeterPerPixel / sensor-placement error), a residual the fitted scale
absorbs. The earlier "m_to_ft alone, never through MeterPerPixel" reasoning
(plan §1b) held only for the *single*-reference case, where no second point
exists to derive rotation/scale; with ≥2 references the empirical fit is
strictly better and lands each reference sensor exactly.

Fallback: with fewer than two matched references (a single-sensor site, or a
recording whose ``C;`` names only one sensor) the transform degrades to the
historical pure translation anchored to ``sensor_index`` — ``a=1, b=0`` in
``AlignTransform`` — so single-reference behavior (and its tests) is unchanged.
Everything here is pure and pandas-free (plan §§2-3);
``Recording.to_dataframe()`` imports pandas lazily for notebook use only.

The streaming counterpart (ROADMAP Item 33, LIVE_OVERLAY_PLAN.md §2) is
``LiveAligner``: feed it one live websocket message at a time and it emits
the same aligned ``Frame``s incrementally, holding the ``C;`` reference and
current timestamp as state. Both paths share one copy of the line grammar
(``_parse_ref`` / ``_parse_frame_entities``) and one copy of the transform
(``_align_frame``); they differ only in who holds the state — a local scan
over the whole file vs. instance attributes across ``feed`` calls.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from .iprj_io import Project
from .units import effective_meter_per_pixel, m_to_ft, px_to_ft

# Load-time guardrails (plan §6): a long capture can't animate 50k frames.
# Pass None to lift a cap; the GUI exposes the knobs.
DEFAULT_MAX_FRAMES = 5000
DEFAULT_MAX_POINTS_PER_FRAME = 200

_TIME_RE = re.compile(r"^\d\d:\d\d:\d\d")

# Marker color per sensor (oid % 10), mirroring evo_replay.SENSOR_COLORS so the
# in-designer Replay overlay (Item 30) reads the same as the standalone plotter.
# The palette is a pure render helper — kept here in the model so the GUI's SVG
# builder is a thin consumer and the mapping is unit-testable headless.
SENSOR_COLORS = {
    0: "cyan",
    1: "yellow",
    2: "lime",
    3: "magenta",
    4: "orange",
    5: "deepskyblue",
}
_FALLBACK_COLOR = "white"  # unknown sensors, as in evo_replay


def marker_color(sensor: int) -> str:
    """Overlay color for a track point, keyed by its ``sensor`` (oid % 10)."""
    return SENSOR_COLORS.get(sensor, _FALLBACK_COLOR)


def short_id(oid: int, digits: int = 4) -> str:
    """Abbreviated object id for the on-marker label (evo_replay's convention:
    the trailing ``digits`` of the id). ``digits <= 0`` yields the empty string,
    matching evo_replay's label-disable path."""
    if digits <= 0:
        return ""
    return str(oid)[-digits:]


@dataclass(frozen=True)
class TrackPoint:
    oid: int
    sensor: int  # oid % 10, the vendor's id convention (as in evo_replay)
    cls: int | None
    x_ft: float  # world feet, y-down
    y_ft: float
    heading: float | None
    x_raw_m: float  # untransformed EVO meters, kept for hover/debug
    y_raw_m: float


@dataclass(frozen=True)
class Frame:
    t: str  # recorder wall-clock stamp, "HH:MM:SS.mmm"
    points: tuple[TrackPoint, ...]


@dataclass(frozen=True)
class AlignTransform:
    """EVO-frame (meters) → world-feet 2D similarity: rotation + scale + shift.

    ``apply`` — the one seam every ``TrackPoint`` is aligned through — is
    ``world = R(θ)·s·m_to_ft(p) + t`` written out with the composed
    coefficients ``a = s·cosθ`` and ``b = s·sinθ`` (so a=1,b=0 is the pure
    translation fallback). ``rotation_deg``/``scale`` are the decomposed
    parameters, surfaced for the load/status readout; ``n_refs`` is how many
    sensor correspondences the fit used (``>= 2`` means the similarity fit ran,
    ``< 2`` the translation fallback)."""

    a: float   # scale·cos(theta), EVO-feet x → world-feet
    b: float   # scale·sin(theta)
    tx: float  # world-feet translation
    ty: float
    rotation_deg: float
    scale: float
    n_refs: int

    def apply(self, x_m: float, y_m: float) -> tuple[float, float]:
        ex, ey = m_to_ft(x_m), m_to_ft(y_m)
        return (self.a * ex - self.b * ey + self.tx,
                self.b * ex + self.a * ey + self.ty)


@dataclass(frozen=True)
class Recording:
    sensor_index: int  # anchor sensor (fallback translation); moot for the fit
    ref_m: tuple[float, float]  # EVO C; reference; (0, 0) when none was seen
    ref_seen: bool
    anchor_ft: tuple[float, float]  # sensor[sensor_index] in world feet
    transform: AlignTransform  # EVO-frame → world-feet fit for every point
    frames: list[Frame]  # frames[i] is frame i -> O(1) timeline scrub

    def to_dataframe(self):
        """Flatten to a tidy pandas DataFrame (notebook convenience only).

        pandas is imported lazily so the module stays dependency-free for
        the model layer and its tests.
        """
        import pandas as pd

        rows = [
            {
                "Frame": i, "Time": f.t, "ID": p.oid, "Sensor": p.sensor,
                "Class": p.cls, "X_ft": p.x_ft, "Y_ft": p.y_ft,
                "Heading": p.heading, "X_raw_m": p.x_raw_m, "Y_raw_m": p.y_raw_m,
            }
            for i, f in enumerate(self.frames)
            for p in f.points
        ]
        return pd.DataFrame(rows)


def anchor_world_ft(project: Project, sensor_index: int) -> tuple[float, float]:
    """World-feet position of the sensor a recording aligns to.

    The one place emp touches the transform: the anchor is stored in world
    pixels, so it converts via px_to_ft with the calibrated scale.
    """
    if not 0 <= sensor_index < len(project.sensors):
        raise ValueError(
            f"sensor_index {sensor_index} out of range "
            f"(project has {len(project.sensors)} sensors)")
    sensor = project.sensors[sensor_index]
    if sensor.position_x is None or sensor.position_y is None:
        raise ValueError(f"sensor {sensor_index} has no position")
    emp = effective_meter_per_pixel(project.background)
    return (px_to_ft(sensor.position_x, emp), px_to_ft(sensor.position_y, emp))


def _fit_similarity(
    corr: list[tuple[tuple[float, float], tuple[float, float]]],
) -> AlignTransform | None:
    """Umeyama 2D similarity fit mapping EVO-feet → world-feet over ``corr``
    (``((ex, ey), (mx, my))`` pairs, both in feet). Returns None when the EVO
    points are coincident (no scale/rotation recoverable); the caller then
    drops to the translation fallback. With exactly two pairs the fit is exact
    (each reference lands on its map anchor); with more it is least-squares."""
    n = len(corr)
    ecx = sum(c[0][0] for c in corr) / n
    ecy = sum(c[0][1] for c in corr) / n
    mcx = sum(c[1][0] for c in corr) / n
    mcy = sum(c[1][1] for c in corr) / n
    a_num = b_num = var_e = 0.0
    for (ex, ey), (mx, my) in corr:
        ex_, ey_ = ex - ecx, ey - ecy
        mx_, my_ = mx - mcx, my - mcy
        a_num += mx_ * ex_ + my_ * ey_
        b_num += my_ * ex_ - mx_ * ey_
        var_e += ex_ * ex_ + ey_ * ey_
    if var_e <= 0:
        return None
    theta = math.atan2(b_num, a_num)
    scale = math.hypot(a_num, b_num) / var_e
    a = scale * math.cos(theta)
    b = scale * math.sin(theta)
    tx = mcx - (a * ecx - b * ecy)
    ty = mcy - (b * ecx + a * ecy)
    return AlignTransform(a, b, tx, ty, math.degrees(theta), scale, n)


def build_align_transform(
    project: Project,
    evo_slots: dict[int, tuple[float, float]],
    *,
    sensor_index: int,
    ref: tuple[float, float],
) -> AlignTransform:
    """The EVO-frame → world-feet transform for one recording.

    ``evo_slots`` maps a sensor index to its position in the EVO frame (meters),
    as parsed from the ``C;`` line. Every project sensor that has both an EVO
    slot and a map position is a correspondence; ≥2 of them drive the similarity
    fit (rotation + scale, so the overlay's orientation *and* residual scale are
    corrected). With fewer — or a degenerate fit — it falls back to the historical
    pure translation anchored to ``sensor_index`` against ``ref``, preserving
    single-reference behavior exactly."""
    emp = effective_meter_per_pixel(project.background)
    corr: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for si, sensor in enumerate(project.sensors):
        pos = evo_slots.get(si)
        if pos is None or sensor.position_x is None or sensor.position_y is None:
            continue
        corr.append((
            (m_to_ft(pos[0]), m_to_ft(pos[1])),
            (px_to_ft(sensor.position_x, emp), px_to_ft(sensor.position_y, emp)),
        ))
    if len(corr) >= 2:
        fit = _fit_similarity(corr)
        if fit is not None:
            return fit
    anchor = anchor_world_ft(project, sensor_index)
    return AlignTransform(
        1.0, 0.0,
        anchor[0] - m_to_ft(ref[0]),
        anchor[1] - m_to_ft(ref[1]),
        0.0, 1.0, len(corr))


def load_recording(
    project: Project,
    path: str | Path,
    *,
    sensor_index: int = 0,
    downsample_rate: int = 1,
    max_frames: int | None = DEFAULT_MAX_FRAMES,
    max_points_per_frame: int | None = DEFAULT_MAX_POINTS_PER_FRAME,
) -> Recording:
    """Read a recording file and align it to *project*'s *sensor_index*."""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    return parse_recording(
        project, text,
        sensor_index=sensor_index,
        downsample_rate=downsample_rate,
        max_frames=max_frames,
        max_points_per_frame=max_points_per_frame,
    )


def parse_recording(
    project: Project,
    text: str,
    *,
    sensor_index: int = 0,
    downsample_rate: int = 1,
    max_frames: int | None = DEFAULT_MAX_FRAMES,
    max_points_per_frame: int | None = DEFAULT_MAX_POINTS_PER_FRAME,
) -> Recording:
    """Parse recording *text* and align every point into world feet.

    Frames with no tracked entities are kept (an empty intersection is a
    real playback moment; evo_replay dropped them only as a side effect of
    its row-per-point shape). Raises ValueError when no ``F;`` frame parses
    at all. Downsampling keeps every ``downsample_rate``-th frame, then
    ``max_frames`` caps the total (plan §6).
    """
    ref, ref_seen, slots, raw_frames = _parse_lines(text)
    if not raw_frames:
        raise ValueError("no F; track frames found in recording")

    raw_frames = raw_frames[:: max(downsample_rate, 1)]
    if max_frames is not None:
        raw_frames = raw_frames[:max_frames]

    anchor = anchor_world_ft(project, sensor_index)
    transform = build_align_transform(
        project, slots, sensor_index=sensor_index, ref=ref)
    frames = [
        _align_frame(t, entities, transform, max_points_per_frame)
        for t, entities in raw_frames
    ]

    return Recording(
        sensor_index=sensor_index,
        ref_m=ref,
        ref_seen=ref_seen,
        anchor_ft=anchor,
        transform=transform,
        frames=frames,
    )


# --- streaming alignment (ROADMAP Item 33, LIVE_OVERLAY_PLAN.md §2) ----------


class LiveAligner:
    """Streaming counterpart of ``parse_recording``: one message per call.

    Built from a loaded ``Project`` + sensor index; ``feed(message)`` returns
    an aligned world-feet ``Frame`` when the message carries an ``F;`` track
    frame and ``None`` otherwise (``C;`` reference, timestamp, ``GetCfg``
    responses, malformed/partial lines). The ``C;`` reference and current
    timestamp persist across calls, so a stream that sends its reference once
    at the top and only ``F;`` afterward stays anchored for its whole life.

    A live websocket message carries no wall-clock line — the *recorder*
    prepends one when writing to disk — so ``feed`` accepts an optional ``t``
    the caller stamps (the GUI passes a ``datetime.now()``-formatted time;
    a file replay can instead just feed the recorded timestamp lines, which
    update the held time the same way). Timestamping stays with the caller so
    this class remains pure and deterministic.

    One documented divergence from the batch path: ``parse_recording`` scans
    the whole file, so a ``C;`` arriving *after* some frames still anchors
    them retroactively; a stream cannot rewrite frames it already emitted, so
    frames fed before any reference use the same ``(0, 0)`` fallback as the
    batch default and keep it. The real feed sends ``C;`` up front, so the
    two paths agree frame-for-frame on any well-formed stream.

    ``feed`` never raises on message content (the batch parser's
    skip-on-``ValueError`` discipline); only the constructor validates, the
    same way ``anchor_world_ft`` does for the batch path.
    """

    def __init__(
        self,
        project: Project,
        sensor_index: int = 0,
        *,
        max_points_per_frame: int | None = DEFAULT_MAX_POINTS_PER_FRAME,
    ) -> None:
        self._project = project
        self.sensor_index = sensor_index
        self.anchor_ft = anchor_world_ft(project, sensor_index)
        self.max_points_per_frame = max_points_per_frame
        self._ref = (0.0, 0.0)
        self._ref_seen = False
        self._t = "00:00:00.000"
        # No C; yet → translation fallback anchored to sensor_index; the first
        # C; rebuilds it as the full similarity fit (matching the batch path).
        self._transform = build_align_transform(
            project, {}, sensor_index=sensor_index, ref=self._ref)

    @property
    def ref_m(self) -> tuple[float, float]:
        return self._ref

    @property
    def ref_seen(self) -> bool:
        return self._ref_seen

    @property
    def transform(self) -> AlignTransform:
        return self._transform

    def feed(self, message: str, t: str | None = None) -> Frame | None:
        """Ingest one raw message; return the aligned ``Frame`` it carries.

        A live message is normally a single line; if one carries several
        ``F;`` lines (e.g. a whole recorded blob), every line still updates
        state losslessly and the last frame is the one returned — the live
        render slot is drop-to-latest anyway (plan §3).
        """
        if t is not None:
            self._t = t
        frame = None
        for line in message.splitlines():
            line = line.strip()
            if not line:
                continue

            if line.startswith("C;"):
                if not self._ref_seen:
                    slots = _parse_ref_all(line)
                    if 0 in slots:  # a usable first pair — first-one-wins
                        self._ref, self._ref_seen = slots[0], True
                        self._transform = build_align_transform(
                            self._project, slots,
                            sensor_index=self.sensor_index, ref=self._ref)
                continue

            if _TIME_RE.match(line):
                self._t = line
                continue

            if line.startswith("F;"):
                frame = _align_frame(
                    self._t, _parse_frame_entities(line),
                    self._transform, self.max_points_per_frame)

        return frame


# --- raw line parsing -------------------------------------------------------

# (oid, cls, x_m, y_m, heading) straight off an F; entity, pre-alignment
_RawEntity = tuple[int, "int | None", float, float, "float | None"]


def _parse_lines(
    text: str,
) -> tuple[tuple[float, float], bool, dict[int, tuple[float, float]], list[tuple[str, list[_RawEntity]]]]:
    """Collect the C; sensor references and the raw F; frames from recording text.

    Line grammar per evo_recorder's output (one timestamp line before each
    message) and evo_replay.parse_evo_data:

      * ``HH:MM:SS.mmm``            wall-clock stamp for the next message
      * ``F;a;b;c;mask;ent;ent;..`` entities as ``oid,class,x,y,heading,..``
      * ``C;x,y,c,x,y,c,...``       per-sensor references; first usable line wins

    Anything else (GetCfg responses, blank lines) is ignored. Returns the
    slot→position map (``_parse_ref_all``) plus ``ref`` = slot 0 (the historical
    single reference) and ``ref_seen``, for the translation fallback and the
    status readout.

    The per-line grammar lives in _parse_ref_all/_parse_frame_entities, shared
    with the streaming LiveAligner — this function only holds the scan state.
    """
    slots: dict[int, tuple[float, float]] = {}
    ref_seen = False
    current_time = "00:00:00.000"
    raw_frames: list[tuple[str, list[_RawEntity]]] = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("C;") and not ref_seen:
            parsed = _parse_ref_all(line)
            if 0 in parsed:  # a usable first pair — old first-one-wins
                slots, ref_seen = parsed, True
            continue

        if _TIME_RE.match(line):
            current_time = line
            continue

        if line.startswith("F;"):
            raw_frames.append((current_time, _parse_frame_entities(line)))

    return slots.get(0, (0.0, 0.0)), ref_seen, slots, raw_frames


# The vendor caps a project at 4 sensors (multifile.MAX_SENSORS); the cap also
# stops the trailing longitude,latitude,apikey fields from parsing as a 5th slot.
_MAX_SENSOR_SLOTS = 4


def _parse_ref_all(line: str) -> dict[int, tuple[float, float]]:
    """Every sensor position a ``C;`` line carries, ``{slot: (x_m, y_m)}``.

    The line is groups of three — ``x, y, confidence`` — per sensor slot 0..3,
    absent sensors written ``?``; a trailing ``longitude, latitude, apikey``
    follows the slots and the cap discards it. A slot whose x or y is not
    numeric (``?``) is omitted, so an unparseable first pair yields ``{}`` —
    the signal ``_parse_lines``/``LiveAligner`` use for old first-one-wins."""
    vals = line[2:].split(",")
    slots: dict[int, tuple[float, float]] = {}
    for idx in range(_MAX_SENSOR_SLOTS):
        i = idx * 3
        if i + 1 >= len(vals):
            break
        try:
            slots[idx] = (float(vals[i]), float(vals[i + 1]))
        except ValueError:
            continue
    return slots


def _parse_frame_entities(line: str) -> list[_RawEntity]:
    """The raw entities of an ``F;`` line; unparseable entities are skipped."""
    parts = line.split(";")
    # parts[0]='F', [1..4] frame header fields, [5:] entities
    entities: list[_RawEntity] = []
    for ent in parts[5:]:
        p = ent.split(",")
        if len(p) < 4:
            continue
        try:
            oid = int(p[0])
            x, y = float(p[2]), float(p[3])
        except ValueError:
            continue
        cls = int(p[1]) if _is_int(p[1]) else None
        heading = float(p[4]) if len(p) > 4 and _is_float(p[4]) else None
        entities.append((oid, cls, x, y, heading))
    return entities


def _align_frame(
    t: str,
    entities: list[_RawEntity],
    transform: AlignTransform,
    max_points_per_frame: int | None,
) -> Frame:
    """Align one raw frame into world feet through ``transform`` — the single
    seam every point crosses. Both the batch parser and the streaming
    LiveAligner build every Frame through here, so the rotation/scale/shift
    fit (LIVE_OVERLAY_PLAN §7) lives in exactly one place; y stays down on both
    sides (no sign flip)."""
    if max_points_per_frame is not None:
        entities = entities[:max_points_per_frame]
    points = []
    for oid, cls, x, y, heading in entities:
        x_ft, y_ft = transform.apply(x, y)
        points.append(TrackPoint(
            oid=oid,
            sensor=oid % 10,
            cls=cls,
            x_ft=x_ft,
            y_ft=y_ft,
            heading=heading,
            x_raw_m=x,
            y_raw_m=y,
        ))
    return Frame(t=t, points=tuple(points))


def _is_int(s: str) -> bool:
    try:
        int(s)
        return True
    except ValueError:
        return False


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False
