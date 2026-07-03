"""Session 4 end-to-end at the model level: new project from an image →
calibrate → draw (via the controller) → attributes/conditions/sensor →
save_iprj → reload → everything survives, including the embedded PNG."""

import base64
import io
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from gui.drawing import DrawingController, next_output_number
from model import units
from model.iprj_io import Background, Condition, Project, Sensor, load_iprj, save_iprj


def make_project(width_px=400, height_px=300):
    img = Image.new("RGB", (width_px, height_px), (40, 90, 40))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    bg = Background(image_base64=base64.b64encode(buf.getvalue()).decode("ascii"))
    return Project(background=bg, sensors=[Sensor()])


def test_new_project_calibrate_draw_attributes_save_reload(tmp_path):
    project = make_project()
    bg = project.background

    # calibrate: image is 400 px wide == 200 ft -> 0.5 ft/px
    units.calibrate_image_width(bg, 400, 200.0)
    assert units.ft_per_px(bg) == pytest.approx(0.5)

    # draw a dimensioned 10x20 ft rectangle with the controller
    zones = project.sensors[0].event_zones
    ctrl = DrawingController(
        zones, lambda: units.ft_per_px(bg),
        next_output=lambda: next_output_number([zones]))
    ctrl.mouse_down((100, 100))
    ctrl.mouse_move((200, 100))
    for k in "10":
        ctrl.key(k)
    ctrl.key("Enter")
    ctrl.mouse_move((150, 200))
    for k in "20":
        ctrl.key(k)
    ctrl.key("Enter")
    assert len(zones) == 1
    assert zones[0].points == pytest.approx(
        [(100, 100), (120, 100), (120, 140), (100, 140)])  # 10 ft == 20 px

    # attributes, a speed condition (stored km/h), sensor placement
    zone = zones[0]
    zone.zone_name = "Ph 4 SBT Stop Bar 1"
    zone.phase_number = 4
    zone.zone_type = 1
    zone.output_number = 38
    zone.conditions.append(Condition(
        enable=1, output_number=62, condition_class=0,
        velocity_min=units.mph_to_kmh(25.0), velocity_max=16091.79))
    sensor = project.sensors[0]
    sensor.position_x, sensor.position_y = 200.0, 10.0
    sensor.azimuth_angle = 180.0
    sensor.installation_height = units.ft_to_m(20.0)

    path = tmp_path / "generated.iprj"
    save_iprj(project, path)

    # vendor dialect on disk
    root = ET.parse(path).getroot()
    assert root.tag == "Config" and root.get("Version") == "1.1"
    assert root.find("ProductInformation").get("ProductCode") == "5220"

    loaded = load_iprj(path)
    lz = loaded.sensors[0].event_zones[0]
    assert lz.zone_name == "Ph 4 SBT Stop Bar 1"
    assert (lz.phase_number, lz.zone_type, lz.output_number) == (4, 1, 38)
    assert lz.points == pytest.approx(zone.points)
    lc = lz.conditions[0]
    assert lc.enable == 1 and lc.output_number == 62
    assert units.kmh_to_mph(lc.velocity_min) == pytest.approx(25.0, abs=0.01)
    ls = loaded.sensors[0]
    assert (ls.position_x, ls.position_y) == (200.0, 10.0)
    assert ls.azimuth_angle == 180.0
    assert units.m_to_ft(ls.installation_height) == pytest.approx(20.0, abs=0.01)

    # calibration survives with full precision (re-derived from the ref pair)
    assert units.ft_per_px(loaded.background) == pytest.approx(0.5)

    # embedded background PNG survives byte-for-byte
    img = Image.open(io.BytesIO(units.decode_background_image(loaded.background)))
    assert img.size == (400, 300)
    assert loaded.background.image_base64 == bg.image_base64

    # reopen → edit → save again stays stable
    loaded.sensors[0].event_zones[0].output_number = 39
    path2 = tmp_path / "generated2.iprj"
    save_iprj(loaded, path2)
    again = load_iprj(path2)
    assert again.sensors[0].event_zones[0].output_number == 39
    assert again.background.image_base64 == bg.image_base64
