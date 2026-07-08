"""Oversized-canvas coordinate boundary (ROADMAP Item 25).

The drawing surface is 2x the background each way with the background centered
inside it, so objects can be placed off-image. The invariant under test: world
coordinates are *untouched* — the canvas offset is applied only at the render /
mouse boundary (world_to_canvas / canvas_to_world), so a saved project's coords
never shift and an off-image click still resolves to a valid world point.
"""

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from gui.app import Viewer
from model import units
from model.iprj_io import Background, Project, Sensor


def make_viewer(width_px=400, height_px=300, tmp_path=None):
    buf = io.BytesIO()
    Image.new("RGB", (width_px, height_px), "gray").save(buf, format="PNG")
    bg = Background(image_base64=base64.b64encode(buf.getvalue()).decode("ascii"),
                    pos_x=0.0, pos_y=0.0, scale=100.0)
    project = Project(background=bg, sensors=[Sensor()])
    src = (tmp_path or Path("/tmp")) / "canvas_test.iprj"
    return Viewer(project, src)


def test_canvas_is_twice_the_image_centered(tmp_path):
    v = make_viewer(400, 300, tmp_path)
    assert (v.canvas_w, v.canvas_h) == (800, 600)  # >= 2x each way
    # centered: equal margin on all sides
    assert v.canvas_off_x == pytest.approx(200.0)
    assert v.canvas_off_y == pytest.approx(150.0)


def test_world_canvas_roundtrip_identity(tmp_path):
    v = make_viewer(400, 300, tmp_path)
    for w in [(0.0, 0.0), (123.5, 87.25), (-40.0, 500.0)]:
        assert v.canvas_to_world(v.world_to_canvas(w)) == pytest.approx(w)


def test_on_image_geometry_only_shifts_by_offset(tmp_path):
    # An on-image world point projects to canvas = world_to_image + offset;
    # nothing about the world<->image anchor moved.
    v = make_viewer(400, 300, tmp_path)
    w = (250.0, 175.0)
    ix, iy = units.world_to_image(v.bg, w)
    cx, cy = v.world_to_canvas(w)
    assert (cx, cy) == pytest.approx((ix + v.canvas_off_x, iy + v.canvas_off_y))


def test_off_image_click_maps_to_valid_world_point(tmp_path):
    # The canvas top-left (0, 0) is well outside the background; it must still
    # resolve to a real (negative / beyond-extent) world point, not clamp.
    v = make_viewer(400, 300, tmp_path)
    w = v.canvas_to_world((0.0, 0.0))
    assert w == pytest.approx(units.image_to_world(
        v.bg, (-v.canvas_off_x, -v.canvas_off_y)))
    assert w[0] < 0 and w[1] < 0  # genuinely off the top-left of the image


def test_background_swap_recomputes_canvas(tmp_path):
    v = make_viewer(400, 300, tmp_path)
    v.image_w, v.image_h = 1000, 800
    v._recompute_canvas()
    assert (v.canvas_w, v.canvas_h) == (2000, 1600)
    assert (v.canvas_off_x, v.canvas_off_y) == pytest.approx((500.0, 400.0))
