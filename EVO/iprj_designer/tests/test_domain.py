import pytest

from model import domain
from model.domain import Direction, VehicleClass, ZoneType
from model.iprj_io import IgnoreZone, Lineal


# -- vendor codes -------------------------------------------------------------

def test_zone_type_codes():
    # Confirmed in the vendor UI (2026-07-03): 0 Motion, 1 Presence, 2 Sidewalk
    assert ZoneType.MOTION == 0
    assert ZoneType.PRESENCE == 1
    assert ZoneType.SIDEWALK == 2
    assert domain.ZONE_TYPE_NAMES[ZoneType.PRESENCE] == "Presence"


def test_vehicle_class_codes():
    assert VehicleClass.ALL == 0
    assert VehicleClass.CAR == 1
    assert VehicleClass.BIKE_PED == 2
    assert VehicleClass.SMALL_TRUCK == 3
    assert VehicleClass.BIG_TRUCK == 4
    assert VehicleClass.CAR_BIG_TRUCK == 5
    assert VehicleClass.CAR_SMALL_TRUCK == 6
    assert VehicleClass.CAR_SMALL_BIG_TRUCK == 7
    assert len(domain.VEHICLE_CLASS_NAMES) == 8


def test_direction_codes():
    assert Direction.BOTH == 0
    assert Direction.APPROACHING == 1
    assert Direction.RECEDING == 2


# -- condition-field relevance ------------------------------------------------

def test_condition_fields_by_zone_type():
    presence = domain.condition_fields(ZoneType.PRESENCE)
    motion = domain.condition_fields(ZoneType.MOTION)
    assert "queuelength_max" in presence and "nr_cars_max" in presence
    assert "velocity_max" not in presence and "direction" not in presence
    assert "velocity_max" in motion and "direction" in motion \
        and "condition_class" in motion and "eta_max" in motion
    assert "queuelength_max" not in motion and "nr_cars_max" not in motion


def test_sidewalk_takes_no_conditions():
    assert domain.condition_fields(ZoneType.SIDEWALK) == ()
    assert not domain.conditions_allowed(ZoneType.SIDEWALK)
    assert domain.conditions_allowed(ZoneType.MOTION)
    assert domain.conditions_allowed(ZoneType.PRESENCE)
    assert domain.conditions_allowed(None)  # unset zone_type reads as 0


def test_condition_fields_unknown_code_shows_everything():
    fields = domain.condition_fields(99)
    assert set(domain.condition_fields(ZoneType.MOTION)) <= set(fields)
    assert set(domain.condition_fields(ZoneType.PRESENCE)) <= set(fields)


def test_condition_fields_are_real_condition_attrs():
    from model.iprj_io import Condition
    c = Condition()
    for zt in ZoneType:
        for f in domain.condition_fields(zt):
            assert hasattr(c, f), f


def test_default_condition_sentinels():
    c = domain.default_condition(output=17)
    assert c.enable == 1 and c.output_number == 17
    assert c.velocity_min == 0.0
    assert c.velocity_max == 16091.79  # 9999 mph as the vendor stores it
    assert c.queuelength_max == 3047.70  # 9999 ft in meters
    assert c.eta_max == 999.0
    assert c.nr_cars_max == c.nr_big_trucks_max == 255


# -- ignore zone helpers --------------------------------------------------------

TRIANGLE = [(0.0, 0.0), (10.0, 0.0), (5.0, 8.0)]


def test_ignore_zone_placeholder_and_insert():
    placeholder = IgnoreZone(enable=0, zone_name="", points=[])
    real = domain.new_ignore_zone(TRIANGLE, name="bridge rail")
    assert domain.is_placeholder_ignore(placeholder)
    assert not domain.is_placeholder_ignore(real)
    assert real.enable == 1 and real.ignore_everything == 1

    zones = [placeholder, IgnoreZone(enable=0, zone_name="", points=[])]
    assert domain.insert_ignore_zone(zones, real) == 0  # takes the first slot
    assert zones[0] is real and len(zones) == 2


def test_ignore_zone_insert_appends_then_caps():
    zones = [domain.new_ignore_zone(TRIANGLE) for _ in range(domain.MAX_IGNORE_ZONES - 1)]
    assert domain.insert_ignore_zone(zones, domain.new_ignore_zone(TRIANGLE)) \
        == domain.MAX_IGNORE_ZONES - 1
    with pytest.raises(ValueError):
        domain.insert_ignore_zone(zones, domain.new_ignore_zone(TRIANGLE))


# -- lineal helpers -------------------------------------------------------------

def test_lineal_placeholder_and_insert():
    placeholder = Lineal(enable=0, point_0=(0.0, 0.0), point_1=(0.0, 0.0))
    missing = Lineal(enable=0)
    real = domain.new_lineal((1.0, 2.0), (30.0, 40.0))
    disabled_real = Lineal(enable=0, point_0=(1.0, 2.0), point_1=(3.0, 4.0))
    assert domain.is_placeholder_lineal(placeholder)
    assert domain.is_placeholder_lineal(missing)
    assert not domain.is_placeholder_lineal(real)
    assert not domain.is_placeholder_lineal(disabled_real)  # keeps hidden geometry

    lineals = [placeholder]
    assert domain.insert_lineal(lineals, real) == 0
    assert lineals[0] is real

    second = domain.new_lineal((5.0, 5.0), (6.0, 6.0))
    assert domain.insert_lineal(lineals, second) == 1  # no slot left: append


def test_lineal_insert_caps_at_vendor_array():
    lineals = [domain.new_lineal((i, 0.0), (i, 1.0)) for i in range(domain.MAX_LINEALS)]
    with pytest.raises(ValueError):
        domain.insert_lineal(lineals, domain.new_lineal((0.0, 0.0), (1.0, 1.0)))
