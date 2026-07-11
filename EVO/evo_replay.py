"""EVO traffic replay — a reliable plotter for aligned EVO radar tracks.

This is the clean foundation distilled from the ``traffic_replay`` cell of
``EVO_plotter.ipynb``. It parses an EVO recording plus its site config
(``*_iprj.txt``), aligns the live tracks onto the site background image, and
renders a replay in one of two forms:

  * an interactive Plotly HTML page (default) with hover details, or
  * an MP4 video (``--video``), rendered with matplotlib + ffmpeg.

By default each point is labelled with an abbreviated object id (the last few
digits) drawn over the marker, so you can follow a track without hovering.

Later additions (spatial corrections, track splicing/fusing) should slot in as
transforms on the aligned DataFrame returned by :func:`load_replay`, keeping the
parse/align/render split intact.

CLI examples
------------
    python evo_replay.py                          # default site -> HTML
    python evo_replay.py --video                  # default site -> MP4
    python evo_replay.py --data path/to/EVO.txt --xml path/to/site_iprj.txt
    python evo_replay.py --downsample 3 --max-frames 500 --out replay.html
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import re
from dataclasses import dataclass

import pandas as pd
from PIL import Image

# --- DEFAULTS -------------------------------------------------------------
# The 86_US95&SH8 site, pointing at a short recording for fast iteration.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
DEFAULT_XML = os.path.join(_ROOT, "sites", "86_US95&SH8", "us95&sh8_iprj.txt")
DEFAULT_DATA = os.path.join(_ROOT, "sites", "86_US95&SH8", "10_37_2_86_EVO_1770311735.txt")

# Color per sensor (by oid % 10). Unknown sensors fall back to Plotly defaults.
SENSOR_COLORS = {
    "Sensor 0": "cyan",
    "Sensor 1": "yellow",
    "Sensor 2": "lime",
    "Sensor 3": "magenta",
    "Sensor 4": "orange",
    "Sensor 5": "deepskyblue",
}


@dataclass
class MapConfig:
    """Static site geometry parsed from the ``*_iprj.txt`` config."""

    scale: float = 0.2          # meters per pixel
    bg_off_x: float = 0.0       # background image pixel offset
    bg_off_y: float = 0.0
    s0_x: float = 0.0           # sensor-0 position in map meters
    s0_y: float = 0.0
    width: int = 0              # background image size, pixels
    height: int = 0

    @property
    def width_m(self) -> float:
        return self.width * self.scale

    @property
    def height_m(self) -> float:
        return self.height * self.scale


# --- PARSING --------------------------------------------------------------

def parse_xml_config(filepath: str) -> tuple[MapConfig, str | None]:
    """Extract scale, offsets, sensor-0 reference, and the base64 background.

    Returns ``(MapConfig, bg_image_data_uri_or_None)``.
    """
    cfg = MapConfig()
    bg_image = None

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    m_img = re.search(r'BackgroundImage="([^"]+)"', content)
    if m_img:
        bg_image = "data:image/png;base64," + m_img.group(1)
        try:
            pil = Image.open(io.BytesIO(base64.b64decode(m_img.group(1))))
            cfg.width, cfg.height = pil.width, pil.height
        except Exception:
            pass

    m_scale = re.search(r'MeterPerPixel="([^"]+)"', content)
    if m_scale:
        cfg.scale = float(m_scale.group(1))

    m_bgx = re.search(r'(?:BackgroundImage|Background_)PosX="([^"]+)"', content)
    if m_bgx:
        cfg.bg_off_x = float(m_bgx.group(1))
    m_bgy = re.search(r'(?:BackgroundImage|Background_)PosY="([^"]+)"', content)
    if m_bgy:
        cfg.bg_off_y = float(m_bgy.group(1))

    # Sensor 0 position (pixels) -> map meters, the anchor for alignment.
    m_s0x = re.search(r'Radarsensor_0_Position_X="([^"]+)"', content)
    m_s0y = re.search(r'Radarsensor_0_Position_Y="([^"]+)"', content)
    if m_s0x and m_s0y:
        cfg.s0_x = (float(m_s0x.group(1)) - cfg.bg_off_x) * cfg.scale
        cfg.s0_y = (float(m_s0y.group(1)) - cfg.bg_off_y) * cfg.scale

    return cfg, bg_image


def parse_evo_data(filepath: str) -> tuple[pd.DataFrame, dict]:
    """Parse a raw EVO recording into a tidy DataFrame of track points.

    The recording interleaves three kinds of lines:
      * ``HH:MM:SS.mmm``           -> current frame timestamp
      * ``F;..;..;..;mask;ent;..`` -> tracked entities ``oid,class,x,y,heading``
      * ``C;x,y,...``              -> sensor-0 reference (alignment anchor)

    Returns ``(DataFrame, evo_s0)`` where ``evo_s0`` is the sensor-0 position in
    the EVO frame, used to align onto the map.
    """
    rows = []
    evo_s0 = {"x": 0.0, "y": 0.0, "seen": False}
    current_time = "00:00:00.000"

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Alignment reference (first C line wins).
            if line.startswith("C;") and not evo_s0["seen"]:
                vals = line[2:].split(",")
                if len(vals) >= 2:
                    try:
                        evo_s0["x"] = float(vals[0])
                        evo_s0["y"] = float(vals[1])
                        evo_s0["seen"] = True
                    except ValueError:
                        pass
                continue

            # Timestamp line.
            if re.match(r"^\d\d:\d\d:\d\d", line):
                current_time = line
                continue

            # Track frame.
            if line.startswith("F;"):
                parts = line.split(";")
                # parts[0]='F', [1..4] are frame/header fields, [5:] are entities.
                for ent in parts[5:]:
                    p = ent.split(",")
                    if len(p) < 4:
                        continue
                    try:
                        oid = int(p[0])
                        x = float(p[2])
                        y = float(p[3])
                    except ValueError:
                        continue
                    heading = float(p[4]) if len(p) > 4 and _is_float(p[4]) else None
                    rows.append({
                        "Time": current_time,
                        "ID": oid,
                        "X_raw": x,
                        "Y_raw": y,
                        "Heading": heading,
                        "Sensor": f"Sensor {oid % 10}",
                    })

    return pd.DataFrame(rows), evo_s0


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


# --- ALIGN / SHAPE --------------------------------------------------------

def align(df: pd.DataFrame, cfg: MapConfig, evo_s0: dict, label_digits: int = 4) -> pd.DataFrame:
    """Translate EVO coordinates onto the map and add a short text label.

    Alignment is a pure translation: map sensor-0 minus EVO sensor-0.
    """
    trans_x = cfg.s0_x - evo_s0["x"]
    trans_y = cfg.s0_y - evo_s0["y"]

    df = df.copy()
    df["X"] = df["X_raw"] + trans_x
    df["Y"] = df["Y_raw"] + trans_y
    if label_digits and label_digits > 0:
        df["Label"] = df["ID"].astype(str).str[-label_digits:]
    else:
        df["Label"] = ""
    return df


def downsample(df: pd.DataFrame, rate: int = 1, max_frames: int | None = None) -> pd.DataFrame:
    """Keep every ``rate``-th unique timestamp, capped at ``max_frames``."""
    if rate <= 1 and not max_frames:
        return df
    times = df["Time"].unique()
    selected = times[:: max(rate, 1)]
    if max_frames:
        selected = selected[:max_frames]
    return df[df["Time"].isin(selected)].copy()


def load_replay(
    xml_file: str = DEFAULT_XML,
    data_file: str = DEFAULT_DATA,
    *,
    downsample_rate: int = 1,
    max_frames: int | None = None,
    label_digits: int = 4,
    verbose: bool = True,
) -> tuple[pd.DataFrame, MapConfig, str | None]:
    """End-to-end load: parse + align + downsample.

    Returns the aligned, frame-ordered DataFrame plus the map config and
    background image. This is the seam for future transforms (spatial
    correction, fusion): operate on the returned DataFrame, then render.
    """
    if verbose:
        print(f"1. Parsing site config: {os.path.basename(xml_file)}")
    cfg, bg_image = parse_xml_config(xml_file)

    if verbose:
        print(f"2. Parsing recording:   {os.path.basename(data_file)}")
    df, evo_s0 = parse_evo_data(data_file)
    if df.empty:
        raise ValueError(f"No track data parsed from {data_file}")

    df = align(df, cfg, evo_s0, label_digits=label_digits)
    df = downsample(df, downsample_rate, max_frames)
    df.sort_values("Time", kind="stable", inplace=True)

    if verbose:
        n_frames = df["Time"].nunique()
        trans = (cfg.s0_x - evo_s0["x"], cfg.s0_y - evo_s0["y"])
        print(f"   Aligned {len(df)} points across {n_frames} frames; "
              f"translation=({trans[0]:.2f}, {trans[1]:.2f})"
              + ("" if evo_s0["seen"] else "  [no C ref -> identity]"))
    return df, cfg, bg_image


# --- RENDER: HTML (Plotly) ------------------------------------------------

def render_html(
    df: pd.DataFrame,
    cfg: MapConfig,
    bg_image: str | None,
    out_path: str,
    *,
    title: str = "EVO Traffic Replay (Aligned)",
    frame_ms: int = 100,
    marker_size: int = 9,
    show_labels: bool = True,
) -> str:
    """Render an interactive Plotly replay to ``out_path`` (HTML)."""
    import plotly.express as px

    fig = px.scatter(
        df,
        x="X",
        y="Y",
        animation_frame="Time",
        animation_group="ID",
        color="Sensor",
        text="Label" if show_labels else None,
        hover_data=["ID", "Sensor", "X_raw", "Y_raw", "Heading"],
        color_discrete_map=SENSOR_COLORS,
        title=title,
    )

    fig.update_traces(
        marker=dict(size=marker_size, opacity=0.9, line=dict(width=1, color="black")),
        textposition="top center",
        textfont=dict(size=9, color="white"),
    )

    layout_kwargs = dict(
        xaxis=dict(range=[0, cfg.width_m], showgrid=False, zeroline=False),
        # Inverted Y: image coordinates grow downward.
        yaxis=dict(range=[cfg.height_m, 0], showgrid=False, zeroline=False,
                   scaleanchor="x", scaleratio=1),
        width=1000,
        height=820,
        template="plotly_dark",
    )
    if bg_image:
        layout_kwargs["images"] = [dict(
            source=bg_image, xref="x", yref="y",
            x=0, y=0, sizex=cfg.width_m, sizey=cfg.height_m,
            sizing="stretch", opacity=0.8, layer="below",
        )]
    fig.update_layout(**layout_kwargs)

    # Speed up the built-in play button.
    if fig.layout.updatemenus:
        fig.layout.updatemenus[0].buttons[0].args[1]["frame"]["duration"] = frame_ms
        fig.layout.updatemenus[0].buttons[0].args[1]["transition"]["duration"] = 0

    fig.write_html(out_path)
    return out_path


# --- RENDER: MP4 (matplotlib + ffmpeg) ------------------------------------

def render_mp4(
    df: pd.DataFrame,
    cfg: MapConfig,
    bg_image: str | None,
    out_path: str,
    *,
    fps: int = 10,
    marker_size: int = 60,
    show_labels: bool = True,
    title: str = "EVO Traffic Replay",
) -> str:
    """Render the replay to an MP4 via matplotlib's ffmpeg writer.

    matplotlib is used (rather than exporting Plotly frames) because it needs no
    extra dependencies here and drives the system ffmpeg directly.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FFMpegWriter
    import numpy as np

    frames = list(df.groupby("Time", sort=True))
    if not frames:
        raise ValueError("No frames to render.")

    def color_for(sensor: str) -> str:
        return SENSOR_COLORS.get(sensor, "white")

    fig, ax = plt.subplots(figsize=(10, 8.2), dpi=120)
    fig.patch.set_facecolor("black")
    ax.set_facecolor("black")

    if bg_image:
        raw = base64.b64decode(bg_image.split(",", 1)[1])
        bg = np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"))
        # extent = (left, right, bottom, top); top=0 keeps Y growing downward.
        ax.imshow(bg, extent=[0, cfg.width_m, cfg.height_m, 0], alpha=0.8, zorder=0)

    ax.set_xlim(0, cfg.width_m)
    ax.set_ylim(cfg.height_m, 0)  # inverted Y to match image coordinates
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])

    scat = ax.scatter([], [], s=marker_size, zorder=2,
                      edgecolors="black", linewidths=0.6)
    title_txt = ax.set_title("", color="white", fontsize=11)
    text_artists: list = []

    writer = FFMpegWriter(fps=fps, metadata={"title": title}, bitrate=4000)
    print(f"   Rendering {len(frames)} frames -> {out_path} @ {fps}fps")

    with writer.saving(fig, out_path, dpi=120):
        for i, (tstamp, g) in enumerate(frames):
            scat.set_offsets(g[["X", "Y"]].to_numpy())
            scat.set_color([color_for(s) for s in g["Sensor"]])
            title_txt.set_text(f"{title}   {tstamp}")

            # Reuse Text artists across frames; grow the pool as needed.
            if show_labels:
                rows = list(g.itertuples(index=False))
                for j, r in enumerate(rows):
                    if j < len(text_artists):
                        t = text_artists[j]
                        t.set_position((r.X, r.Y))
                        t.set_text(r.Label)
                        t.set_visible(True)
                    else:
                        text_artists.append(ax.text(
                            r.X, r.Y, r.Label, color="white", fontsize=7,
                            ha="center", va="bottom", zorder=3,
                        ))
                for t in text_artists[len(rows):]:
                    t.set_visible(False)

            writer.grab_frame()
            if (i + 1) % 100 == 0:
                print(f"      {i + 1}/{len(frames)} frames")

    plt.close(fig)
    return out_path


# --- ORCHESTRATION / CLI --------------------------------------------------

def replay(
    xml_file: str = DEFAULT_XML,
    data_file: str = DEFAULT_DATA,
    *,
    out_path: str | None = None,
    video: bool = False,
    downsample_rate: int = 1,
    max_frames: int | None = None,
    label_digits: int = 4,
    fps: int = 10,
    frame_ms: int = 100,
    verbose: bool = True,
) -> str:
    """Load a recording and render it to HTML (default) or MP4 (``video=True``)."""
    df, cfg, bg_image = load_replay(
        xml_file, data_file,
        downsample_rate=downsample_rate, max_frames=max_frames,
        label_digits=label_digits, verbose=verbose,
    )

    if out_path is None:
        out_path = "traffic_replay.mp4" if video else "traffic_replay.html"

    show_labels = bool(label_digits and label_digits > 0)
    if verbose:
        print(f"3. Rendering {'MP4' if video else 'HTML'} -> {out_path}")
    if video:
        render_mp4(df, cfg, bg_image, out_path, fps=fps, show_labels=show_labels)
    else:
        render_html(df, cfg, bg_image, out_path, frame_ms=frame_ms, show_labels=show_labels)

    if verbose:
        print(f"Done. Open: {out_path}")
    return out_path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="EVO traffic replay plotter (HTML or MP4).")
    p.add_argument("--xml", default=DEFAULT_XML, help="Site config *_iprj.txt")
    p.add_argument("--data", default=DEFAULT_DATA, help="Raw EVO recording .txt")
    p.add_argument("--out", default=None, help="Output path (default traffic_replay.html/.mp4)")
    p.add_argument("--video", action="store_true", help="Render an MP4 instead of HTML")
    p.add_argument("--downsample", type=int, default=1, metavar="N",
                   help="Keep every Nth frame (default 1)")
    p.add_argument("--max-frames", type=int, default=None, metavar="M",
                   help="Cap total frames")
    p.add_argument("--label-digits", type=int, default=4, metavar="D",
                   help="Trailing id digits to label points with (0 disables)")
    p.add_argument("--fps", type=int, default=10, help="MP4 frames per second")
    p.add_argument("--frame-ms", type=int, default=100, help="HTML play frame duration (ms)")
    return p


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    replay(
        xml_file=args.xml,
        data_file=args.data,
        out_path=args.out,
        video=args.video,
        downsample_rate=args.downsample,
        max_frames=args.max_frames,
        label_digits=args.label_digits,
        fps=args.fps,
        frame_ms=args.frame_ms,
    )


if __name__ == "__main__":
    main()
