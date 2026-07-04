"""iprj Designer — approach-template editor (Session 6.1, Phase 4.2 grid).

NiceGUI form for creating/editing approach-template JSON files
(model/templates.py): name, design speed, extension time, lane
configuration, detector toggles, base output, approach direction, thru/LT
phase. Direction/phase/base-output fields left blank are saved as
placeholders (prompted at placement — Phase 4.3).

Phase 4.2 adds a Detectors grid below the lane list: one CSS Grid whose
columns are the template's physical lanes, so each detector row's editable
cell is placed under the lane(s) it spans (`grid-column` start/span from
`spanning_lanes`) — a row spanning lanes 1-2 visibly merges those two
columns. "Seed from kinematics" materializes `seed_detectors()`'s ITE
defaults into editable rows; nothing here recomputes them afterward — a
row's stored length/setback/output-offset/phase fully replaces the seeded
value once edited (Phase 4.1's "seed, don't constrain").
Template management stays lightweight — pick a file, edit the form, save;
no duplicate/rename workflow (edit the JSON file directly for that).

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

from model.templates import (DETECTOR_KINDS, DIRECTIONS, MOVEMENT_CHARS,
                             ApproachTemplate, Lane, TemplateDetector,
                             lane_config_str, load_template, save_template,
                             seed_detectors)

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"


def build_ui(template: ApproachTemplate, path: Path | None) -> None:
    state = {"path": path}
    lane_rows: list[dict] = []
    detector_rows: list[dict] = []  # plain-dict rows backing the grid (Phase 4.2)

    def template_files() -> dict[str, str]:
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        return {str(p): p.name for p in sorted(TEMPLATES_DIR.glob("*.json"))}

    def set_title():
        label = state["path"].name if state["path"] else "(new, unsaved)"
        title.set_text(f"Approach template — {label}")

    def current_lanes() -> list[Lane]:
        return [Lane(r["movement"].value, float(r["width"].value or 0),
                     bool(r["advance"].value)) for r in lane_rows]

    def refresh_preview():
        try:
            preview.set_text(lane_config_str(current_lanes()))
        except ValueError as e:
            preview.set_text(f"invalid: {e}")
        render_detectors()  # lane count/labels/widths feed the grid columns

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

    # -- Phase 4.2: detector grid ---------------------------------------------
    # One CSS Grid container: column 1 is the row header (kind/span/phase/
    # output-offset/delete), columns 2..n+1 are the template's physical
    # lanes. A row's value cell is placed with `grid-column: start / span
    # count` from its span, so a row spanning lanes 1-2 visibly merges those
    # two lane columns. `detector_rows` holds plain dicts (not tied to the ui
    # elements), so any structural change just clears and rebuilds the grid.

    def row_from_detector(det: TemplateDetector) -> dict:
        return {"kind": det.kind, "span_from": det.spanning_lanes[0],
                "span_to": det.spanning_lanes[-1], "length_ft": det.length_ft,
                "setback_ft": det.setback_ft, "output_offset": det.output_offset,
                "phase": str(det.phase)}

    def new_detector_row() -> dict:
        return {"kind": "count", "span_from": 0, "span_to": 0,
                "length_ft": 5.0, "setback_ft": 0.0,
                "output_offset": len(detector_rows), "phase": "thru"}

    def grid_columns_css() -> str:
        cols = ["200px"]
        for r in lane_rows:
            try:
                weight = max(float(r["width"].value or 12.0) / 12.0, 0.5)
            except (TypeError, ValueError):
                weight = 1.0
            cols.append(f"minmax(120px, {weight:.2f}fr)")
        return " ".join(cols) if lane_rows else "200px 1fr"

    def set_span(row: dict, key: str, value) -> None:
        try:
            v = int(value)
        except (TypeError, ValueError):
            return
        n_lanes = max(len(lane_rows), 1)
        row[key] = min(max(v, 0), n_lanes - 1)
        if row["span_from"] > row["span_to"]:
            row["span_to" if key == "span_from" else "span_from"] = row[key]
        render_detectors()

    def remove_detector_row(row: dict) -> None:
        detector_rows.remove(row)
        render_detectors()

    def add_detector_row() -> None:
        detector_rows.append(new_detector_row())
        render_detectors()

    def do_seed() -> None:
        try:
            temp = ApproachTemplate(
                lanes=current_lanes(), speed_mph=float(speed.value or 0),
                extension_time_s=float(extension.value or 1.0),
                count_loops=bool(count_loops.value))
        except ValueError as e:
            ui.notify(f"fix the lanes/speed first: {e}", type="negative")
            return
        detector_rows.clear()
        detector_rows.extend(row_from_detector(d) for d in seed_detectors(temp))
        render_detectors()
        ui.notify(f"seeded {len(detector_rows)} detector row(s) from kinematics")

    def seed_from_kinematics() -> None:
        if not detector_rows:
            do_seed()
            return
        with ui.dialog() as dialog, ui.card():
            ui.label("Replace all detector rows with fresh kinematic defaults? "
                     "Existing edits will be lost.")
            with ui.row():
                ui.button("Replace", on_click=lambda: (dialog.close(), do_seed()))
                ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    def render_detectors() -> None:
        n_lanes = max(len(lane_rows), 1)
        for row in detector_rows:  # reclamp in case a lane was deleted
            row["span_from"] = min(max(row["span_from"], 0), n_lanes - 1)
            row["span_to"] = min(max(row["span_to"], row["span_from"]), n_lanes - 1)
        detectors_grid.clear()
        with detectors_grid:
            detectors_grid.style("display:grid; gap:4px; align-items:stretch; "
                                 f"grid-template-columns:{grid_columns_css()};")
            ui.label("Detector").classes("text-xs text-gray-500 self-center") \
                .style("grid-column:1; grid-row:1;")
            for i, r in enumerate(lane_rows):
                ui.label(f"Lane {i + 1}: {r['movement'].value or '?'}") \
                    .classes("text-xs text-gray-500 text-center self-center") \
                    .style(f"grid-column:{i + 2}; grid-row:1;")
            for ri, row in enumerate(detector_rows):
                grid_row = ri + 2
                with ui.column().classes("gap-1 p-2 bg-grey-9 rounded") \
                        .style(f"grid-column:1; grid-row:{grid_row};"):
                    kind_opts = list(dict.fromkeys([*DETECTOR_KINDS, row["kind"]]))
                    ui.select(kind_opts, value=row["kind"], with_input=True,
                             new_value_mode="add-unique",
                             on_change=lambda e, row=row:
                             row.__setitem__("kind", e.value)).props("dense")
                    with ui.row().classes("items-center gap-1"):
                        ui.label("lanes").classes("text-xs text-gray-500")
                        ui.number(value=row["span_from"], min=0, max=n_lanes - 1,
                                 precision=0,
                                 on_change=lambda e, row=row:
                                 set_span(row, "span_from", e.value)) \
                            .classes("w-14").props("dense")
                        ui.label("-").classes("text-xs")
                        ui.number(value=row["span_to"], min=0, max=n_lanes - 1,
                                 precision=0,
                                 on_change=lambda e, row=row:
                                 set_span(row, "span_to", e.value)) \
                            .classes("w-14").props("dense")
                    with ui.row().classes("items-center gap-1"):
                        ui.input("phase", value=row["phase"],
                                 placeholder='thru / lt / #',
                                 on_change=lambda e, row=row:
                                 row.__setitem__("phase", e.value)) \
                            .classes("w-20").props("dense")
                        ui.number("out +", value=row["output_offset"], min=0,
                                 precision=0,
                                 on_change=lambda e, row=row: row.__setitem__(
                                     "output_offset", int(e.value or 0))) \
                            .classes("w-16").props("dense")
                        ui.button(icon="delete",
                                 on_click=lambda row=row: remove_detector_row(row)) \
                            .props("flat dense size=sm")
                span_count = row["span_to"] - row["span_from"] + 1
                with ui.card().classes("p-2").style(
                        f"grid-column:{row['span_from'] + 2} / span {span_count}; "
                        f"grid-row:{grid_row}; background:#173017; "
                        "border:1px solid #2ca02c;"):
                    with ui.row().classes("items-center gap-2 w-full"):
                        ui.number("length (ft)", value=row["length_ft"], min=0.1,
                                 precision=1,
                                 on_change=lambda e, row=row: row.__setitem__(
                                     "length_ft", float(e.value or 0))) \
                            .classes("w-28").props("dense")
                        ui.number("setback (ft)", value=row["setback_ft"],
                                 precision=1,
                                 on_change=lambda e, row=row: row.__setitem__(
                                     "setback_ft", float(e.value or 0))) \
                            .classes("w-28").props("dense")

    def _parse_phase(value: str) -> int | str:
        v = (value or "").strip()
        if v in ("thru", "lt"):
            return v
        try:
            return int(v)
        except ValueError:
            raise ValueError(f'phase must be "thru", "lt", or an integer, '
                             f"got {value!r}") from None

    def collect_detectors() -> list[TemplateDetector]:
        rows = []
        for i, row in enumerate(detector_rows):
            try:
                rows.append(TemplateDetector(
                    kind=row["kind"] or "count",
                    spanning_lanes=list(range(row["span_from"], row["span_to"] + 1)),
                    length_ft=float(row["length_ft"] or 0),
                    setback_ft=float(row["setback_ft"] or 0),
                    output_offset=int(row["output_offset"] or 0),
                    phase=_parse_phase(row["phase"])))
            except ValueError as e:
                raise ValueError(f"detector row {i + 1} ({row['kind']}): {e}") from None
        return rows

    def load_form(t: ApproachTemplate):
        name.value = t.name
        speed.value = t.speed_mph
        extension.value = t.extension_time_s
        direction.value = t.direction
        count_loops.value = t.count_loops
        base_output.value = t.base_output
        thru_phase.value = t.thru_phase
        lt_phase.value = t.lt_phase
        lanes_col.clear()
        lane_rows.clear()
        for lane in t.lanes:
            add_lane_row(lane)
        detector_rows.clear()
        detector_rows.extend(row_from_detector(d) for d in t.detectors)
        refresh_preview()

    def collect_form() -> ApproachTemplate:
        lanes = current_lanes()

        def opt_int(el):  # blank = placeholder (prompt at placement)
            return int(el.value) if el.value is not None else None

        return ApproachTemplate(
            name=name.value or "New approach",
            speed_mph=float(speed.value or 0),
            extension_time_s=float(extension.value or 1.0),
            lanes=lanes,
            count_loops=bool(count_loops.value),
            base_output=opt_int(base_output),
            direction=direction.value or None,
            thru_phase=opt_int(thru_phase),
            lt_phase=opt_int(lt_phase),
            detectors=collect_detectors(),
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
            extension = ui.number("Extension (s)", min=0.1, step=0.1,
                                  precision=1).classes("w-32")
            with extension:
                ui.tooltip("detection-channel extension assumed when seeding "
                           "the continuous-coverage advance chain")
            direction = ui.select(list(DIRECTIONS),
                                  label="Approach direction") \
                .classes("w-40").props("clearable")
            with direction:
                ui.tooltip('compass side of the intersection this approach '
                           'is on, e.g. "N" = north approach (SB traffic)')
            count_loops = ui.checkbox("Count loops")
        with ui.row().classes("items-center gap-4"):
            base_output = ui.number("Base output #", min=0,
                                    precision=0).classes("w-40")
            thru_phase = ui.number("Thru phase", min=0, precision=0).classes("w-32")
            lt_phase = ui.number("LT phase", min=0, precision=0).classes("w-32")
        ui.label("blank direction/phase/output fields are prompted at "
                 "placement time").classes("text-xs text-gray-500")

        ui.separator()
        with ui.row().classes("w-full items-center"):
            ui.label("Lanes").classes("text-base")
            ui.button("Add lane", on_click=lambda: add_lane_row(Lane("T")))
        ui.label(f"movement letters: one or more of {list(MOVEMENT_CHARS)} "
                 "(e.g. L, T, TR)").classes("text-xs text-gray-500")
        lanes_col = ui.column().classes("w-full gap-0")
        preview = ui.label("").classes("text-sm font-mono text-gray-400")

    with ui.card().classes("w-full max-w-6xl mx-auto"):
        with ui.row().classes("w-full items-center"):
            ui.label("Detectors").classes("text-base")
            ui.space()
            ui.button("Add row", on_click=add_detector_row).props("flat dense")
            ui.button("Seed from kinematics", on_click=seed_from_kinematics) \
                .props("flat dense")
        ui.label("columns are the physical lanes above; a row's cell spans "
                 "the lanes it covers. Seeding fills rows with the ITE "
                 "kinematic defaults — edit any value to override it; "
                 "seeding never runs again on its own.") \
            .classes("text-xs text-gray-500")
        detectors_grid = ui.element("div").classes("w-full overflow-x-auto")

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
