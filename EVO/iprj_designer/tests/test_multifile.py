"""Two-file sensor-pair split/merge (ROADMAP Item 9, ITEM9_SPLIT_PLAN.md §5).

The acceptance test: build a 3-/4-sensor Project, split_project, save both
files, load both back, merge_pair, and get the original deep-equal — with
OutputNumbers byte-identical (they are project-wide rack channels; only the
sensor *index* restarts at 0 in the _3_4 file).
"""

import base64
import struct
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

import pytest

from model.iprj_io import (
    Background,
    Condition,
    EventZone,
    Lineal,
    Project,
    Sensor,
    TextLabel,
    load_iprj,
    save_iprj,
)
from model.multifile import (
    BackgroundMismatch,
    check_background_match,
    is_multifile,
    is_valid_pair,
    merge_pair,
    pair_paths,
    pair_role,
    real_sensor_count,
    split_project,
)

SITES = Path(__file__).resolve().parents[3] / "sites"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def make_png(width: int = 64, height: int = 48, shade: int = 0) -> str:
    """Minimal grayscale PNG as base64 (what Background embeds)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes([shade]) * width for _ in range(height))
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return base64.b64encode(png).decode("ascii")


def make_bg(shade: int = 0, width: int = 64, height: int = 48) -> Background:
    return Background(image_base64=make_png(width, height, shade),
                      pos_x=0.0, pos_y=0.0, rotation=0.0, scale=100.0,
                      meter_per_pixel=0.1)


# Project-wide rack channels: sensors 3-4 keep theirs verbatim in the _3_4 file.
OUTPUTS = [1, 2, 33, 34]


def make_project(n_sensors: int, bg: Background | None = None) -> Project:
    sensors = []
    for i in range(n_sensors):
        x = 10.0 * i
        zone = EventZone(
            zone_name=f"Zone {i + 1}", zone_type=1, output_number=OUTPUTS[i],
            points=[(x, 0.0), (x + 8.0, 0.0), (x + 8.0, 12.0), (x, 12.0)],
            conditions=[Condition(enable=1, output_number=OUTPUTS[i])],
        )
        sensors.append(Sensor(position_x=x, position_y=-3.0, event_zones=[zone]))
    return Project(
        background=bg if bg is not None else make_bg(),
        sensors=sensors,
        lineals=[Lineal(enable=1, point_0=(0.0, 0.0), point_1=(9.0, 9.0))],
        text_labels=[TextLabel(enable=1, text="note", position_x=1.0, position_y=2.0)],
        date="2026_07_04_00:00:00",
        extra={"Zoomfaktor": "1.00"},
    )


def read_attrs(path) -> dict[str, str]:
    attrs = {}
    for elem in ET.parse(path).getroot().iter("Configuration"):
        attrs.update(elem.attrib)
    return attrs


# ---------------------------------------------------------------------------
# Naming convention
# ---------------------------------------------------------------------------

def test_pair_paths_from_base():
    p12, p34 = pair_paths(Path("/site/foo.iprj"))
    assert p12 == Path("/site/foo_1_2.iprj")
    assert p34 == Path("/site/foo_3_4.iprj")


def test_pair_paths_from_either_member():
    expected = (Path("/site/foo_1_2.iprj"), Path("/site/foo_3_4.iprj"))
    assert pair_paths(Path("/site/foo_1_2.iprj")) == expected
    assert pair_paths(Path("/site/foo_3_4.iprj")) == expected


def test_pair_paths_extensionless_base_defaults_to_iprj():
    assert pair_paths(Path("/site/foo")) == (
        Path("/site/foo_1_2.iprj"), Path("/site/foo_3_4.iprj"))


def test_pair_paths_base_ending_in_digits_not_misstripped():
    # "route_12" ends in digits but not in the _1_2/_3_4 marker.
    p12, p34 = pair_paths(Path("/site/route_12.iprj"))
    assert p12 == Path("/site/route_12_1_2.iprj")
    assert p34 == Path("/site/route_12_3_4.iprj")
    # …and a full member name round-trips back to the same base.
    assert pair_paths(p12) == (p12, p34)


def test_pair_role():
    assert pair_role(Path("/site/foo_1_2.iprj")) == "1_2"
    assert pair_role(Path("/site/foo_3_4.iprj")) == "3_4"
    assert pair_role(Path("/site/foo.iprj")) is None
    assert pair_role(Path("/site/route_12.iprj")) is None


def test_is_valid_pair():
    p12 = Path("/site/foo_1_2.iprj")
    p34 = Path("/site/foo_3_4.iprj")
    assert is_valid_pair(p12, p34)
    assert not is_valid_pair(p34, p12)                            # order matters
    assert not is_valid_pair(p12, Path("/other/foo_3_4.iprj"))    # different dir
    assert not is_valid_pair(p12, Path("/site/bar_3_4.iprj"))     # different base
    assert not is_valid_pair(p12, Path("/site/foo_1_2.iprj"))     # two _1_2
    assert not is_valid_pair(Path("/site/foo.iprj"), p34)         # unsuffixed


# ---------------------------------------------------------------------------
# Sensor counting
# ---------------------------------------------------------------------------

def test_trailing_blank_sensor_does_not_force_second_file():
    project = make_project(2)
    project.sensors.append(Sensor())  # load-style gap-fill padding
    assert real_sensor_count(project) == 2
    assert not is_multifile(project)
    primary, secondary = split_project(project)
    assert secondary is None


def test_is_multifile_threshold():
    assert not is_multifile(make_project(1))
    assert not is_multifile(make_project(2))
    assert is_multifile(make_project(3))
    assert is_multifile(make_project(4))


# ---------------------------------------------------------------------------
# Split
# ---------------------------------------------------------------------------

def test_split_two_sensors_is_plain_single_file(tmp_path):
    project = make_project(2)
    primary, secondary = split_project(project)
    assert secondary is None
    assert primary == project
    assert primary is not project  # no aliasing
    save_iprj(primary, tmp_path / "split.iprj")
    save_iprj(project, tmp_path / "plain.iprj")
    assert (tmp_path / "split.iprj").read_bytes() == (tmp_path / "plain.iprj").read_bytes()


def test_split_ownership_and_no_aliasing():
    project = make_project(4)
    primary, secondary = split_project(project)
    assert [s.event_zones[0].zone_name for s in primary.sensors] == ["Zone 1", "Zone 2"]
    assert [s.event_zones[0].zone_name for s in secondary.sensors] == ["Zone 3", "Zone 4"]
    # Project-wide fields live in the primary only.
    assert primary.lineals == project.lineals and primary.extra == project.extra
    assert secondary.lineals == [] and secondary.text_labels == [] and secondary.extra == {}
    assert secondary.background == project.background
    # Deep copies throughout — mutating an output never touches the input.
    assert primary.background is not project.background
    assert secondary.background is not project.background
    primary.sensors[0].event_zones[0].points[0] = (99.0, 99.0)
    secondary.sensors[0].event_zones[0].zone_name = "changed"
    assert project.sensors[0].event_zones[0].points[0] == (0.0, 0.0)
    assert project.sensors[2].event_zones[0].zone_name == "Zone 3"


def test_split_rejects_five_sensors():
    project = make_project(4)
    project.sensors.append(make_project(1).sensors[0])
    with pytest.raises(ValueError):
        split_project(project)


def test_34_file_serializes_as_radarsensor_0_1_outputs_untouched(tmp_path):
    _, secondary = split_project(make_project(4))
    out = tmp_path / "pair_3_4.iprj"
    save_iprj(secondary, out)
    attrs = read_attrs(out)
    assert attrs["Radarsensor_nrOfSensors"] == "2"
    # Sensor index restarts at 0; rack channels 33/34 are preserved verbatim.
    assert attrs["Radarsensor_0_EventZone_0_OutputNumber"] == "33"
    assert attrs["Radarsensor_1_EventZone_0_OutputNumber"] == "34"
    assert not any(k.startswith("Radarsensor_2_") for k in attrs)
    # Project-wide extras stay in the _1_2 file.
    assert not any(k.startswith(("Lineals_", "Textlabel_")) for k in attrs)
    assert "Zoomfaktor" not in attrs


# ---------------------------------------------------------------------------
# The acceptance test: split -> save -> load -> merge is lossless
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n_sensors", [3, 4])
def test_split_save_load_merge_roundtrip(n_sensors, tmp_path):
    project = make_project(n_sensors)
    primary, secondary = split_project(project)
    p12, p34 = pair_paths(tmp_path / "site.iprj")
    save_iprj(primary, p12)
    save_iprj(secondary, p34)

    merged = merge_pair(load_iprj(p12), load_iprj(p34))
    assert merged == project


# ---------------------------------------------------------------------------
# Background match
# ---------------------------------------------------------------------------

def test_match_identical():
    m = check_background_match(make_bg(), make_bg())
    assert m.ok and not m.warn and m.reason == ""


def test_match_image_size_mismatch_blocks():
    m = check_background_match(make_bg(), make_bg(width=32))
    assert not m.ok
    assert "64x48" in m.reason and "32x48" in m.reason


def test_match_unnormalized_position_blocks():
    b = make_bg()
    b.pos_x = 150.0  # someone skipped normalize_origin
    m = check_background_match(make_bg(), b)
    assert not m.ok
    assert "origin-normalized" in m.reason


def test_match_scale_and_rotation_block():
    b = make_bg()
    b.scale = 50.0
    assert not check_background_match(make_bg(), b).ok
    b = make_bg()
    b.rotation = 1.5
    assert not check_background_match(make_bg(), b).ok


def test_match_meter_per_pixel_mismatch_blocks():
    b = make_bg()
    b.meter_per_pixel = 0.2
    m = check_background_match(make_bg(), b)
    assert not m.ok
    assert "meters-per-pixel" in m.reason


def test_match_calibration_on_one_side_only_blocks():
    b = make_bg()
    b.meter_per_pixel = None
    m = check_background_match(make_bg(), b)
    assert not m.ok
    assert "calibration" in m.reason


def test_match_calibration_missing_on_both_skips_that_tier():
    a, b = make_bg(), make_bg()
    a.meter_per_pixel = b.meter_per_pixel = None
    assert check_background_match(a, b).ok


def test_match_image_on_one_side_only_blocks():
    b = make_bg()
    b.image_base64 = None
    assert not check_background_match(make_bg(), b).ok


def test_match_no_images_at_all_still_compares_geometry():
    a, b = make_bg(), make_bg()
    a.image_base64 = b.image_base64 = None
    m = check_background_match(a, b)
    assert m.ok and not m.warn


def test_match_same_geometry_different_pixels_warns():
    m = check_background_match(make_bg(shade=0), make_bg(shade=200))
    assert m.ok and m.warn and m.reason


# ---------------------------------------------------------------------------
# Merge guards
# ---------------------------------------------------------------------------

def test_merge_hard_mismatch_raises():
    with pytest.raises(BackgroundMismatch):
        merge_pair(make_project(2), make_project(2, bg=make_bg(width=32)))


def test_merge_soft_mismatch_needs_allow_soft():
    primary = make_project(2)
    secondary = make_project(2, bg=make_bg(shade=200))
    with pytest.raises(BackgroundMismatch):
        merge_pair(primary, secondary)
    merged = merge_pair(primary, secondary, allow_soft=True)
    assert len(merged.sensors) == 4
    assert merged.background == primary.background  # primary owns the image


def test_merge_over_four_sensors_raises():
    with pytest.raises(ValueError, match="limit"):
        merge_pair(make_project(3), make_project(2))


# ---------------------------------------------------------------------------
# Real-world pair: the Franklin site ships as exactly this two-file pattern
# ---------------------------------------------------------------------------

FRANKLIN_12 = SITES / "Franklin_KCID" / "Phase 2 & 6 sensor 1 and 2.iprj"
FRANKLIN_34 = SITES / "Franklin_KCID" / "Phase 4 & 8 sensor 3 and 4 with speed.iprj"


def test_franklin_pair_merges():
    primary = load_iprj(FRANKLIN_12)
    secondary = load_iprj(FRANKLIN_34)
    match = check_background_match(primary.background, secondary.background)
    assert match.ok and not match.warn, match.reason

    merged = merge_pair(primary, secondary)
    assert len(merged.sensors) == 4
    assert merged.sensors[:2] == primary.sensors
    assert merged.sensors[2:] == secondary.sensors
    assert merged.background == primary.background
    # OutputNumbers came through verbatim from both files.
    original = [z.output_number
                for proj in (primary, secondary) for s in proj.sensors
                for z in s.event_zones if z.enable]
    merged_outputs = [z.output_number for s in merged.sensors
                      for z in s.event_zones if z.enable]
    assert merged_outputs == original
