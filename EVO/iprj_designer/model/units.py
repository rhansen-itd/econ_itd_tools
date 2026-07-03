"""Unit conversion and background calibration.

Canonical internal unit for the designer is feet; the iprj file stores world
pixels (y-down) plus a meters-per-pixel scale. Everything crossing that
boundary goes through here.

Calibration precision: vendor files round MeterPerPixel to two decimals but
keep the calibration inputs (MeterReference0/1 + ReferenceLength) at full
precision, so effective_meter_per_pixel() re-derives the scale from the
reference pair whenever it agrees with the stored value to within rounding.
"""

from __future__ import annotations

import base64
import math
import struct

from .iprj_io import Background, Point

M_PER_FT = 0.3048  # exact (international foot)
FT_PER_M = 1.0 / M_PER_FT
KMH_PER_MPH = 1.609344  # exact (international mile)


def ft_to_m(ft: float) -> float:
    return ft * M_PER_FT


def m_to_ft(m: float) -> float:
    return m * FT_PER_M


# Condition velocities are stored in km/h (Session 4 finding: the one enabled
# speed condition in the wild stores 40.23 = exactly 25 mph; see IPRJ_FORMAT).

def mph_to_kmh(mph: float) -> float:
    return mph * KMH_PER_MPH


def kmh_to_mph(kmh: float) -> float:
    return kmh / KMH_PER_MPH


def px_to_m(px: float, meter_per_pixel: float) -> float:
    return px * meter_per_pixel


def m_to_px(m: float, meter_per_pixel: float) -> float:
    return m / meter_per_pixel


def px_to_ft(px: float, meter_per_pixel: float) -> float:
    return m_to_ft(px * meter_per_pixel)


def ft_to_px(ft: float, meter_per_pixel: float) -> float:
    return ft_to_m(ft) / meter_per_pixel


def effective_meter_per_pixel(bg: Background) -> float:
    """Best-precision scale for a loaded background.

    Prefers the value implied by the reference pair + ReferenceLength (full
    precision) when it matches the stored MeterPerPixel to within the
    vendor's two-decimal rounding; otherwise trusts the stored value (real
    files exist where ReferenceLength was edited without re-applying the
    calibration, leaving the pair stale — ex27bg2.iprj).
    """
    stored = bg.meter_per_pixel
    implied = None
    if None not in (bg.reference_length, bg.ref0_x, bg.ref0_y, bg.ref1_x, bg.ref1_y):
        d = math.dist((bg.ref0_x, bg.ref0_y), (bg.ref1_x, bg.ref1_y))
        if d > 0:
            implied = bg.reference_length / d
    if stored is None:
        if implied is None:
            raise ValueError("background has no usable calibration")
        return implied
    if implied is not None and abs(implied - stored) <= 0.005:
        return implied
    return stored


def ft_per_px(bg: Background) -> float:
    return m_to_ft(effective_meter_per_pixel(bg))


def calibrate_two_points(bg: Background, p0: Point, p1: Point, distance_ft: float) -> None:
    """Two clicked points a known real distance apart (vendor-native form)."""
    d = math.dist(p0, p1)
    if d <= 0:
        raise ValueError("reference points must be distinct")
    if distance_ft <= 0:
        raise ValueError("reference distance must be positive")
    bg.ref0_x, bg.ref0_y = float(p0[0]), float(p0[1])
    bg.ref1_x, bg.ref1_y = float(p1[0]), float(p1[1])
    bg.reference_length = ft_to_m(distance_ft)
    bg.meter_per_pixel = bg.reference_length / d


def calibrate_image_width(bg: Background, image_width_px: float, width_ft: float) -> None:
    """Known real-world width of the background image.

    Expressed as a two-point calibration across the image's top edge so the
    file carries the same fields either way. image_width_px is in world px
    (image pixels x the BackgroundImageScale factor).
    """
    if bg.pos_x is None or bg.pos_y is None:
        bg.pos_x, bg.pos_y = 0.0, 0.0
    calibrate_two_points(
        bg,
        (bg.pos_x, bg.pos_y),
        (bg.pos_x + image_width_px, bg.pos_y),
        width_ft,
    )


def calibrate_image_height(bg: Background, image_height_px: float, height_ft: float) -> None:
    """Known real-world height of the background image (left edge, y-down)."""
    if bg.pos_x is None or bg.pos_y is None:
        bg.pos_x, bg.pos_y = 0.0, 0.0
    calibrate_two_points(
        bg,
        (bg.pos_x, bg.pos_y),
        (bg.pos_x, bg.pos_y + image_height_px),
        height_ft,
    )


# ---------------------------------------------------------------------------
# Image <-> world transform (confirmed in Session 1: the image's top-left sits
# at (pos_x, pos_y) and one image pixel spans scale/100 world pixels)
# ---------------------------------------------------------------------------

def image_scale_factor(bg: Background) -> float:
    """World px per image px (BackgroundImageScale is a percentage)."""
    return (bg.scale if bg.scale is not None else 100.0) / 100.0


def image_to_world(bg: Background, p: Point) -> Point:
    f = image_scale_factor(bg)
    return ((bg.pos_x or 0.0) + p[0] * f, (bg.pos_y or 0.0) + p[1] * f)


def world_to_image(bg: Background, p: Point) -> Point:
    f = image_scale_factor(bg)
    return ((p[0] - (bg.pos_x or 0.0)) / f, (p[1] - (bg.pos_y or 0.0)) / f)


def decode_background_image(bg: Background) -> bytes:
    if not bg.image_base64:
        raise ValueError("background has no embedded image")
    return base64.b64decode(bg.image_base64)


def background_image_size(bg: Background) -> tuple[int, int]:
    """(width, height) in image pixels. All observed files embed PNG."""
    raw = decode_background_image(bg)
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("embedded background image is not a PNG")
    return struct.unpack(">II", raw[16:24])
