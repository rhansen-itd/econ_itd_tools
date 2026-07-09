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
anchor. Alignment is a pure translation in a y-down frame, matching
evo_replay's behavior; plan §7 flags confirming the no-rotation and y-sign
assumptions against a live recording as still open (no real recording
survives on disk to pin them here).

The anchor is per-sensor (plan §1c): each recording is one host's stream, so
it is tagged with its owning sensor index and aligns to that sensor — never a
hard-wired sensor 0. Everything here is pure and pandas-free (plan §§2-3);
``Recording.to_dataframe()`` imports pandas lazily for notebook use only.
"""

from __future__ import annotations

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
class Recording:
    sensor_index: int  # the project sensor this stream is anchored to
    ref_m: tuple[float, float]  # EVO C; reference; (0, 0) when none was seen
    ref_seen: bool
    anchor_ft: tuple[float, float]  # sensor[sensor_index] in world feet
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
    ref, ref_seen, raw_frames = _parse_lines(text)
    if not raw_frames:
        raise ValueError("no F; track frames found in recording")

    raw_frames = raw_frames[:: max(downsample_rate, 1)]
    if max_frames is not None:
        raw_frames = raw_frames[:max_frames]

    anchor = anchor_world_ft(project, sensor_index)
    frames = []
    for t, entities in raw_frames:
        if max_points_per_frame is not None:
            entities = entities[:max_points_per_frame]
        points = tuple(
            TrackPoint(
                oid=oid,
                sensor=oid % 10,
                cls=cls,
                x_ft=anchor[0] + m_to_ft(x - ref[0]),
                y_ft=anchor[1] + m_to_ft(y - ref[1]),  # y-down on both sides
                heading=heading,
                x_raw_m=x,
                y_raw_m=y,
            )
            for oid, cls, x, y, heading in entities
        )
        frames.append(Frame(t=t, points=points))

    return Recording(
        sensor_index=sensor_index,
        ref_m=ref,
        ref_seen=ref_seen,
        anchor_ft=anchor,
        frames=frames,
    )


# --- raw line parsing -------------------------------------------------------

# (oid, cls, x_m, y_m, heading) straight off an F; entity, pre-alignment
_RawEntity = tuple[int, "int | None", float, float, "float | None"]


def _parse_lines(text: str) -> tuple[tuple[float, float], bool, list[tuple[str, list[_RawEntity]]]]:
    """Collect the C; reference and the raw F; frames from recording text.

    Line grammar per evo_recorder's output (one timestamp line before each
    message) and evo_replay.parse_evo_data:

      * ``HH:MM:SS.mmm``            wall-clock stamp for the next message
      * ``F;a;b;c;mask;ent;ent;..`` entities as ``oid,class,x,y,heading,..``
      * ``C;x,y,...``               sensor reference; first one wins

    Anything else (GetCfg responses, blank lines) is ignored. The whole file
    is scanned before aligning, so a late C; line still anchors correctly.
    """
    ref_x, ref_y, ref_seen = 0.0, 0.0, False
    current_time = "00:00:00.000"
    raw_frames: list[tuple[str, list[_RawEntity]]] = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("C;") and not ref_seen:
            vals = line[2:].split(",")
            if len(vals) >= 2:
                try:
                    ref_x, ref_y = float(vals[0]), float(vals[1])
                    ref_seen = True
                except ValueError:
                    pass
            continue

        if _TIME_RE.match(line):
            current_time = line
            continue

        if line.startswith("F;"):
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
            raw_frames.append((current_time, entities))

    return (ref_x, ref_y), ref_seen, raw_frames


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
