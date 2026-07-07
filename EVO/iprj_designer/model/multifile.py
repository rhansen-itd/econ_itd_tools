"""Multi-sensor two-file split/merge (ROADMAP Item 9, see ITEM9_SPLIT_PLAN.md).

The vendor caps a .iprj at 2 sensors, so a 3-4 sensor project lives on disk as
a filename-convention pair — `<base>_1_2.iprj` (sensors 1-2) and
`<base>_3_4.iprj` (sensors 3-4, written as Radarsensor_0/1 in that file) —
while in memory there is always exactly one Project. The split happens on
save, the merge on overlay-open; nothing else in the model changes. Each
output file stays 100% vendor-clean: the filename is the only pairing channel.

Coregistration relies on origin normalization (coords.normalize_origin,
Item 11): both files of a pair are expressed relative to the shared image's
top-left, so the merge is a plain sensor-list append — no cross-file delta.
check_background_match() verifies that premise on the overlay-open path,
where the user could pick two unrelated files.

OutputNumbers are project-wide detector-rack channels and are never renumbered
by the split; only the sensor *index* restarts at 0 in the _3_4 file (free —
save_iprj enumerates the sensor list).

Project-wide extras (lineals, text labels, project.extra) are owned by the
_1_2 file; the _3_4 file carries only the duplicated background + its sensors.
"""

from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .bands import FILE1_BAND, FILE2_BAND, GENERAL_BAND, Owner, owner_of_index
from .iprj_io import Background, Lineal, Project, Sensor, TextLabel
from .labels import DISABLED_POSITION
from .units import (
    background_image_size,
    decode_background_image,
    effective_meter_per_pixel,
)

MAX_SENSORS = 4  # vendor cap of 2 sensors/file x 2 files


# ---------------------------------------------------------------------------
# Band-scoped annotation helpers (ROADMAP Item 21)
# ---------------------------------------------------------------------------

def _blank_lineal_slot() -> Lineal:
    return Lineal(enable=0, point_0=(0.0, 0.0), point_1=(0.0, 0.0))


def _blank_label_slot() -> TextLabel:
    return TextLabel(enable=0, text="",
                     position_x=DISABLED_POSITION, position_y=DISABLED_POSITION)


def _blank_band(slots: list, band: range, placeholder) -> None:
    """Reset every slot of *band* that exists in *slots* to a fresh
    placeholder (in place)."""
    for i in band:
        if i < len(slots):
            slots[i] = placeholder()


def _copy_blanked(slots: list, band: range, placeholder) -> list:
    """Deep copy *slots* with *band* blanked to placeholders."""
    out = copy.deepcopy(list(slots))
    _blank_band(out, band, placeholder)
    return out


def _combine_bands(primary: list, secondary: list, placeholder) -> list:
    """Recombine two split annotation arrays: the FILE2 band comes from the
    *secondary* (_3_4) file, everything else (GENERAL + FILE1) from the
    *primary* (_1_2) file, mirroring the split. Missing slots are
    placeholders, so length differences degrade cleanly."""
    n = max(len(primary), len(secondary))
    out = []
    for i in range(n):
        src = secondary if owner_of_index(i) == Owner.FILE2 else primary
        out.append(copy.deepcopy(src[i]) if i < len(src) else placeholder())
    return out


def _enabled_in_band(slots: list, band: range) -> list:
    return [slots[i] for i in band if i < len(slots) and slots[i].enable]


def general_blocks_match(primary: Project, secondary: Project) -> bool:
    """Whether the GENERAL band (indices 0–19) of both lineals and text
    labels agrees between the two files of a pair (ROADMAP Item 21).

    A clean split duplicates the general block into both files, so they are
    identical; a mismatch means one file's general annotations were edited
    independently in the vendor software. `merge_pair` keeps the primary's
    regardless — this is the soft-warn signal the GUI surfaces (cf.
    `check_background_match`). Compares enabled entries only, so a
    placeholder-padded array still matches an unpadded one."""
    return (_enabled_in_band(primary.lineals, GENERAL_BAND)
            == _enabled_in_band(secondary.lineals, GENERAL_BAND)
            and _enabled_in_band(primary.text_labels, GENERAL_BAND)
            == _enabled_in_band(secondary.text_labels, GENERAL_BAND))

_PAIR_RE = re.compile(r"^(.*)_(1_2|3_4)$")  # on the stem

_POS_TOL = 0.01    # post-normalization residual allowed on Background pos
_SCALE_TOL = 0.01
_ROTATION_TOL = 0.01
_MPP_TOL = 0.005   # same tolerance units.effective_meter_per_pixel uses


# ---------------------------------------------------------------------------
# Naming convention
# ---------------------------------------------------------------------------

def pair_role(path: str | Path) -> str | None:
    """"1_2" | "3_4" | None for a path's place in the naming convention."""
    m = _PAIR_RE.match(Path(path).stem)
    return m.group(2) if m else None


def pair_paths(one: str | Path) -> tuple[Path, Path]:
    """Any member path (or an unsuffixed base) -> (path_1_2, path_3_4).

    Strips a trailing _1_2/_3_4 from the stem to get the base, so any of
    `foo`, `foo_1_2.iprj`, `foo_3_4.iprj` yields the same pair. A missing
    file extension defaults to .iprj.
    """
    one = Path(one)
    m = _PAIR_RE.match(one.stem)
    base = m.group(1) if m else one.stem
    suffix = one.suffix or ".iprj"
    return (one.with_name(f"{base}_1_2{suffix}"),
            one.with_name(f"{base}_3_4{suffix}"))


def is_valid_pair(p1: str | Path, p2: str | Path) -> bool:
    """True iff (p1, p2) are <base>_1_2 / <base>_3_4 in the same directory.

    Order matters: p1 must be the _1_2 member (Viewer.pair stores them that
    way and plain Save trusts the order).
    """
    p1, p2 = Path(p1), Path(p2)
    if p1.parent != p2.parent or p1.suffix != p2.suffix:
        return False
    m1 = _PAIR_RE.match(p1.stem)
    m2 = _PAIR_RE.match(p2.stem)
    return (m1 is not None and m2 is not None
            and m1.group(1) == m2.group(1)
            and (m1.group(2), m2.group(2)) == ("1_2", "3_4"))


# ---------------------------------------------------------------------------
# Sensor counting
# ---------------------------------------------------------------------------

def real_sensor_count(project: Project) -> int:
    """Sensors that count toward the 2-per-file vendor cap.

    Every sensor the GUI shows is real (add_sensor always positions it);
    vendor files never pad sensor slots (site survey — nrOfSensors always
    equals the written indices). The only discountable entries are trailing
    all-default Sensor() padding, e.g. load_iprj's gap fill, which must not
    force a spurious second file.
    """
    blank = Sensor()
    n = len(project.sensors)
    while n and project.sensors[n - 1] == blank:
        n -= 1
    return n


def is_multifile(project: Project) -> bool:
    """True when the project needs the two-file pair on disk (>2 sensors)."""
    return real_sensor_count(project) > 2


# ---------------------------------------------------------------------------
# Background match (overlay-open safety check)
# ---------------------------------------------------------------------------

@dataclass
class BackgroundMatch:
    ok: bool     # False -> hard fail, block the merge
    warn: bool   # True with ok -> soft mismatch, ask the user
    reason: str  # first field that diverged, with both values; "" on a match


class BackgroundMismatch(ValueError):
    """Raised by merge_pair when the two backgrounds cannot overlay."""


def check_background_match(a: Background, b: Background) -> BackgroundMatch:
    """Can two projects' backgrounds be overlaid as one? Two-tier check.

    Tier 1 (hard fail): image dimensions, origin-normalized position, scale,
    rotation, effective meters-per-pixel. Any mismatch makes overlaying the
    zones meaningless. Both backgrounds must already be origin-normalized
    (load_iprj does this); a residual position means one wasn't, and is a
    hard fail rather than a real background mismatch.

    Tier 2 (soft warn): same geometry but different pixel content (e.g. a
    re-encoded image) returns ok=True, warn=True so the GUI can ask instead
    of blocking. Missing data degrades gracefully: absent on both sides ->
    that tier is skipped; absent on one side only -> hard fail.
    """
    def fail(reason: str) -> BackgroundMatch:
        return BackgroundMatch(ok=False, warn=False, reason=reason)

    # Tier 1 — geometry.
    if bool(a.image_base64) != bool(b.image_base64):
        return fail("one file has an embedded background image, the other does not")
    if a.image_base64 and b.image_base64:
        try:
            size_a, size_b = background_image_size(a), background_image_size(b)
        except ValueError:  # non-PNG payload; sizes unknowable, hash still runs
            size_a = size_b = None
        if size_a != size_b:
            return fail(f"image is {size_a[0]}x{size_a[1]} vs {size_b[0]}x{size_b[1]}")

    for which, bg in (("first", a), ("second", b)):
        if abs(bg.pos_x or 0.0) > _POS_TOL or abs(bg.pos_y or 0.0) > _POS_TOL:
            return fail(
                f"{which} file is not origin-normalized: background pos is "
                f"({bg.pos_x}, {bg.pos_y}), expected (0, 0)")

    scale_a = a.scale if a.scale is not None else 100.0
    scale_b = b.scale if b.scale is not None else 100.0
    if abs(scale_a - scale_b) > _SCALE_TOL:
        return fail(f"image scale is {scale_a} vs {scale_b}")

    rot_a = a.rotation if a.rotation is not None else 0.0
    rot_b = b.rotation if b.rotation is not None else 0.0
    if abs(rot_a - rot_b) > _ROTATION_TOL:
        return fail(f"image rotation is {rot_a} vs {rot_b}")

    def mpp(bg: Background) -> float | None:
        try:
            return effective_meter_per_pixel(bg)
        except ValueError:
            return None

    mpp_a, mpp_b = mpp(a), mpp(b)
    if (mpp_a is None) != (mpp_b is None):
        return fail("one file has a scale calibration, the other does not")
    if mpp_a is not None and abs(mpp_a - mpp_b) > _MPP_TOL:
        return fail(f"meters-per-pixel is {mpp_a:.4f} vs {mpp_b:.4f}")

    # Tier 2 — pixel content.
    if a.image_base64 and b.image_base64:
        digest_a = hashlib.sha256(decode_background_image(a)).digest()
        digest_b = hashlib.sha256(decode_background_image(b)).digest()
        if digest_a != digest_b:
            return BackgroundMatch(
                ok=True, warn=True,
                reason="backgrounds share size and calibration but the image "
                       "pixels differ (re-encoded or edited copy?)")

    return BackgroundMatch(ok=True, warn=False, reason="")


# ---------------------------------------------------------------------------
# Split / merge
# ---------------------------------------------------------------------------

def split_project(project: Project) -> tuple[Project, Project | None]:
    """One in-memory Project -> (primary, secondary) for the two-file save.

    secondary is None when <=2 sensors (today's single-file behavior; the
    primary is then the whole project unchanged). Otherwise annotations
    (lineals + text labels) split by index band (ROADMAP Item 21):

    - primary  = sensors[0:2] + project extra/metadata + the GENERAL (0–19)
      and FILE1 (20–59) annotation bands (the FILE2 band, 60–99, blanked),
    - secondary = sensors[2:4] + a deep copy of the background + the GENERAL
      (0–19) and FILE2 (60–99) annotation bands (the FILE1 band blanked).

    The GENERAL band is duplicated into **both** files; each file's FILE band
    holds only that pair's sensor annotations. `project.extra` (Zoomfaktor,
    plot prefs) stays with the primary. date/version/product_code are
    mirrored so the pair looks alike to the vendor; merge_pair takes the
    primary's anyway.

    save_iprj enumerates the sensor list, so the secondary's sensors come out
    as Radarsensor_0/1 with no index rewriting; OutputNumbers are untouched.
    Everything is deep-copied — neither returned Project aliases the input.
    """
    n = real_sensor_count(project)
    if n > MAX_SENSORS:
        raise ValueError(
            f"project has {n} sensors; the two-file limit is {MAX_SENSORS}")
    primary = copy.deepcopy(project)
    if n <= 2:
        return primary, None
    secondary = Project(
        background=copy.deepcopy(primary.background),
        sensors=primary.sensors[2:n],  # already fresh copies
        lineals=_copy_blanked(project.lineals, FILE1_BAND, _blank_lineal_slot),
        text_labels=_copy_blanked(project.text_labels, FILE1_BAND, _blank_label_slot),
        date=primary.date,
        version=primary.version,
        product_code=primary.product_code,
    )
    _blank_band(primary.lineals, FILE2_BAND, _blank_lineal_slot)
    _blank_band(primary.text_labels, FILE2_BAND, _blank_label_slot)
    primary.sensors = primary.sensors[:2]
    return primary, secondary


def merge_pair(primary: Project, secondary: Project, *,
               allow_soft: bool = False) -> Project:
    """(_1_2 project, _3_4 project) -> one Project with sensors [p0,p1,s0,s1].

    Background, extra, and metadata come from the primary; the secondary
    contributes its sensors and its FILE2 annotation band (indices 60–99).
    Annotations recombine by band (ROADMAP Item 21): GENERAL (0–19) + FILE1
    (20–59) from the primary, FILE2 from the secondary. The primary's GENERAL
    block wins silently even if the two disagree — call `general_blocks_match`
    for the soft-warn signal (the GUI does, cf. `check_background_match`).

    Raises BackgroundMismatch on a check_background_match hard fail, and on
    the soft-warn (same geometry, different pixels) case too unless
    allow_soft=True — the GUI runs the check itself first and passes
    allow_soft after the user confirms. Raises ValueError when the combined
    sensor count exceeds MAX_SENSORS (e.g. two _1_2 files overlaid).
    """
    match = check_background_match(primary.background, secondary.background)
    if not match.ok or (match.warn and not allow_soft):
        raise BackgroundMismatch(match.reason)

    n_primary = real_sensor_count(primary)
    n_secondary = real_sensor_count(secondary)
    if n_primary + n_secondary > MAX_SENSORS:
        raise ValueError(
            f"{n_primary} + {n_secondary} sensors exceeds the "
            f"{MAX_SENSORS}-sensor two-file limit — are both files "
            f"really a 1-2/3-4 pair?")

    merged = copy.deepcopy(primary)
    merged.sensors = (merged.sensors[:n_primary]
                      + copy.deepcopy(secondary.sensors[:n_secondary]))
    merged.lineals = _combine_bands(
        primary.lineals, secondary.lineals, _blank_lineal_slot)
    merged.text_labels = _combine_bands(
        primary.text_labels, secondary.text_labels, _blank_label_slot)
    return merged
