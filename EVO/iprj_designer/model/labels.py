"""Text-label persistence with sensor-scoped index bands (ROADMAP Item 21).

Parallel to `model/centerline.py`'s Lineal handling: text labels live in the
project's fixed `Textlabel` array (100 slots in vendor files), and which band
a label's slot index falls in decides its file `Owner` and thus which file(s)
it is written to on the two-file split. Ownership carries no on-disk tag; it
is inferred on load from the slot's band and re-materialized into that band on
save — see `model/bands.py` for the band layout.

A label is "used" when enabled; disabled placeholder slots are free for reuse
regardless of their parked position (the vendor sits disabled labels at
`Position_X/Y = -9999`, `DISABLED_POSITION`). The GUI passes the complete
label set on every save, so `save_labels_owned` blanks all enabled labels
first and refills — the same full-replace model the Lineal writers use.
"""

from __future__ import annotations

import copy
import math
from typing import Sequence

from .bands import Owner, allocate, owner_of_index
from .iprj_io import Point, Project, TextLabel

# The vendor parks disabled labels off-canvas here rather than at (0, 0).
DISABLED_POSITION = -9999.0

# World-px tolerance for recognizing a centerline-name label sitting at a
# centerline's far end — same order as gui/drawing.ATTACH_TOL: the vendor
# rounds coordinates to 2 decimals, hand-drawn slop is a screen pixel or more.
NAME_LABEL_TOL = 0.05


def _placeholder_label() -> TextLabel:
    return TextLabel(enable=0, text="",
                     position_x=DISABLED_POSITION, position_y=DISABLED_POSITION)


def _is_free(label: TextLabel) -> bool:
    """A slot free for reuse: any disabled label (enabled labels are the
    project's real annotations; disabled ones are placeholders whatever their
    parked position)."""
    return not label.enable


def _blank(label: TextLabel) -> None:
    label.enable = 0
    label.text = ""
    label.position_x = DISABLED_POSITION
    label.position_y = DISABLED_POSITION


def load_labels(project: Project) -> list[TextLabel]:
    """Every enabled text label, as fresh working copies for the GUI pool."""
    return [lbl for _, lbl in load_labels_owned(project)]


def load_labels_owned(project: Project) -> list[tuple[Owner, TextLabel]]:
    """Every enabled text label with the file `Owner` inferred from its
    slot's band (ROADMAP Item 21)."""
    return [(owner_of_index(i), copy.deepcopy(lbl))
            for i, lbl in enumerate(project.text_labels) if lbl.enable]


def save_labels_owned(
    project: Project,
    labels: Sequence[tuple[Owner, TextLabel]],
) -> list[TextLabel]:
    """Write *labels* (each tagged with its file `Owner`) as the project's
    full set, each into a free slot *within its band* (ROADMAP Item 21),
    lowest-first, replacing the previous set.

    All currently-enabled labels are blanked to placeholder form first (full
    replace — the caller passes the complete set); disabled labels are the
    free pool. A label whose band is full (overflow) is left unplaced and
    returned. Disabled entries in *labels* are ignored. Passing [] clears
    every label.
    """
    for lbl in project.text_labels:
        if lbl.enable:
            _blank(lbl)
    skipped: list[TextLabel] = []
    for owner, label in labels:
        if not label.enable:
            continue
        idxs = allocate(project.text_labels, owner, 1, _is_free, _placeholder_label)
        if idxs is None:
            skipped.append(label)
            continue
        project.text_labels[idxs[0]] = copy.deepcopy(label)
    return skipped


def save_labels(project: Project, labels: Sequence[TextLabel]) -> list[TextLabel]:
    """GENERAL-band `save_labels_owned`: every label goes to the 0–19 band
    (written to both files of a split). Kept for callers that don't track
    ownership."""
    return save_labels_owned(project, [(Owner.GENERAL, l) for l in labels])


# ---------------------------------------------------------------------------
# Centerline-name labels (ROADMAP Item 22)
# ---------------------------------------------------------------------------
#
# A centerline's session name is persisted as a no-rotation text label sitting
# at the centerline's far end (the point furthest from the stop bar). Because
# the .iprj format carries no association tag, the link is re-derived on load
# purely by geometry, the way gui/drawing.derive_attachments re-links zones to
# centerlines: a no-rotation label within NAME_LABEL_TOL of a centerline's far
# end is that centerline's name label.


def is_name_label(label: TextLabel) -> bool:
    """The shape a centerline-name label takes: an enabled, un-rotated text
    label (a rotated label is decorative, never a name) that is not a
    membership label (ROADMAP Item 26 — those also sit un-rotated but carry a
    ``name: outputs`` list and belong to `parse_membership_label`)."""
    return (bool(label.enable) and abs(label.rotation_angle or 0.0) < 1e-6
            and parse_membership_label(label.text or "") is None)


def match_name_labels(
    far_ends: Sequence[Point | None],
    labels: Sequence[TextLabel],
    tol: float = NAME_LABEL_TOL,
) -> dict[int, int]:
    """Associate centerlines with their name labels by geometry (ROADMAP
    Item 22).

    *far_ends* is one point per centerline (its furthest-from-stop-bar vertex,
    or None when the centerline has no geometry yet). Returns a mapping
    ``centerline index -> label index`` for every no-rotation label within
    *tol* of a centerline's far end. Ties are broken by distance, then by
    first appearance: each label names at most one centerline and each
    centerline takes at most one label, so two centerlines whose ends coincide
    still resolve deterministically."""
    cands: list[tuple[float, int, int]] = []
    for ci, end in enumerate(far_ends):
        if end is None:
            continue
        for li, lbl in enumerate(labels):
            if not is_name_label(lbl):
                continue
            d = math.hypot((lbl.position_x or 0.0) - end[0],
                           (lbl.position_y or 0.0) - end[1])
            if d <= tol:
                cands.append((d, ci, li))
    result: dict[int, int] = {}
    used_labels: set[int] = set()
    for _, ci, li in sorted(cands, key=lambda c: (c[0], c[1], c[2])):
        if ci in result or li in used_labels:
            continue
        result[ci] = li
        used_labels.add(li)
    return result


# ---------------------------------------------------------------------------
# Centerline-membership labels (ROADMAP Item 26)
# ---------------------------------------------------------------------------
#
# A zone's tie to a centerline (which detectors belong to which approach) is
# geometric and implicit today — re-derived on load by
# gui/drawing.derive_attachments. Item 26 makes it explicit and persisted, the
# same no-format-extension way centerline names are (above): a per-centerline
# text label whose Text reads ``"[centerline name]: [zone slots]"`` — e.g.
# ``"N_CL: 2_5, 2_7, 3_1"``. Each member is named by its **(sensor index, zone
# index) slot** — the vendor stores zones in fixed per-sensor slots that persist
# by index across a save/reload (the same property model/bands.py exploits for
# Lineals/Textlabels), so the slot is a unique, round-trip-stable identifier —
# unlike OutputNumber, which real projects reuse across zones. On load the label
# is re-parsed and each listed slot re-attached, with no recourse to geometry —
# see gui/app.ViewportState._derive_membership.
#
# The sensor index is written in **absolute (merged-project) space** (sensors
# 0-3). On the two-file split the _3_4 half's sensors are renumbered to 0/1, so
# the reader offsets file-local indices back to absolute using the file's pair
# role (`_derive_membership`); this keeps a bare _3_4 half resolvable, not only
# the merged overlay. The label sits top-left (cosmetic — the tie is re-derived
# from its Text, not its position) and lives in the centerline's owner band, so
# a sensor-owned group's membership label travels to the right file on the split.


def format_membership_label(name: str,
                            slots: Sequence[tuple[int, int]]) -> str:
    """Render a centerline's membership as label Text (ROADMAP Item 26):
    ``"[name]: [slots]"`` with each ``(sensor_index, zone_index)`` slot written
    ``sensor_zone``, sorted and de-duplicated — e.g.
    ``format_membership_label("N_CL", [(2, 7), (2, 5)])`` -> ``"N_CL: 2_5, 2_7"``."""
    keys = sorted({(int(si), int(zi)) for si, zi in slots})
    return f"{name}: {', '.join(f'{si}_{zi}' for si, zi in keys)}"


def parse_membership_label(text: str) -> tuple[str, list[tuple[int, int]]] | None:
    """Inverse of `format_membership_label`: ``"N_CL: 2_5, 2_7"`` ->
    ``("N_CL", [(2, 5), (2, 7)])`` (ROADMAP Item 26). Returns None for anything
    that is not a ``name: <comma-separated sensor_zone slots>`` shape — a bare
    name, an empty name, or any token that is not two underscore-joined
    non-negative integers — so ordinary text labels are never mistaken for
    membership labels. The caller further requires the parsed name to match a
    real centerline before adopting it."""
    s = (text or "").strip()
    if ":" not in s:
        return None
    name, _, rest = s.partition(":")
    name, rest = name.strip(), rest.strip()
    if not name or not rest:
        return None
    slots: list[tuple[int, int]] = []
    for tok in rest.split(","):
        tok = tok.strip()
        if not tok:
            continue
        parts = tok.split("_")
        if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
            return None
        slots.append((int(parts[0]), int(parts[1])))
    if not slots:
        return None
    return name, slots
