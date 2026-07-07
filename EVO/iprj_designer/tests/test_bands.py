"""Index-band ownership primitives (ROADMAP Item 21, model/bands.py)."""

import pytest

from model.bands import (
    FILE1_BAND,
    FILE2_BAND,
    GENERAL_BAND,
    Owner,
    allocate,
    band_for,
    owner_of_index,
    sensor_owner,
)


# Slots are plain ints for the allocator tests: 0 = free placeholder, 1 = used.
def _free(x):
    return x == 0


def _placeholder():
    return 0


# ---------------------------------------------------------------------------
# Band geometry
# ---------------------------------------------------------------------------

def test_bands_tile_0_to_99_without_overlap():
    assert GENERAL_BAND == range(0, 20)
    assert FILE1_BAND == range(20, 60)
    assert FILE2_BAND == range(60, 100)
    assert list(GENERAL_BAND) + list(FILE1_BAND) + list(FILE2_BAND) == list(range(100))


@pytest.mark.parametrize("i,owner", [
    (0, Owner.GENERAL), (19, Owner.GENERAL),
    (20, Owner.FILE1), (59, Owner.FILE1),
    (60, Owner.FILE2), (99, Owner.FILE2),
    (100, Owner.FILE2),  # past the array still classifies (allocate never makes it)
])
def test_owner_of_index(i, owner):
    assert owner_of_index(i) == owner


def test_band_for_round_trips_owner_of_index():
    for owner in Owner:
        for i in band_for(owner):
            assert owner_of_index(i) == owner


def test_sensor_owner_matches_split_boundary():
    assert sensor_owner(0) == Owner.FILE1  # S1
    assert sensor_owner(1) == Owner.FILE1  # S2
    assert sensor_owner(2) == Owner.FILE2  # S3
    assert sensor_owner(3) == Owner.FILE2  # S4


# ---------------------------------------------------------------------------
# allocate
# ---------------------------------------------------------------------------

def test_allocate_from_empty_extends_general_from_zero():
    slots = []
    assert allocate(slots, Owner.GENERAL, 3, _free, _placeholder) == [0, 1, 2]
    assert slots == [0, 0, 0]


def test_allocate_file1_from_empty_extends_up_to_band_start():
    slots = []
    assert allocate(slots, Owner.FILE1, 2, _free, _placeholder) == [20, 21]
    assert len(slots) == 22  # 0..21 materialized, only 20/21 are the picks


def test_allocate_is_lowest_free_first_within_band():
    slots = [0] * 100
    slots[0] = slots[1] = 1
    assert allocate(slots, Owner.GENERAL, 2, _free, _placeholder) == [2, 3]


def test_allocate_stays_inside_its_band():
    slots = [0] * 100
    got = allocate(slots, Owner.FILE1, 3, _free, _placeholder)
    assert got == [20, 21, 22]
    assert all(i in FILE1_BAND for i in got)


def test_allocate_returns_none_on_band_overflow():
    slots = [1] * 20 + [0] * 80  # GENERAL band full
    assert allocate(slots, Owner.GENERAL, 1, _free, _placeholder) is None
    # FILE1/FILE2 still have room
    assert allocate(slots, Owner.FILE1, 1, _free, _placeholder) == [20]


def test_allocate_partial_room_is_overflow_not_partial_fill():
    slots = [1] * 19 + [0] * 81  # one GENERAL slot free
    assert allocate(slots, Owner.GENERAL, 2, _free, _placeholder) is None
    assert allocate(slots, Owner.GENERAL, 1, _free, _placeholder) == [19]


def test_allocate_full_band_capacity():
    assert allocate([], Owner.GENERAL, 20, _free, _placeholder) == list(range(20))
    assert allocate([], Owner.GENERAL, 21, _free, _placeholder) is None
