"""Round-trip every real .iprj under sites/ through load_iprj/save_iprj.

Fidelity contract (revised for ROADMAP Item 11): load_iprj normalizes the
origin so the background image's top-left is world (0,0), so the saved file
is deliberately NOT byte-identical to the vendor's. It must instead contain
exactly the same attribute keys where every coordinate value is shifted by
(-Background_PosX, -Background_PosY) of the source file (Background_PosX/Y
themselves become 0) and every non-coordinate value is equal — string-equal,
or numerically equal where the model normalized formatting (e.g. "100" ->
"100.00"). Element order and container form are allowed to differ (we always
write the vendor form).
"""

import dataclasses
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from model.iprj_io import (
    Background,
    EventZone,
    Project,
    Sensor,
    load_iprj,
    save_iprj,
)

SITES = Path(__file__).resolve().parents[3] / "sites"
IPRJ_FILES = sorted(SITES.rglob("*.iprj"))


def read_attrs(path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    attrs = {}
    for elem in root.iter("Configuration"):
        attrs.update(elem.attrib)
    return attrs


def values_equal(a: str, b: str) -> bool:
    if a == b:
        return True
    try:
        return float(a) == float(b)
    except ValueError:
        return False


# Every attribute key that carries a world coordinate, per axis (see
# IPRJ_FORMAT.md §"Coordinate system"). Everything else must round-trip
# value-equal; these must round-trip shifted by the source file's
# (-Background_PosX, -Background_PosY).
_COORD_KEY = {
    "x": re.compile(
        r"^(Background_PosX"
        r"|MeterReference[01]_X"
        r"|Radarsensor_\d+_Position_X"
        r"|Radarsensor_\d+_(EventZone|IgnoreZone)_\d+_ZonePoint_\d+_X"
        r"|Radarsensor_\d+_EventZone_\d+_EtaPoint_X"
        r"|Lineals_\d+_Point_\d+_X"
        r"|Textlabel_\d+_Position_X)$"),
    "y": re.compile(
        r"^(Background_PosY"
        r"|MeterReference[01]_Y"
        r"|Radarsensor_\d+_Position_Y"
        r"|Radarsensor_\d+_(EventZone|IgnoreZone)_\d+_ZonePoint_\d+_Y"
        r"|Radarsensor_\d+_EventZone_\d+_EtaPoint_Y"
        r"|Lineals_\d+_Point_\d+_Y"
        r"|Textlabel_\d+_Position_Y)$"),
}


def coord_shift(key: str, dx: float, dy: float) -> float | None:
    """The expected translation for this key, or None if it's not a coordinate."""
    if _COORD_KEY["x"].match(key):
        return dx
    if _COORD_KEY["y"].match(key):
        return dy
    return None


def test_fixture_files_exist():
    assert len(IPRJ_FILES) >= 20, f"expected the sites/ fixtures, found {len(IPRJ_FILES)}"


@pytest.mark.parametrize("path", IPRJ_FILES, ids=lambda p: str(p.relative_to(SITES)))
def test_attribute_roundtrip(path, tmp_path):
    project = load_iprj(path)
    out = tmp_path / "roundtrip.iprj"
    save_iprj(project, out)

    orig = read_attrs(path)
    new = read_attrs(out)

    missing = sorted(set(orig) - set(new))
    added = sorted(set(new) - set(orig))
    assert not missing, f"keys lost on save: {missing[:10]}"
    assert not added, f"keys invented on save: {added[:10]}"

    # The whole file is translated by the source's (-PosX, -PosY) …
    dx = float(orig.get("Background_PosX", 0.0))
    dy = float(orig.get("Background_PosY", 0.0))
    bad = []
    for k in orig:
        if k == "BackgroundImage":
            continue
        shift = coord_shift(k, dx, dy)
        if shift is None:
            ok = values_equal(orig[k], new[k])
        else:
            ok = math.isclose(float(new[k]), float(orig[k]) - shift, abs_tol=1e-9)
        if not ok:
            bad.append((k, orig[k], new[k]))
    assert not bad, f"values changed: {bad[:10]}"
    assert orig.get("BackgroundImage") == new.get("BackgroundImage")

    # … which lands the background's top-left exactly on the origin.
    if "Background_PosX" in new:
        assert float(new["Background_PosX"]) == 0.0
    if "Background_PosY" in new:
        assert float(new["Background_PosY"]) == 0.0


@pytest.mark.parametrize("path", IPRJ_FILES, ids=lambda p: str(p.relative_to(SITES)))
def test_model_stable_after_roundtrip(path, tmp_path):
    project = load_iprj(path)
    out = tmp_path / "roundtrip.iprj"
    save_iprj(project, out)
    again = load_iprj(out)
    # Converter-form files carry no date/version/product metadata; save fills
    # defaults, so compare with the metadata aligned.
    again = dataclasses.replace(
        again, date=project.date,
        version=project.version, product_code=project.product_code,
    )
    assert project == again


def test_save_from_scratch(tmp_path):
    zone = EventZone(
        zone_name="Ph 4 SBT Stop Bar 1", phase_number=4, output_number=38,
        points=[(100.0, 200.0), (148.0, 200.0), (148.0, 320.0), (100.0, 320.0)],
    )
    project = Project(
        background=Background(pos_x=0.0, pos_y=0.0, meter_per_pixel=0.0762),
        sensors=[Sensor(position_x=50.0, position_y=60.0, event_zones=[zone])],
    )
    out = tmp_path / "new.iprj"
    save_iprj(project, out)

    root = ET.parse(out).getroot()
    assert root.tag == "Config"
    assert root.get("Version") == "1.1"
    assert root.find("ProductInformation").get("ProductCode") == "5220"

    again = load_iprj(out)
    z = again.sensors[0].event_zones[0]
    assert z.zone_name == "Ph 4 SBT Stop Bar 1"
    assert z.points == zone.points
    attrs = read_attrs(out)
    assert attrs["Radarsensor_0_EventZone_0_NrOfZonePoints"] == "4"
    assert attrs["Radarsensor_nrOfSensors"] == "1"
    # full-precision scale must survive the vendor's 2-decimal float style
    assert attrs["MeterPerPixel"] == "0.0762"


def test_zone_name_with_xml_specials(tmp_path):
    project = Project(sensors=[Sensor(event_zones=[
        EventZone(zone_name='EZ "1" <us95&sh8>', points=[(0.0, 0.0)] * 4),
    ])])
    out = tmp_path / "escaped.iprj"
    save_iprj(project, out)
    again = load_iprj(out)
    assert again.sensors[0].event_zones[0].zone_name == 'EZ "1" <us95&sh8>'
