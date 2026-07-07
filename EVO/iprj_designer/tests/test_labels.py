"""Band-scoped text-label persistence (ROADMAP Item 21, model/labels.py)."""

from model.bands import Owner
from model.iprj_io import Project, TextLabel, load_iprj, save_iprj
from model.labels import (
    DISABLED_POSITION,
    NAME_LABEL_TOL,
    is_name_label,
    load_labels,
    load_labels_owned,
    match_name_labels,
    save_labels,
    save_labels_owned,
)


def placeholder() -> TextLabel:
    return TextLabel(enable=0, text="",
                     position_x=DISABLED_POSITION, position_y=DISABLED_POSITION)


def full_array() -> list[TextLabel]:
    """A vendor-style 100-slot disabled placeholder array."""
    return [placeholder() for _ in range(100)]


def label(text: str, x: float = 1.0, y: float = 2.0) -> TextLabel:
    # Vendor default styling for a new label (FontSize 12, white).
    return TextLabel(enable=1, text=text, position_x=x, position_y=y,
                     font_size=12, textcolor_red=255, textcolor_green=255,
                     textcolor_blue=255)


# ---------------------------------------------------------------------------
# Owner inference on load
# ---------------------------------------------------------------------------

def test_load_labels_owned_infers_band():
    labels = full_array()
    labels[0] = label("general")
    labels[25] = label("s1s2")
    labels[70] = label("s3s4")
    owned = load_labels_owned(Project(text_labels=labels))
    assert [(o, l.text) for o, l in owned] == [
        (Owner.GENERAL, "general"), (Owner.FILE1, "s1s2"), (Owner.FILE2, "s3s4")]


def test_load_labels_skips_disabled_and_deep_copies():
    labels = full_array()
    labels[3] = label("keep")
    project = Project(text_labels=labels)
    loaded = load_labels(project)
    assert [l.text for l in loaded] == ["keep"]
    loaded[0].text = "mutated"
    assert project.text_labels[3].text == "keep"  # working copy, no aliasing


# ---------------------------------------------------------------------------
# Save into bands
# ---------------------------------------------------------------------------

def test_save_labels_owned_places_in_bands():
    project = Project(text_labels=full_array())
    assert save_labels_owned(project, [
        (Owner.GENERAL, label("g")),
        (Owner.FILE1, label("a")),
        (Owner.FILE2, label("b")),
    ]) == []
    assert project.text_labels[0].text == "g"
    assert project.text_labels[20].text == "a"
    assert project.text_labels[60].text == "b"
    # everything else stays a disabled placeholder
    used = {0, 20, 60}
    assert all(not l.enable for i, l in enumerate(project.text_labels) if i not in used)


def test_save_labels_wrapper_is_general_band():
    project = Project(text_labels=full_array())
    save_labels(project, [label("x"), label("y")])
    assert project.text_labels[0].text == "x"
    assert project.text_labels[1].text == "y"
    assert load_labels_owned(project) == load_labels_owned(project)
    assert all(o == Owner.GENERAL for o, _ in load_labels_owned(project))


def test_save_labels_full_replace():
    project = Project(text_labels=full_array())
    save_labels_owned(project, [(Owner.FILE1, label("first"))])
    save_labels_owned(project, [(Owner.FILE1, label("second"))])
    owned = load_labels_owned(project)
    assert [(o, l.text) for o, l in owned] == [(Owner.FILE1, "second")]
    save_labels_owned(project, [])
    assert load_labels(project) == []


def test_save_labels_owned_overflow_is_returned():
    project = Project(text_labels=full_array())
    many = [(Owner.GENERAL, label(f"n{i}")) for i in range(21)]  # band holds 20
    skipped = save_labels_owned(project, many)
    assert len(skipped) == 1 and skipped[0].text == "n20"
    assert sum(1 for l in project.text_labels if l.enable) == 20


def test_disabled_slots_park_at_sentinel():
    project = Project(text_labels=full_array())
    save_labels_owned(project, [(Owner.GENERAL, label("only"))])
    parked = [l for l in project.text_labels if not l.enable]
    assert parked and all(l.position_x == DISABLED_POSITION for l in parked)


# ---------------------------------------------------------------------------
# Through the .iprj file
# ---------------------------------------------------------------------------

def test_file_roundtrip_preserves_bands_and_styling(tmp_path):
    project = Project(text_labels=full_array())
    save_labels_owned(project, [
        (Owner.GENERAL, label("g", x=5.0, y=6.0)),
        (Owner.FILE2, label("f2", x=7.0, y=8.0)),
    ])
    path = tmp_path / "labels.iprj"
    save_iprj(project, path)
    owned = load_labels_owned(load_iprj(path))
    assert [(o, l.text, l.font_size, l.textcolor_red) for o, l in owned] == [
        (Owner.GENERAL, "g", 12, 255), (Owner.FILE2, "f2", 12, 255)]


# ---------------------------------------------------------------------------
# Centerline-name label association (ROADMAP Item 22)
# ---------------------------------------------------------------------------

def named(text: str, x: float, y: float, rotation: float = 0.0) -> TextLabel:
    lbl = label(text, x, y)
    lbl.rotation_angle = rotation
    return lbl


def test_is_name_label_needs_enabled_and_unrotated():
    assert is_name_label(named("N", 0, 0))
    assert not is_name_label(named("N", 0, 0, rotation=90.0))
    disabled = named("N", 0, 0)
    disabled.enable = 0
    assert not is_name_label(disabled)


def test_match_associates_label_at_far_end():
    far_ends = [(100.0, 50.0)]
    labels = [named("N_CL", 100.0, 50.0)]
    assert match_name_labels(far_ends, labels) == {0: 0}


def test_match_ignores_rotated_and_distant_labels():
    far_ends = [(100.0, 50.0)]
    labels = [named("rotated", 100.0, 50.0, rotation=45.0),
              named("far", 100.0 + 10 * NAME_LABEL_TOL, 50.0)]
    assert match_name_labels(far_ends, labels) == {}


def test_match_is_one_to_one_and_nearest_wins():
    # Two centerlines whose far ends nearly coincide, two candidate labels:
    # each centerline takes its nearest, each label used once.
    far_ends = [(0.0, 0.0), (0.02, 0.0)]
    labels = [named("A", 0.021, 0.0), named("B", 0.001, 0.0)]
    # B is nearest to cl 0 (d=0.001) and A nearest to cl 1 (d=0.001)
    assert match_name_labels(far_ends, labels) == {0: 1, 1: 0}


def test_match_skips_centerline_without_geometry():
    assert match_name_labels([None, (5.0, 5.0)], [named("X", 5.0, 5.0)]) == {1: 0}
