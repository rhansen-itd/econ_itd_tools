"""Vendor index bands for sensor-scoped annotations (ROADMAP Item 21).

`Lineal` and `Textlabel` slots persist **by index** in the vendor software —
writing lineal 10 with 1–9 absent reloads and re-saves as lineal 10 — and the
vendor auto-writes new annotations to the lowest free index. We exploit that
to route annotations to the right file of the two-file split
(`model/multifile.py`) purely by which index band they sit in:

    indices  0–19  (vendor 1–20)   GENERAL  -> written to *both* files
    indices 20–59  (vendor 21–60)  FILE1    -> sensors 1&2, the _1_2 file
    indices 60–99  (vendor 61–100) FILE2    -> sensors 3&4, the _3_4 file

Ownership carries **no on-disk tag**; it is inferred from the band an
element's slot index falls in (`owner_of_index`) and re-materialized into that
band on save. Reserving the low GENERAL band means the vendor's
lowest-free-index auto-write lands there by construction, so annotations added
in the vendor software stay "general" rather than colliding with a sensor's
band. The active sensor maps to a file band exactly as the split boundary
does: sensor index 0/1 -> FILE1, 2/3 -> FILE2 (`sensor_owner`).

The 100-slot cap is structural here: `allocate` never picks an index past a
band's end, so a full band overflows (returns None) rather than growing the
array past the vendor's fixed 100 entries.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Callable


class Owner(IntEnum):
    """Which file(s) an annotation is written to on the two-file split."""
    GENERAL = 0  # both files
    FILE1 = 1    # sensors 1&2 (_1_2)
    FILE2 = 2    # sensors 3&4 (_3_4)


GENERAL_BAND = range(0, 20)
FILE1_BAND = range(20, 60)
FILE2_BAND = range(60, 100)
SLOT_COUNT = 100

_BANDS = {Owner.GENERAL: GENERAL_BAND, Owner.FILE1: FILE1_BAND, Owner.FILE2: FILE2_BAND}


def band_for(owner: Owner) -> range:
    return _BANDS[owner]


def owner_of_index(i: int) -> Owner:
    """The band owner of slot index *i* (indices past 99 read as FILE2, but
    `allocate` never creates them)."""
    if i < GENERAL_BAND.stop:
        return Owner.GENERAL
    if i < FILE1_BAND.stop:
        return Owner.FILE1
    return Owner.FILE2


def sensor_owner(si: int) -> Owner:
    """File band an active sensor index (0-based) writes to: 0/1 -> FILE1,
    2/3 -> FILE2 — the same boundary `model/multifile.split_project` uses.
    So S2 (index 1) is FILE1 and S4 (index 3) is FILE2."""
    return Owner.FILE1 if si < 2 else Owner.FILE2


def allocate(
    slots: list,
    owner: Owner,
    count: int,
    is_free: Callable[[object], bool],
    make_placeholder: Callable[[], object],
) -> list[int] | None:
    """Pick *count* free slot indices inside *owner*'s band, lowest-first,
    extending *slots* with placeholders where the chosen index is past the
    current length.

    A slot is available when it is beyond the current array (implicitly a
    free future placeholder) or `is_free` says so. Returns the chosen indices
    ascending, or None when the band cannot fit *count* more items — the
    caller surfaces that as an overflow (the vendor's 100-slot array is fixed;
    we never spill past a band's end).
    """
    band = band_for(owner)
    chosen: list[int] = []
    for i in band:
        if len(chosen) == count:
            break
        if i >= len(slots) or is_free(slots[i]):
            chosen.append(i)
    if len(chosen) < count:
        return None
    for i in chosen:
        while len(slots) <= i:
            slots.append(make_placeholder())
    return chosen
