"""Toolbar mode + owner-dropdown projection logic (ROADMAP Item 24).

These are the pure decision helpers the GUI wires: effective_mode() derives the
state-machine mode from the tool toggle + Draw sub-kind (Sensor/Centerline are
sub-kinds now, not top-level tools), and general_offered() gates whether the
unified Owner/Sensor dropdown offers "General"."""

import pytest

from gui.app import effective_mode, general_offered


# ---------------------------------------------------------------------------
# effective_mode — tool + sub-kind -> state-machine mode
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", [
    "Event Zone", "Ignore Zone", "Lineal", "Text Label", "Centerline", "Sensor"])
def test_edit_tool_is_edit_regardless_of_subkind(kind):
    assert effective_mode("Edit", kind) == "Edit"


@pytest.mark.parametrize("kind", ["Event Zone", "Centerline", "Sensor"])
def test_background_tool_is_background_regardless_of_subkind(kind):
    assert effective_mode("Background", kind) == "Background"


@pytest.mark.parametrize("kind", ["Event Zone", "Centerline", "Sensor"])
def test_overlay_tool_resolves_to_its_subkind_ignoring_draw_subkind(kind):
    # Record/Replay/Live (Items 31/30/35) are siblings under one "Overlay"
    # top-level tool now (Item 37); the Overlay sub-kind IS the effective
    # mode, regardless of whatever the (irrelevant, hidden) Draw sub-kind is.
    assert effective_mode("Overlay", kind, "Record") == "Record"
    assert effective_mode("Overlay", kind, "Replay") == "Replay"
    assert effective_mode("Overlay", kind, "Live") == "Live"
    # Align (Item 40) is the fourth Overlay sub-kind — an interactive-alignment
    # mode, resolved the same sub-kind-is-the-mode way as the other three.
    assert effective_mode("Overlay", kind, "Align") == "Align"


def test_overlay_tool_defaults_to_replay_subkind():
    # The overlay_kind_val default mirrors the toolbar's initial toggle value.
    assert effective_mode("Overlay", "Event Zone") == "Replay"


@pytest.mark.parametrize("kind,mode", [
    ("Event Zone", "Draw"),
    ("Ignore Zone", "Draw"),
    ("Lineal", "Draw"),
    ("Text Label", "Draw"),
    ("Centerline", "Centerline"),  # folded sub-kind gets its own mode
    ("Sensor", "Sensor"),
])
def test_draw_tool_resolves_folded_subkinds(kind, mode):
    assert effective_mode("Draw", kind) == mode


# ---------------------------------------------------------------------------
# general_offered — when the Owner/Sensor dropdown offers "General"
# ---------------------------------------------------------------------------

def test_general_offered_for_owned_draw_kinds():
    assert general_offered("Draw", "Lineal")
    assert general_offered("Draw", "Text Label")


def test_general_not_offered_for_zone_kinds():
    assert not general_offered("Draw", "Event Zone")
    assert not general_offered("Draw", "Ignore Zone")


def test_general_offered_for_centerline():
    assert general_offered("Centerline", "Event Zone")  # draw_kind is stale here


def test_general_not_offered_for_edit_sensor_or_background():
    # Edit only scopes the active sensor; it never sets an owner.
    assert not general_offered("Edit", "Event Zone")
    assert not general_offered("Sensor", "Event Zone")
    assert not general_offered("Background", "Lineal")
