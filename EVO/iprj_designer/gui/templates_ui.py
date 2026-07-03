"""iprj Designer — approach-template editor (Session 6.1).

Minimal NiceGUI form for creating/editing approach-template JSON files
(model/templates.py): name, design speed, lane configuration, detector
toggles, starting input/output, approach direction, thru/LT phase. Template
management stays lightweight this session — pick a file, edit the form,
save; no expansion/placement logic (that's Session 6.2/6.3), and no
duplicate/rename workflow (edit the JSON file directly for that).

Usage:
    python gui/templates_ui.py [template.json] [--port 8081]

Defaults to a blank template. Existing files under templates/ are listed in
the "Open" dropdown.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nicegui import ui

from model.templates import (DIRECTIONS, MOVEMENT_CHARS, ApproachTemplate,
                             Lane, lane_config_str, load_template,
                             save_template)

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"


def build_ui(template: ApproachTemplate, path: Path | None) -> None:
    state = {"path": path}
    lane_rows: list[dict] = []

    def template_files() -> dict[str, str]:
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        return {str(p): p.name for p in sorted(TEMPLATES_DIR.glob("*.json"))}

    def set_title():
        label = state["path"].name if state["path"] else "(new, unsaved)"
        title.set_text(f"Approach template — {label}")

    def refresh_preview():
        try:
            lanes = [Lane(r["movement"].value, float(r["width"].value or 0),
                          bool(r["advance"].value)) for r in lane_rows]
            preview.set_text(lane_config_str(lanes))
        except ValueError as e:
            preview.set_text(f"invalid: {e}")

    def add_lane_row(lane: Lane):
        with lanes_col, ui.row().classes("items-center gap-2") as row_el:
            entry = {
                "movement": ui.input("movement", value=lane.movement,
                                     placeholder="L / T / R / TR ...",
                                     on_change=lambda: refresh_preview()) \
                    .classes("w-24"),
                "width": ui.number("width (ft)", value=lane.width_ft, min=1,
                                  precision=1,
                                  on_change=lambda: refresh_preview()) \
                    .classes("w-28"),
                "advance": ui.checkbox("advance detector",
                                       value=lane.advance_detector),
            }
            ui.button(icon="delete",
                      on_click=lambda e=entry, r=row_el:
                      (lane_rows.remove(e), lanes_col.remove(r),
                       refresh_preview())).props("flat dense")
        lane_rows.append(entry)
        refresh_preview()

    def load_form(t: ApproachTemplate):
        name.value = t.name
        speed.value = t.speed_mph
        direction.value = t.direction
        count_loops.value = t.count_loops
        starting_input.value = t.starting_input
        starting_output.value = t.starting_output
        thru_phase.value = t.thru_phase
        lt_phase.value = t.lt_phase
        lanes_col.clear()
        lane_rows.clear()
        for lane in t.lanes:
            add_lane_row(lane)
        refresh_preview()

    def collect_form() -> ApproachTemplate:
        lanes = [Lane(r["movement"].value, float(r["width"].value or 0),
                      bool(r["advance"].value)) for r in lane_rows]
        return ApproachTemplate(
            name=name.value or "New approach",
            speed_mph=float(speed.value or 0),
            lanes=lanes,
            count_loops=bool(count_loops.value),
            starting_input=int(starting_input.value or 0),
            starting_output=int(starting_output.value or 0),
            direction=direction.value,
            thru_phase=int(thru_phase.value or 0),
            lt_phase=int(lt_phase.value or 0),
        )

    def new_template():
        state["path"] = None
        load_form(ApproachTemplate())
        set_title()

    def do_load(file_path: str):
        if not file_path:
            return
        try:
            t = load_template(file_path)
        except (ValueError, OSError) as e:
            ui.notify(f"failed to load: {e}", type="negative")
            return
        state["path"] = Path(file_path)
        load_form(t)
        set_title()
        ui.notify(f"loaded {state['path'].name}")

    def do_save(dest: Path):
        try:
            t = collect_form()
        except ValueError as e:
            ui.notify(f"cannot save: {e}", type="negative")
            return
        save_template(t, dest)
        state["path"] = dest
        set_title()
        open_select.set_options(template_files(), value=str(dest))
        ui.notify(f"saved {dest}")

    def save():
        if state["path"] is None:
            save_as()
        else:
            do_save(state["path"])

    def save_as():
        stem = (name.value or "template").lower().replace(" ", "_")
        default = state["path"] or (TEMPLATES_DIR / f"{stem}.json")
        with ui.dialog() as dialog, ui.card():
            ui.label("Save template as:")
            path_in = ui.input("path", value=str(default)) \
                .style("min-width: 420px")

            def apply():
                p = Path(path_in.value).expanduser()
                if p.suffix.lower() != ".json":
                    p = p.with_suffix(".json")
                dialog.close()
                do_save(p)

            with ui.row():
                ui.button("Save", on_click=apply)
                ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    # -- layout --------------------------------------------------------------

    with ui.row().classes("w-full items-center gap-2 px-2"):
        title = ui.label("").classes("text-lg")
        ui.space()
        open_select = ui.select(template_files(), label="Open",
                                on_change=lambda e: do_load(e.value)) \
            .classes("w-64").props("dense clearable")
        ui.button("New", on_click=new_template).props("flat dense")
        ui.button("Save", on_click=save).props("flat dense")
        ui.button("Save As…", on_click=save_as).props("flat dense")

    with ui.card().classes("w-full max-w-3xl mx-auto"):
        with ui.row().classes("w-full items-center"):
            name = ui.input("Name").classes("grow")
        with ui.row().classes("items-center gap-4"):
            speed = ui.number("Speed (mph)", min=0, precision=0).classes("w-32")
            direction = ui.select(list(DIRECTIONS),
                                  label="Approach direction").classes("w-40")
            with direction:
                ui.tooltip('compass side of the intersection this approach '
                           'is on, e.g. "N" = north approach (SB traffic)')
            count_loops = ui.checkbox("Count loops")
        with ui.row().classes("items-center gap-4"):
            starting_input = ui.number("Starting input #", min=0,
                                       precision=0).classes("w-40")
            starting_output = ui.number("Starting output #", min=0,
                                        precision=0).classes("w-40")
        with ui.row().classes("items-center gap-4"):
            thru_phase = ui.number("Thru phase", min=0, precision=0).classes("w-32")
            lt_phase = ui.number("LT phase", min=0, precision=0).classes("w-32")

        ui.separator()
        with ui.row().classes("w-full items-center"):
            ui.label("Lanes").classes("text-base")
            ui.button("Add lane", on_click=lambda: add_lane_row(Lane("T")))
        ui.label(f"movement letters: one or more of {list(MOVEMENT_CHARS)} "
                 "(e.g. L, T, TR)").classes("text-xs text-gray-500")
        lanes_col = ui.column().classes("w-full gap-0")
        preview = ui.label("").classes("text-sm font-mono text-gray-400")

    load_form(template)
    set_title()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", nargs="?", type=Path, help="template JSON to open")
    ap.add_argument("--port", type=int, default=8081)
    args = ap.parse_args()

    template = load_template(args.path) if args.path else ApproachTemplate()
    build_ui(template, args.path)
    ui.run(port=args.port, title="Approach Template Editor", reload=False,
           show=False, dark=True)


if __name__ in {"__main__", "__mp_main__"}:
    main()
