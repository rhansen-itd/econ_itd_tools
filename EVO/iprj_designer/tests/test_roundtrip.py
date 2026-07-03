"""Round-trip every real .iprj under sites/ through load_iprj/save_iprj.

Fidelity contract: the saved file must contain exactly the same attribute
keys with equal values — string-equal, or numerically equal where the model
normalized formatting (e.g. "100" -> "100.00"). Element order and container
form are allowed to differ (we always write the vendor form).
"""

import dataclasses
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

    bad = [(k, orig[k], new[k]) for k in orig
           if not values_equal(orig[k], new[k]) and k != "BackgroundImage"]
    assert not bad, f"values changed: {bad[:10]}"
    assert orig.get("BackgroundImage") == new.get("BackgroundImage")


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
