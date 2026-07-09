"""EVO recording playback engine (ROADMAP Item 29, RECORD_PLAYBACK_PLAN.md).

Parses a raw EVO recording — the file ``../evo_recorder.py`` writes: an
``HH:MM:SS.mmm`` wall-clock line before every websocket message, ``F;`` track
frames, and a ``C;`` reference line — and aligns every track point into the
designer's canonical world-feet space, anchored to one sensor of the loaded
Project.

The transform (plan §1b) has one correctness pivot: the EVO stream reports
positions in *true meters*, so a point's offset from the ``C;`` reference
converts to feet with ``m_to_ft`` alone — never through MeterPerPixel. Only
the sensor anchor, which the Project stores in world *pixels*, goes through
``effective_meter_per_pixel``:

    anchor_ft = px_to_ft(sensor[n].position, emp)
    world_ft  = anchor_ft + m_to_ft(p_m - ref_m)

Scaling the metric offset by mpp would bake in the stored value's rounding
error (up to ~5% on real sites, plan §1a) and grow it with distance from the
anchor.

Plan §7's no-rotation assumption turned out WRONG for some sites (Banks is
rotated ~−34°; see OVERLAY_ROTATION_INVESTIGATION.md). When the recording
carries the ``Z;`` GetCfg line — the configured zones in the EVO frame —
``model.zonefit`` recovers the full similarity (rotation+scale+translation)
from matched zone centroids and that transform supersedes the translation;
the anchor/reference translation above remains the fallback whenever the
``Z;`` fit is unavailable, which keeps every previously-correct behavior.

The anchor is per-sensor (plan §1c): each recording is one host's stream, so
it is tagged with its owning sensor index and aligns to that sensor — never a
hard-wired sensor 0. Everything here is pure and pandas-free (plan §§2-3);
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

import gzip
import re
import zlib
from dataclasses import dataclass
from pathlib import Path

from . import zonefit
from .iprj_io import Project
from .units import effective_meter_per_pixel, m_to_ft, px_to_ft
from .zonefit import ZoneFit

_GZIP_MAGIC = b"\x1f\x8b"

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
class Recording:
    sensor_index: int  # the project sensor this stream is anchored to
    ref_m: tuple[float, float]  # EVO C; reference; (0, 0) when none was seen
    ref_seen: bool
    anchor_ft: tuple[float, float]  # sensor[sensor_index] in world feet
    frames: list[Frame]  # frames[i] is frame i -> O(1) timeline scrub
    # Similarity recovered from the recording's Z; zones (rotation fix);
    # None = no usable Z; line, frames used the translation fallback.
    zone_fit: ZoneFit | None = None

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


def load_recording(
    project: Project,
    path: str | Path,
    *,
    sensor_index: int = 0,
    downsample_rate: int = 1,
    max_frames: int | None = DEFAULT_MAX_FRAMES,
    max_points_per_frame: int | None = DEFAULT_MAX_POINTS_PER_FRAME,
) -> Recording:
    """Read a recording file and align it to *project*'s *sensor_index*.

    Transparently reads gzip-compressed recordings (``capture/recorder.py``
    writes ``.txt.gz``) alongside plain ``.txt`` ones — detected by magic
    bytes, not extension, so a renamed file still loads."""
    text = _read_recording_text(path)
    return parse_recording(
        project, text,
        sensor_index=sensor_index,
        downsample_rate=downsample_rate,
        max_frames=max_frames,
        max_points_per_frame=max_points_per_frame,
    )


def _read_recording_text(path: str | Path) -> str:
    """Decode a recording file, gzip or plain, sniffed by magic bytes.

    The recorder flushes a zlib sync point after every message
    (``gzip.GzipFile.flush()``), so a capture killed mid-write (crash, power
    loss) leaves a gzip stream with no end-of-stream marker but every
    fully-written message still intact. A strict ``gzip.decompress`` raises
    ``EOFError`` on that stream and would discard the whole file, so this
    falls back to a raw ``zlib`` decompressor on that error, which recovers
    everything up to the truncation instead of nothing."""
    raw = Path(path).read_bytes()
    if raw[:2] != _GZIP_MAGIC:
        return raw.decode("utf-8", errors="ignore")
    try:
        data = gzip.decompress(raw)
    except EOFError:
        data = zlib.decompressobj(zlib.MAX_WBITS | 16).decompress(raw)
    return data.decode("utf-8", errors="ignore")


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
    ref, ref_seen, raw_frames, zline = _parse_lines(text)
    if not raw_frames:
        raise ValueError("no F; track frames found in recording")

    raw_frames = raw_frames[:: max(downsample_rate, 1)]
    if max_frames is not None:
        raw_frames = raw_frames[:max_frames]

    fit = zonefit.fit(project, zonefit.parse_zline(zline)) if zline else None
    anchor = anchor_world_ft(project, sensor_index)
    frames = [
        _align_frame(t, entities, anchor, ref, max_points_per_frame, fit)
        for t, entities in raw_frames
    ]

    return Recording(
        sensor_index=sensor_index,
        ref_m=ref,
        ref_seen=ref_seen,
        anchor_ft=anchor,
        frames=frames,
        zone_fit=fit,
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
    the whole file, so a ``C;``/``Z;`` arriving *after* some frames still
    anchors them retroactively; a stream cannot rewrite frames it already
    emitted, so frames fed before any reference use the same ``(0, 0)``
    fallback as the batch default and keep it, and frames fed before the
    ``Z;`` zones stay translation-aligned. The real feed sends the GetCfg
    reply (``C;`` + ``Z;``) up front, so the two paths agree frame-for-frame
    on any well-formed stream.

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
        self.sensor_index = sensor_index
        self.anchor_ft = anchor_world_ft(project, sensor_index)
        self.max_points_per_frame = max_points_per_frame
        self._project = project  # kept for the Z; zone fit
        self._ref = (0.0, 0.0)
        self._ref_seen = False
        self._zone_fit: ZoneFit | None = None
        self._t = "00:00:00.000"

    @property
    def ref_m(self) -> tuple[float, float]:
        return self._ref

    @property
    def ref_seen(self) -> bool:
        return self._ref_seen

    @property
    def zone_fit(self) -> ZoneFit | None:
        return self._zone_fit

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
                    ref = _parse_ref(line)
                    if ref is not None:
                        self._ref, self._ref_seen = ref, True
                continue

            if line.startswith("Z;"):
                if self._zone_fit is None:  # first usable Z; wins, like C;
                    self._zone_fit = zonefit.fit(
                        self._project, zonefit.parse_zline(line))
                continue

            if _TIME_RE.match(line):
                self._t = line
                continue

            if line.startswith("F;"):
                frame = _align_frame(
                    self._t, _parse_frame_entities(line),
                    self.anchor_ft, self._ref, self.max_points_per_frame,
                    self._zone_fit)

        return frame


# --- raw line parsing -------------------------------------------------------

# (oid, cls, x_m, y_m, heading) straight off an F; entity, pre-alignment
_RawEntity = tuple[int, "int | None", float, float, "float | None"]


def _parse_lines(text: str) -> tuple[
    tuple[float, float], bool, list[tuple[str, list[_RawEntity]]], str | None,
]:
    """Collect the C; reference, raw F; frames, and Z; line from recording text.

    Line grammar per evo_recorder's output (one timestamp line before each
    message) and evo_replay.parse_evo_data:

      * ``HH:MM:SS.mmm``            wall-clock stamp for the next message
      * ``F;a;b;c;mask;ent;ent;..`` entities as ``oid,class,x,y,heading,..``
      * ``C;x,y,...``               sensor reference; first one wins
      * ``Z;zone;zone;..``          configured zones in the EVO frame (part
                                    of the GetCfg reply); first one wins,
                                    returned raw for model.zonefit

    Anything else (other GetCfg responses, blank lines) is ignored. The whole
    file is scanned before aligning, so a late C;/Z; line still anchors
    correctly.

    The per-line grammar lives in _parse_ref/_parse_frame_entities, shared
    with the streaming LiveAligner — this function only holds the scan state.
    """
    ref_x, ref_y, ref_seen = 0.0, 0.0, False
    zline: str | None = None
    current_time = "00:00:00.000"
    raw_frames: list[tuple[str, list[_RawEntity]]] = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("C;") and not ref_seen:
            ref = _parse_ref(line)
            if ref is not None:
                (ref_x, ref_y), ref_seen = ref, True
            continue

        if line.startswith("Z;"):
            if zline is None:
                zline = line
            continue

        if _TIME_RE.match(line):
            current_time = line
            continue

        if line.startswith("F;"):
            raw_frames.append((current_time, _parse_frame_entities(line)))

    return (ref_x, ref_y), ref_seen, raw_frames, zline


def _parse_ref(line: str) -> tuple[float, float] | None:
    """A ``C;`` line's (x, y) reference in EVO meters; None if unparseable."""
    vals = line[2:].split(",")
    if len(vals) >= 2:
        try:
            return float(vals[0]), float(vals[1])
        except ValueError:
            pass
    return None


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
    anchor: tuple[float, float],
    ref: tuple[float, float],
    max_points_per_frame: int | None,
    zone_fit: ZoneFit | None = None,
) -> Frame:
    """Align one raw frame into world feet — the single copy of the transform.
    Both the batch parser and the streaming LiveAligner build every Frame
    through here. With a ``ZoneFit`` (the recording carried a usable ``Z;``
    line) each point goes through the fitted similarity; otherwise the plan-
    §1b translation applies, with its m_to_ft-on-offset / emp-on-anchor
    split."""
    if max_points_per_frame is not None:
        entities = entities[:max_points_per_frame]

    def to_world(x: float, y: float) -> tuple[float, float]:
        if zone_fit is not None:
            return zone_fit.apply_m(x, y)
        # y-down on both sides
        return anchor[0] + m_to_ft(x - ref[0]), anchor[1] + m_to_ft(y - ref[1])

    points = []
    for oid, cls, x, y, heading in entities:
        x_ft, y_ft = to_world(x, y)
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
