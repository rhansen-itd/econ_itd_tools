"""Visual check of the coordinate theory: decode a project's background image,
place it at (Background_PosX, Background_PosY) in world pixels (y-down), and
overlay the event zones, ignore zones, sensors, and calibration references.
If zones land on the roadway, the shared-pixel-space theory holds.

Usage:
    python scripts/overlay_zones.py [path/to/site.iprj] [--out out.png] [--show]

Defaults to sites/Banks/banks.iprj; output goes to tests/out/ (gitignored).
"""

import argparse
import io
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model import units
from model.iprj_io import load_iprj

REPO = Path(__file__).resolve().parents[3]

PHASE_COLORS = ["tab:red", "tab:blue", "tab:green", "tab:orange", "tab:purple",
                "tab:brown", "tab:pink", "tab:olive", "tab:cyan"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("iprj", nargs="?", default=REPO / "sites/Banks/banks.iprj", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()

    project = load_iprj(args.iprj)
    bg = project.background

    img = Image.open(io.BytesIO(units.decode_background_image(bg)))
    if bg.rotation:
        print(f"note: BackgroundImageRotation={bg.rotation} not applied "
              "(rotation semantics unverified)")
    scale = (bg.scale or 100.0) / 100.0
    x0, y0 = bg.pos_x or 0.0, bg.pos_y or 0.0
    w, h = img.width * scale, img.height * scale

    fpp = units.ft_per_px(bg)
    fig_h = 12.0
    fig, ax = plt.subplots(figsize=(max(6.0, fig_h * w / h), fig_h))
    # y-down world: extent bottom > top flips the axis to match
    ax.imshow(img, extent=(x0, x0 + w, y0 + h, y0), origin="upper")

    for si, sensor in enumerate(project.sensors):
        for zone in sensor.event_zones:
            if not zone.enable or len(zone.points) < 3:
                continue
            color = PHASE_COLORS[(zone.phase_number or 0) % len(PHASE_COLORS)]
            ax.add_patch(Polygon(zone.points, closed=True, facecolor=color,
                                 edgecolor=color, alpha=0.45, lw=1.5))
            cx = sum(p[0] for p in zone.points) / len(zone.points)
            cy = sum(p[1] for p in zone.points) / len(zone.points)
            ax.annotate(f"{zone.zone_name}\nout {zone.output_number}",
                        (cx, cy), ha="center", va="center", fontsize=5,
                        color="white",
                        bbox=dict(facecolor="black", alpha=0.4, pad=1))
        for zone in sensor.ignore_zones:
            if not zone.enable or len(zone.points) < 3:
                continue
            ax.add_patch(Polygon(zone.points, closed=True, facecolor="none",
                                 edgecolor="yellow", ls="--", lw=1.0))
        if sensor.position_x is not None:
            ax.plot(sensor.position_x, sensor.position_y, "w^", ms=10,
                    mec="black")
            ax.annotate(f"S{si + 1}", (sensor.position_x, sensor.position_y),
                        textcoords="offset points", xytext=(0, 8),
                        ha="center", color="white", fontsize=8, weight="bold")

    if bg.ref0_x is not None:
        ax.plot([bg.ref0_x, bg.ref1_x], [bg.ref0_y, bg.ref1_y], "r+-", ms=12,
                lw=0.8, label=f"reference ({units.m_to_ft(bg.reference_length):.0f} ft)")
        ax.legend(loc="upper right", fontsize=7)

    # 100 ft scale bar
    bar_px = units.ft_to_px(100.0, units.effective_meter_per_pixel(bg))
    bx, by = x0 + 0.05 * w, y0 + 0.97 * h
    ax.plot([bx, bx + bar_px], [by, by], "w-", lw=3)
    ax.annotate("100 ft", (bx + bar_px / 2, by), textcoords="offset points",
                xytext=(0, 6), ha="center", color="white", fontsize=8)

    ax.set_title(f"{args.iprj.name} — {fpp:.3f} ft/px "
                 f"({units.effective_meter_per_pixel(bg):.4f} m/px)")
    ax.set_xlabel("world px")
    ax.set_ylabel("world px (y-down)")

    out = args.out or (Path(__file__).resolve().parents[1] / "tests/out" /
                       f"{args.iprj.stem}_overlay.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"wrote {out}")
    if args.show:
        plt.show()


if __name__ == "__main__":
    main()
