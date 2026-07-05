"""normalize_origin: the canonical image-origin datum (ROADMAP Item 11)."""

import copy

import pytest

from model.coords import normalize_origin
from model.iprj_io import (
    Background,
    EventZone,
    IgnoreZone,
    Lineal,
    Project,
    Sensor,
    TextLabel,
)
from model.units import effective_meter_per_pixel

DX, DY = -244.0, 57.5  # vendor-style arbitrary background position


def make_project() -> Project:
    return Project(
        background=Background(
            pos_x=DX, pos_y=DY, rotation=0.0, scale=100.0,
            meter_per_pixel=0.08, reference_length=30.0,
            ref0_x=-100.0, ref0_y=100.0, ref1_x=293.7, ref1_y=100.0,
        ),
        sensors=[Sensor(
            position_x=10.0, position_y=20.0,
            event_zones=[
                EventZone(
                    eta_enable=1, eta_point_x=5.0, eta_point_y=6.0,
                    points=[(0.0, 0.0), (4.0, 0.0), (4.0, 8.0), (0.0, 8.0)],
                ),
                EventZone(enable=0),  # disabled vendor placeholder
            ],
            ignore_zones=[IgnoreZone(points=[(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)])],
        )],
        lineals=[Lineal(enable=1, point_0=(7.0, 8.0), point_1=(9.0, 10.0))],
        text_labels=[TextLabel(text="hi", position_x=11.0, position_y=12.0)],
    )


def shifted(p):
    return (p[0] - DX, p[1] - DY)


def test_everything_shifts_to_image_origin():
    project = make_project()
    assert normalize_origin(project) is project  # mutates in place

    bg = project.background
    assert (bg.pos_x, bg.pos_y) == (0.0, 0.0)
    assert (bg.ref0_x, bg.ref0_y) == shifted((-100.0, 100.0))
    assert (bg.ref1_x, bg.ref1_y) == shifted((293.7, 100.0))

    sensor = project.sensors[0]
    assert (sensor.position_x, sensor.position_y) == shifted((10.0, 20.0))
    zone = sensor.event_zones[0]
    assert (zone.eta_point_x, zone.eta_point_y) == shifted((5.0, 6.0))
    assert zone.points == [shifted(p) for p in
                           [(0.0, 0.0), (4.0, 0.0), (4.0, 8.0), (0.0, 8.0)]]
    assert sensor.ignore_zones[0].points == [
        shifted(p) for p in [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]]

    # disabled placeholders move with the frame too
    placeholder = sensor.event_zones[1]
    assert (placeholder.eta_point_x, placeholder.eta_point_y) == shifted((0.0, 0.0))

    lineal = project.lineals[0]
    assert lineal.point_0 == shifted((7.0, 8.0))
    assert lineal.point_1 == shifted((9.0, 10.0))
    label = project.text_labels[0]
    assert (label.position_x, label.position_y) == shifted((11.0, 12.0))


def test_calibration_untouched():
    project = make_project()
    before = effective_meter_per_pixel(project.background)
    normalize_origin(project)
    bg = project.background
    assert effective_meter_per_pixel(bg) == before
    assert bg.meter_per_pixel == 0.08
    assert bg.reference_length == 30.0
    assert bg.rotation == 0.0 and bg.scale == 100.0


def test_idempotent():
    once = normalize_origin(make_project())
    twice = normalize_origin(copy.deepcopy(once))
    assert twice == once


def test_zero_or_missing_pos_is_a_noop():
    project = make_project()
    project.background.pos_x, project.background.pos_y = 0.0, 0.0
    assert normalize_origin(copy.deepcopy(project)) == project
    # converter-form file with no Background_Pos keys at all
    project.background.pos_x = project.background.pos_y = None
    assert normalize_origin(copy.deepcopy(project)) == project


def test_none_fields_stay_none():
    # A sparse converter-style project: pos present, most keys absent — the
    # save path must not gain attributes it didn't have (save skips None).
    project = Project(
        background=Background(pos_x=DX, pos_y=DY),
        sensors=[Sensor(position_x=None, position_y=None,
                        event_zones=[EventZone(eta_point_x=None, eta_point_y=None)])],
        lineals=[Lineal(point_0=(7.0, 8.0), point_1=None)],
        text_labels=[TextLabel(position_x=None, position_y=None)],
    )
    normalize_origin(project)
    bg = project.background
    assert (bg.pos_x, bg.pos_y) == (0.0, 0.0)
    assert bg.ref0_x is None and bg.ref1_y is None
    sensor = project.sensors[0]
    assert sensor.position_x is None and sensor.position_y is None
    zone = sensor.event_zones[0]
    assert zone.eta_point_x is None and zone.eta_point_y is None
    assert project.lineals[0].point_0 == shifted((7.0, 8.0))
    assert project.lineals[0].point_1 is None
    label = project.text_labels[0]
    assert label.position_x is None and label.position_y is None


def test_one_axis_missing():
    project = Project(background=Background(pos_x=None, pos_y=DY),
                      sensors=[Sensor(position_x=10.0, position_y=20.0)])
    normalize_origin(project)
    assert project.background.pos_x is None
    assert project.background.pos_y == 0.0
    sensor = project.sensors[0]
    assert (sensor.position_x, sensor.position_y) == (10.0, 20.0 - DY)


def test_distances_preserved():
    project = normalize_origin(make_project())
    pts = project.sensors[0].event_zones[0].points
    assert pts[1][0] - pts[0][0] == pytest.approx(4.0)
    assert pts[2][1] - pts[1][1] == pytest.approx(8.0)
