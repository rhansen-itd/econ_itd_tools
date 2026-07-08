import pytest

from gui.viewport import MAX_SCALE, MIN_SCALE, Viewport
from model.iprj_io import Background
from model import units


def test_zoom_at_keeps_anchor_fixed():
    vp = Viewport(scale=1.0, tx=10.0, ty=-20.0)
    anchor = (300.0, 400.0)
    before = vp.image_to_viewport(anchor)
    vp.zoom_at(anchor, 1.5)
    after = vp.image_to_viewport(anchor)
    assert after == pytest.approx(before)
    assert vp.scale == pytest.approx(1.5)
    # other points move away from the anchor
    other = vp.image_to_viewport((310.0, 400.0))
    assert other[0] - after[0] == pytest.approx(15.0)


def test_zoom_clamped():
    vp = Viewport()
    vp.zoom_at((0.0, 0.0), 1e9)
    assert vp.scale == MAX_SCALE
    vp.zoom_at((0.0, 0.0), 1e-12)
    assert vp.scale == MIN_SCALE


def test_zoom_clamped_does_not_translate():
    vp = Viewport(scale=MAX_SCALE, tx=5.0, ty=6.0)
    vp.zoom_at((100.0, 100.0), 2.0)  # already at max: no-op
    assert (vp.scale, vp.tx, vp.ty) == (MAX_SCALE, 5.0, 6.0)


def test_drag_moves_anchor_with_cursor():
    vp = Viewport(scale=2.0)
    # cursor went down at image (100, 100); now reads image (110, 95)
    vp.drag_to((100.0, 100.0), (110.0, 95.0))
    # the drag-start point should now sit where the cursor is:
    # viewport pos of (100,100) moved by scale*(10,-5)
    assert (vp.tx, vp.ty) == pytest.approx((20.0, -10.0))


def test_fit_centers_and_contains():
    vp = Viewport()
    vp.fit((2000.0, 4800.0), (1000.0, 800.0), margin=1.0)
    assert vp.scale == pytest.approx(800.0 / 4800.0)
    # centered horizontally, flush vertically
    assert vp.tx == pytest.approx((1000.0 - vp.scale * 2000.0) / 2.0)
    assert vp.ty == pytest.approx(0.0)


def test_fit_frames_offset_content():
    # Item 25: with the oversized canvas the background sits at an offset inside
    # the transformed surface; fit must center the *background*, so the offset
    # shifts the translation by scale*origin relative to the origin-at-0 case.
    vp_base = Viewport()
    vp_base.fit((2000.0, 4800.0), (1000.0, 800.0), margin=1.0)
    vp_off = Viewport()
    vp_off.fit((2000.0, 4800.0), (1000.0, 800.0),
               content_origin=(1000.0, 2400.0), margin=1.0)
    assert vp_off.scale == pytest.approx(vp_base.scale)
    assert vp_off.tx == pytest.approx(vp_base.tx - vp_off.scale * 1000.0)
    assert vp_off.ty == pytest.approx(vp_base.ty - vp_off.scale * 2400.0)
    # the background's top-left (surface point == content_origin) lands exactly
    # where the origin-at-0 case put the image's top-left.
    assert vp_off.image_to_viewport((1000.0, 2400.0)) == \
        pytest.approx(vp_base.image_to_viewport((0.0, 0.0)))


def test_css_roundtrips_transform():
    vp = Viewport(scale=1.25, tx=-3.5, ty=7.0)
    assert vp.css() == ("transform-origin: 0 0; "
                        "transform: translate(-3.5px, 7.0px) scale(1.25);")


def test_image_world_transform_identity_placement():
    bg = Background()  # pos (0,0), scale 100
    assert units.image_to_world(bg, (10.0, 20.0)) == (10.0, 20.0)
    assert units.world_to_image(bg, (10.0, 20.0)) == (10.0, 20.0)


def test_image_world_transform_offset_and_scale():
    bg = Background(pos_x=-244.0, pos_y=-2100.0, scale=94.0)
    w = units.image_to_world(bg, (100.0, 200.0))
    assert w == pytest.approx((-244.0 + 94.0, -2100.0 + 188.0))
    assert units.world_to_image(bg, w) == pytest.approx((100.0, 200.0))


def test_calibrate_image_height():
    bg = Background()
    units.calibrate_image_height(bg, image_height_px=4800.0, height_ft=1200.0)
    assert units.ft_per_px(bg) == pytest.approx(0.25)
    assert (bg.ref1_x, bg.ref1_y) == (0.0, 4800.0)
