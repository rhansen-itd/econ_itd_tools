"""Toolbar / layout mockups — ROADMAP Item 23 (planning, NOT wiring).

Runnable static mockups of the *consolidated* toolbar the Item 24/27 rework
builds toward: **Draw is the hub** (Sensor / Centerline / Template fold into
Draw sub-kinds), and the active-sensor selector + General/Active-sensor owner
toggle collapse into one **Owner/Sensor** dropdown.

    Option A — Two-tier consolidated  ← OWNER'S CHOICE (refined 2026-07-07)
    Option B — Single command bar      (kept for reference)
    Option C — Left tool rail          (kept for reference)

Option A carries the owner's grouping refinements: commands grouped by type with
`|` separators — modes (Draw/Edit/Background) top-left, permanent drawing tools
(snap/ruler/undo/layers/fit) next to them, the file cluster (folder · template
editor · filename · save) top-right with the filename beside Save, and the
zone-table Auto/On/Off control right-justified on row 2 above the table.

Nothing here talks to model/ or the real app — buttons are inert (a click just
notifies); the only live behaviour is flipping the tool / draw sub-kind so the
context bar reflows. Decision write-up: ITEM23_TOOLBAR_PLAN.md.

Run in the repo .venv:   python gui/toolbar_mockup.py   →  http://localhost:8081
(port 8081 so it never clashes with the real app on 8080)
"""
from nicegui import ui

# --- fake data (no model import — this is a static mockup) --------------------
SENSORS = ["S1", "S2", "S3", "S4"]
TEMPLATES = ["approach_4lane", "approach_2lane", "left_turn_only"]
CENTERLINES = ["N_CL", "S_CL", "E_CL", "W_CL"]
FILENAME = "banks_1_2.iprj + banks_3_4.iprj"

DRAW_KINDS = ["Event Zone", "Ignore Zone", "Lineal", "Text Label",
              "Centerline", "Sensor"]
ZONE_KINDS = {"Event Zone", "Ignore Zone"}   # General hidden — must own a sensor
OWNED_KINDS = {"Lineal", "Text Label", "Centerline"}  # General offered (both files)

# Colours to make the functional groups legible in the mockup only.
C_TOOL = "text-cyan-300"
C_KIND = "text-amber-300"
C_OWNER = "text-emerald-300"


def _inert(msg="mockup — not wired"):
    return lambda *_: ui.notify(msg, position="bottom")


def owner_options(kind: str) -> list[str]:
    """The unified Owner/Sensor dropdown's options for a given sub-kind.

    Zones + Sensor management must belong to a real sensor, so General is
    suppressed there; owned annotations (lineal/label/centerline) offer
    General (both-file band) plus each sensor's band.
    """
    if kind in OWNED_KINDS:
        return ["General"] + SENSORS
    return SENSORS  # Event Zone, Ignore Zone, Sensor


def owner_band_hint(value: str) -> str:
    if value == "General":
        return "→ both files"
    n = int(value[1:])
    return "→ _1_2" if n <= 2 else "→ _3_4"


def kind_extras(kind: str) -> None:
    """Per-sub-kind extra controls, inline. Shared by every option so only the
    *arrangement* differs between A/B/C — matching how Item 24's single
    `update_context_bar` will gate these by draw kind. Note the template EDITOR
    button is NOT here (owner moved it to the file cluster); only the template
    picker + placement-values button live in Event Zone."""
    if kind == "Event Zone":
        # Template placement is a subset of Event Zone (Item 27), plus the
        # unified CL dropdown that applies to *every* drawn zone.
        ui.select(TEMPLATES, label="template", clearable=True) \
            .props("dense clearable").classes("w-40")
        ui.select(CENTERLINES, label="along CL", clearable=True) \
            .props("dense clearable").classes("w-28")
        ui.button(icon="edit_note", on_click=_inert()).props("flat dense") \
            .tooltip("placement values")
    elif kind == "Text Label":
        ui.input("label text", value="Ph 4").props("dense").classes("w-32")
        ui.number("size", value=12).props("dense").classes("w-16")
        ui.number("rot°", value=0).props("dense").classes("w-16")
        ui.color_input("color", value="#ffffff").props("dense").classes("w-24")
        ui.checkbox("B").props("dense")
        ui.checkbox("I").props("dense")
    elif kind == "Centerline":
        ui.select(CENTERLINES, value="N_CL", label="centerline") \
            .props("dense").classes("w-28")
        ui.button(icon="add_road", on_click=_inert()).props("flat dense") \
            .tooltip("add centerline")
        ui.input("name", value="N_CL").props("dense clearable").classes("w-28")
    elif kind == "Sensor":
        ui.button(icon="add_circle", on_click=_inert()).props("flat dense") \
            .tooltip("add sensor")
        ui.button(icon="delete", on_click=_inert()).props("flat dense") \
            .tooltip("delete active sensor")
    # Ignore Zone + Lineal: no extras beyond the owner dropdown.


def owner_dropdown(kind: str):
    opts = owner_options(kind)
    default = opts[0]
    sel = ui.select(opts, value=default, label="owner / sensor") \
        .props("dense").classes(f"w-36 {C_OWNER}")
    hint = ui.label(owner_band_hint(default)).classes(
        f"font-mono text-xs {C_OWNER}")
    sel.on_value_change(lambda e: hint.set_text(owner_band_hint(e.value)))
    return sel


def drawing_tools() -> None:
    """Permanent drawing/canvas tools — available in every mode. Grouped
    together per the owner's call; the clear-ruler button rides with the ruler."""
    ui.switch("snap").props("dense")
    ui.button(icon="straighten", on_click=_inert()).props("flat dense") \
        .tooltip("ruler")
    ui.button(icon="clear", on_click=_inert()).props("flat dense") \
        .tooltip("clear ruler")
    ui.button(icon="undo", on_click=_inert()).props("flat dense").tooltip("undo")
    ui.button(icon="layers", on_click=_inert()).props("flat dense") \
        .tooltip("layers")
    ui.button(icon="fit_screen", on_click=_inert()).props("flat dense") \
        .tooltip("fit view")


def file_cluster() -> None:
    """Document/file commands, right-justified: template editor · folder menu ·
    filename · save. The folder icon sits next to the filename, and the filename
    next to Save (owner's calls); the template editor leads the cluster (moved
    out of the Event-Zone context bar)."""
    ui.button(icon="edit_square", on_click=_inert()).props("flat dense") \
        .tooltip("template editor (new tab)")
    with ui.button(icon="folder").props("flat dense") as b:
        b.tooltip("file")
        with ui.menu():
            ui.menu_item("New…", on_click=_inert())
            ui.menu_item("Open…", on_click=_inert())
            ui.menu_item("Open second pair (overlay)…", on_click=_inert())
            ui.separator()
            ui.menu_item("Save", on_click=_inert())
            ui.menu_item("Save As…", on_click=_inert())
    ui.label(FILENAME).classes("text-sm text-gray-300 whitespace-nowrap")
    ui.button(icon="save", on_click=_inert()).props("flat dense") \
        .tooltip("save (Ctrl-S)")


def zone_table_toggle() -> None:
    """Zone-table three-state (Auto / On / Off), right-justified on row 2 above
    the table (owner's call). Auto = show only when a zone kind is active."""
    with ui.button(icon="view_sidebar").props("flat dense") as b:
        b.tooltip("zone table: Auto / On / Off")
        with ui.menu():
            for opt in ("Auto (default)", "On", "Off"):
                ui.menu_item(opt, on_click=_inert())


def canvas(budget: str) -> None:
    """Stand-in for the drawing surface, sized to the option's height budget so
    the vertical trade-off between options is visible at a glance."""
    with ui.element("div").classes("w-full rounded overflow-hidden") \
            .style(f"height: {budget}; background:"
                   " repeating-linear-gradient(45deg,#161616,#161616 14px,"
                   "#1c1c1c 14px,#1c1c1c 28px); position: relative;"):
        ui.label(f"drawing canvas   ·   height budget = {budget}") \
            .classes("text-gray-500 text-sm absolute") \
            .style("top: 8px; left: 12px;")


def status_bar() -> None:
    with ui.row().classes("w-full justify-between px-2 pt-1"):
        ui.label("mode: draw · event zone").classes("text-white font-mono text-xs")
        ui.label("x: — · y: —").classes("text-white font-mono text-xs")
        ui.label("zoom 1.00×").classes("text-white font-mono text-xs")


# =============================================================================
# Option A — Two-tier consolidated  (OWNER'S CHOICE, refined)
# =============================================================================
def option_a() -> None:
    state = {"tool": "Draw", "kind": "Event Zone"}

    @ui.refreshable
    def context_row():
        with ui.row().classes("w-full items-center gap-2 no-wrap "
                              "overflow-x-auto px-2"):
            if state["tool"] == "Draw":
                kt = ui.toggle(DRAW_KINDS, value=state["kind"]).props("dense") \
                    .classes(C_KIND)
                kt.on_value_change(lambda e: (state.update(kind=e.value),
                                              context_row.refresh()))
                ui.separator().props("vertical")
                owner_dropdown(state["kind"])
                kind_extras(state["kind"])
            elif state["tool"] == "Edit":
                ui.label("2 selected").classes("font-mono text-white")
                for ic, tip in (("tune", "properties"), ("rotate_right", "rotate"),
                                ("timeline", "move along CL"), ("delete", "delete")):
                    ui.button(icon=ic, on_click=_inert()).props("flat dense") \
                        .tooltip(tip)
                ui.separator().props("vertical")
                owner_dropdown("Event Zone")
            else:  # Background
                ui.button(icon="aspect_ratio", on_click=_inert()) \
                    .props("flat dense").tooltip("calibrate by size")
                ui.button(icon="image", on_click=_inert()).props("flat dense") \
                    .tooltip("upload background")
            # Zone-table three-state, right-justified above the table.
            ui.space()
            ui.separator().props("vertical")
            zone_table_toggle()

    # Row 1 — modes (top-left) | permanent drawing tools … file cluster (top-right).
    with ui.row().classes("w-full items-center gap-2 no-wrap "
                          "overflow-x-auto px-2 pt-1"):
        tt = ui.toggle(["Draw", "Edit", "Background"], value="Draw") \
            .props("dense").classes(C_TOOL)
        tt.on_value_change(lambda e: (state.update(tool=e.value),
                                      context_row.refresh()))
        ui.separator().props("vertical")   # the "|" between groups
        drawing_tools()
        ui.space()
        ui.separator().props("vertical")
        file_cluster()

    # Row 2 — context bar.
    context_row()
    canvas("calc(100vh - 210px)")
    status_bar()


# =============================================================================
# Option B — Single command bar  (reference)
# =============================================================================
def option_b() -> None:
    state = {"tool": "Draw", "kind": "Event Zone"}

    @ui.refreshable
    def bar():
        with ui.row().classes("w-full items-center gap-2 no-wrap "
                              "overflow-x-auto px-2 pt-1"):
            tt = ui.toggle(["Draw", "Edit", "Background"], value=state["tool"]) \
                .props("dense").classes(C_TOOL)
            tt.on_value_change(lambda e: (state.update(tool=e.value),
                                          bar.refresh()))
            ui.separator().props("vertical")
            if state["tool"] == "Draw":
                # Sub-kind as a dropdown (not a segmented toggle) to reclaim width.
                kd = ui.select(DRAW_KINDS, value=state["kind"], label="draw") \
                    .props("dense").classes(f"w-32 {C_KIND}")
                kd.on_value_change(lambda e: (state.update(kind=e.value),
                                              bar.refresh()))
                owner_dropdown(state["kind"])
                kind_extras(state["kind"])
            elif state["tool"] == "Edit":
                ui.label("2 sel").classes("font-mono text-white")
                for ic, tip in (("tune", "properties"), ("rotate_right", "rotate"),
                                ("delete", "delete")):
                    ui.button(icon=ic, on_click=_inert()).props("flat dense") \
                        .tooltip(tip)
                owner_dropdown("Event Zone")
            else:
                ui.button(icon="aspect_ratio", on_click=_inert()) \
                    .props("flat dense").tooltip("calibrate")
                ui.button(icon="image", on_click=_inert()).props("flat dense") \
                    .tooltip("upload bg")
            ui.space()
            drawing_tools()
            ui.separator().props("vertical")
            file_cluster()
            zone_table_toggle()

    bar()
    canvas("calc(100vh - 180px)")   # one toolbar row → more canvas
    status_bar()


# =============================================================================
# Option C — Left tool rail  (reference)
# =============================================================================
def option_c() -> None:
    state = {"tool": "Draw", "kind": "Event Zone"}

    @ui.refreshable
    def context_row():
        with ui.row().classes("w-full items-center gap-2 no-wrap "
                              "overflow-x-auto px-2 pt-1"):
            if state["tool"] == "Draw":
                kt = ui.toggle(DRAW_KINDS, value=state["kind"]).props("dense") \
                    .classes(C_KIND)
                kt.on_value_change(lambda e: (state.update(kind=e.value),
                                              context_row.refresh()))
                owner_dropdown(state["kind"])
                kind_extras(state["kind"])
            elif state["tool"] == "Edit":
                ui.label("2 selected").classes("font-mono text-white")
                for ic, tip in (("tune", "props"), ("rotate_right", "rotate"),
                                ("delete", "delete")):
                    ui.button(icon=ic, on_click=_inert()).props("flat dense") \
                        .tooltip(tip)
                owner_dropdown("Event Zone")
            else:
                ui.button(icon="aspect_ratio", on_click=_inert()) \
                    .props("flat dense").tooltip("calibrate")
                ui.button(icon="image", on_click=_inert()).props("flat dense")
            ui.space()
            file_cluster()
            ui.separator().props("vertical")
            zone_table_toggle()

    with ui.row().classes("w-full no-wrap gap-0"):
        # Vertical rail: primary tools on top, drawing tools below.
        with ui.column().classes("items-center gap-1 py-2 px-1 bg-neutral-900"):
            rail = ui.toggle(["Draw", "Edit", "Background"], value="Draw") \
                .props("dense vertical").classes(C_TOOL)
            rail.on_value_change(lambda e: (state.update(tool=e.value),
                                            context_row.refresh()))
            ui.separator()
            drawing_tools()
        with ui.column().classes("grow gap-0"):
            context_row()
            canvas("calc(100vh - 150px)")   # tallest canvas of the three
            status_bar()


# =============================================================================
@ui.page("/")
def page():
    ui.query("body").style("background: #111;")
    with ui.column().classes("w-full gap-0"):
        ui.label("iprj Designer — toolbar consolidation mockups (Item 23)") \
            .classes("text-lg text-white px-3 pt-2")
        ui.label("Option A is the owner's chosen layout (refined). Flip Tool / "
                 "sub-kind to watch the context bar reflow. Cyan = tool · "
                 "amber = draw sub-kind · green = unified owner/sensor dropdown.") \
            .classes("text-xs text-gray-400 px-3")
        with ui.tabs().classes("w-full") as tabs:
            ta = ui.tab("A · Two-tier (chosen)")
            tb = ui.tab("B · Single bar")
            tc = ui.tab("C · Left rail")
        with ui.tab_panels(tabs, value=ta).classes("w-full").props("dark"):
            with ui.tab_panel(ta):
                option_a()
            with ui.tab_panel(tb):
                option_b()
            with ui.tab_panel(tc):
                option_c()


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(port=8081, title="Item 23 toolbar mockups", reload=False,
           show=False, dark=True)
