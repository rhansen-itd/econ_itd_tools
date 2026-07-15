"""Overlay review labeling — hand-labeled stitching observations from the GUI.

2026-07-14 round (the owner's request following Item 44): the ground-truth
observation set that drives fusion-engine improvement was hand-transcribed
from watching replays; this module lets the owner author those labels *in*
the replay overlay instead — click markers to select raw tracks, commit the
selection as a group with a kind, and save straight into the observations
JSON schema that ``tests/fixtures/stitch_observations_2026-07-13.json``
established and ``scripts/fusion_eval.py`` scores. One file format end to
end, so every review session grows the acceptance set.

Kinds mirror the fixture's semantics (owner's words, quoted there):

* ``handoff``     — different sensors' views of one object → must fuse.
* ``persistence`` — one sensor dropped and re-acquired the object → must fuse.
* ``anchor``      — persisted correctly under one id through a long stop;
                    must not absorb any same-sensor neighbour.
* ``stray``       — not a genuine object (interference / shadow); must not
                    merge into any genuine group.
* ``bad_pair``    — the inverse of handoff/persistence (Item 47): these members
                    are *distinct* objects the engine over-merged, so they must
                    **not** all land in one fused id. Authored by clicking an
                    over-merged fused marker in the fused overlay (its
                    ``FusedTrack.members`` become the selection); scored pass
                    when they end up in ≥2 distinct fused ids.

``ped`` and ``unsure`` are per-group flags, ``note`` free text, and
``same_sensor`` is derived from the members rather than asked for. Multi-track
kinds (handoff/persistence, and bad_pair) need at least two members; anchor and
stray label a single track (more are allowed — the fixture has multi-member
strays).

Pure Python, no GUI imports, pytest-testable headless like the rest of
``model/``. The GUI owns click hit-testing (it lives in canvas space); this
module owns the selection/group state and the (de)serialization.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

Member = tuple[int, int]  # (sensor, oid) — a raw track key, as in fusion

KINDS = ("handoff", "persistence", "anchor", "stray", "bad_pair")
# kinds that describe two-or-more tracks and so need at least two members —
# handoff/persistence (must fuse) and bad_pair (must NOT all fuse), Item 47.
_MULTI_KINDS = ("handoff", "persistence", "bad_pair")


@dataclass(frozen=True)
class ReviewGroup:
    """One labeled observation: a set of raw tracks plus what they mean."""

    kind: str
    members: tuple[Member, ...]
    ped: bool = False
    unsure: bool = False
    note: str = ""

    @property
    def same_sensor(self) -> bool:
        """The fixture's ``same_sensor`` marker: every member shares one
        slot, so the mechanism is within-sensor stitching whatever the kind
        says (only meaningful for multi-member groups)."""
        return len(self.members) > 1 and len({s for s, _ in self.members}) == 1

    def to_json(self) -> dict:
        """Fixture-style entry: optional keys present only when set."""
        d: dict = {"kind": self.kind}
        if self.same_sensor:
            d["same_sensor"] = True
        if self.unsure:
            d["unsure"] = True
        if self.ped:
            d["ped"] = True
        d["members"] = [list(m) for m in self.members]
        if self.note:
            d["note"] = self.note
        return d

    @classmethod
    def from_json(cls, d: dict) -> "ReviewGroup":
        return cls(
            kind=d["kind"],
            members=tuple((int(s), int(o)) for s, o in d["members"]),
            ped=bool(d.get("ped", False)),
            unsure=bool(d.get("unsure", False)),
            note=str(d.get("note", "")))


@dataclass
class ReviewSession:
    """Selection + labeled groups for one capture, GUI-agnostic.

    ``capture``/``recording``/``iprj_candidates`` seed the observations
    schema so the saved file is directly loadable by the eval harness."""

    capture: str = ""
    recording: str = ""
    iprj_candidates: list[str] = field(default_factory=list)
    groups: list[ReviewGroup] = field(default_factory=list)
    selection: list[Member] = field(default_factory=list)

    # -- selection -----------------------------------------------------------

    def toggle(self, member: Member) -> bool:
        """Select/deselect a raw track; returns True when now selected.
        Order of first selection is kept — the owner lists members in the
        order the object moved through the sensors."""
        if member in self.selection:
            self.selection.remove(member)
            return False
        self.selection.append(member)
        return True

    def clear_selection(self) -> None:
        self.selection.clear()

    def is_selected(self, member: Member) -> bool:
        return member in self.selection

    # -- groups ---------------------------------------------------------------

    def commit(self, kind: str, *, ped: bool = False, unsure: bool = False,
               note: str = "") -> ReviewGroup:
        """Turn the current selection into a labeled group (and clear it).
        Raises ValueError on an unknown kind, an empty selection, or a
        multi-track kind with a single member — refuse, don't guess, as
        everywhere."""
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r} (one of {KINDS})")
        if not self.selection:
            raise ValueError("nothing selected — click markers first")
        if kind in _MULTI_KINDS and len(self.selection) < 2:
            raise ValueError(
                f"a {kind} group needs at least two tracks "
                f"({len(self.selection)} selected)")
        g = ReviewGroup(kind=kind, members=tuple(self.selection),
                        ped=ped, unsure=unsure, note=note)
        self.groups.append(g)
        self.selection.clear()
        return g

    def remove(self, index: int) -> ReviewGroup:
        return self.groups.pop(index)

    def labeled_members(self) -> set[Member]:
        return {m for g in self.groups for m in g.members}

    # -- observations-schema (de)serialization ---------------------------------

    def to_json(self) -> dict:
        """The single-capture observations document the eval harness reads —
        same shape as tests/fixtures/stitch_observations_2026-07-13.json."""
        return {
            "_comment": [
                "Stitching observations labeled in the iprj Designer replay "
                "overlay (Overlay > Replay > review).",
                "Schema and kind semantics follow "
                "tests/fixtures/stitch_observations_2026-07-13.json; "
                "scored by scripts/fusion_eval.py --obs <this file>.",
            ],
            "captures": {
                self.capture or "capture": {
                    "recording": self.recording,
                    "iprj_candidates": list(self.iprj_candidates),
                    "groups": [g.to_json() for g in self.groups],
                }
            },
        }

    @classmethod
    def from_json(cls, data: dict) -> "ReviewSession":
        """Load a (single-capture) observations document; a multi-capture
        file loads its first capture — review edits one recording at a time."""
        captures = data.get("captures", {})
        if not captures:
            return cls()
        name, entry = next(iter(captures.items()))
        return cls(
            capture=name,
            recording=str(entry.get("recording", "")),
            iprj_candidates=[str(c) for c in entry.get("iprj_candidates", [])],
            groups=[ReviewGroup.from_json(g)
                    for g in entry.get("groups", [])])

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_json(), indent=1) + "\n")

    @classmethod
    def load(cls, path: Path) -> "ReviewSession":
        return cls.from_json(json.loads(path.read_text()))


def observations_path(recording_path: Path) -> Path:
    """The sidecar the GUI saves to / resumes from, beside the recording:
    ``10_37_64_32_EVO_....txt.gz`` → ``10_37_64_32_EVO_....observations.json``.
    Deterministic so a re-opened recording finds its labels again."""
    name = recording_path.name
    for suffix in (".txt.gz", ".txt"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return recording_path.with_name(name + ".observations.json")
