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
def test_replay_and_live_tools_ignore_subkind(kind):
    # Replay (Item 30) and Live (Item 35) are read-only top-level modes.
    assert effective_mode("Replay", kind) == "Replay"
    assert effective_mode("Live", kind) == "Live"


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
