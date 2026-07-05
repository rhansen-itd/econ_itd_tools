"""iprj Designer — approach-template editor (Session 6.1, Phase 4.2 grid).

NiceGUI form for creating/editing approach-template JSON files
(model/templates.py): name, design speed, extension time, decision/advance
detector seed lengths, lane configuration, detector toggles, base output,
approach direction, thru/LT phase. Direction/phase/base-output fields left
blank are saved as placeholders (prompted at placement — Phase 4.3).

The Detectors grid below the lane list is a **side-by-side adjacency table**
(ROADMAP Item 16): one CSS Grid whose columns are the template's physical
lanes. Detectors at the same distance from the stop bar (the count loops
across the lanes, the stop-bar zones, the advance loops) share **one row**,
laid out under the lane(s) each spans (`grid-column` start/span from
`spanning_lanes`) — so a row spanning lanes 1-2 visibly merges those two
columns and siblings in other lanes sit beside it. Rows are the adjacency
groups from `model.detector_layout.group_adjacent_detectors`
(display-only — the saved template stays a flat detector list);
`assign_tracks` stacks any laterally-colliding detectors onto sub-rows.
"Seed from kinematics" materializes `seed_detectors()`'s ITE defaults, then
groups them; nothing recomputes afterward — a stored length/setback/output-
offset/phase fully replaces the seeded value once edited ("seed, don't
constrain"). Without seeding, **Add row** drops an empty band and the `+` in
each empty lane column adds a detector there (inheriting the row's station
from its first detector); spanning multiple lanes is done by editing a
cell's lane range.
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

from model.detector_layout import assign_tracks, group_adjacent_detectors
from model.templates import (DETECTOR_KINDS, DIRECTIONS, MOVEMENT_CHARS,
                             ApproachTemplate, Lane, TemplateDetector,
                             lane_config_str, load_template, save_template,
                             seed_detectors)

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"


def build_ui(template: ApproachTemplate, path: Path | None) -> None:
    state = {"path": path}
    lane_rows: list[dict] = []
    # Detector rows grouped into side-by-side adjacency bands (ROADMAP Item 16):
    # each inner list is one table row's detector dicts. Grouping is display-only
    # (built once on seed/load); saving flattens it back to a flat detector list.
    groups: list[list[dict]] = []

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

    # -- Item 16: side-by-side adjacency table --------------------------------
    # One CSS Grid: columns 2..n+1 are the template's physical lanes, column 1
    # is a slim per-row header (Row #, delete-row). Detectors are grouped into
    # adjacency bands (`groups`, one inner list per table row); within a row
    # each detector is a card placed at `grid-column: span_from+2 / span count`
    # so same-station detectors sit side by side across their lanes. Cards are
    # plain dicts (not tied to ui elements), so any structural change just
    # clears and rebuilds the grid. Grouping is display-only — `collect_form`
    # flattens `groups` back to a flat detector list for saving/expansion.

    def row_from_detector(det: TemplateDetector) -> dict:
        return {"kind": det.kind, "span_from": det.spanning_lanes[0],
                "span_to": det.spanning_lanes[-1], "length_ft": det.length_ft,
                "setback_ft": det.setback_ft, "output_offset": det.output_offset,
                "phase": str(det.phase)}

    def all_rows() -> list[dict]:
        return [row for group in groups for row in group]

    def set_groups_from_detectors(dets: list[TemplateDetector]) -> None:
        """Rebuild `groups` by adjacency-grouping a flat detector list (used on
        seed and load); display-only, keeps input order within each group."""
        rows = [row_from_detector(d) for d in dets]
        groups.clear()
        groups.extend([rows[i] for i in members]
                      for members in group_adjacent_detectors(dets))

    def grid_columns_css() -> str:
        cols = ["150px"]
        for r in lane_rows:
            try:
                weight = max(float(r["width"].value or 12.0) / 12.0, 0.5)
            except (TypeError, ValueError):
                weight = 1.0
            cols.append(f"minmax(150px, {weight:.2f}fr)")
        return " ".join(cols) if lane_rows else "150px 1fr"

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

    def remove_detector_row(group: list[dict], row: dict) -> None:
        group.remove(row)  # an emptied band stays as a "+"-per-column row
        render_detectors()

    def remove_group(group: list[dict]) -> None:
        groups.remove(group)
        render_detectors()

    def add_row() -> None:
        groups.append([])  # empty band: a "+" in every lane column
        render_detectors()

    def add_cell(group: list[dict], lane: int) -> None:
        """Add a detector in `lane`. A sibling in an existing band inherits its
        station (setback/length) and kind/phase from the band's first detector;
        the first detector of an empty band gets plain defaults. Spanning more
        lanes is done afterward by editing the cell's lane range."""
        if group:
            init = group[0]
            row = {"kind": init["kind"], "span_from": lane, "span_to": lane,
                   "length_ft": init["length_ft"], "setback_ft": init["setback_ft"],
                   "output_offset": len(all_rows()), "phase": init["phase"]}
        else:
            row = {"kind": "count", "span_from": lane, "span_to": lane,
                   "length_ft": 5.0, "setback_ft": 0.0,
                   "output_offset": len(all_rows()), "phase": "thru"}
        group.append(row)
        render_detectors()

    def do_seed() -> None:
        try:
            temp = ApproachTemplate(
                lanes=current_lanes(), speed_mph=float(speed.value or 0),
                extension_time_s=float(extension.value or 1.0),
                decision_length_ft=float(decision_length.value or 0),
                advance_length_ft=float(advance_length.value or 0),
                count_loops=bool(count_loops.value))
        except ValueError as e:
            ui.notify(f"fix the lanes/speed first: {e}", type="negative")
            return
        set_groups_from_detectors(seed_detectors(temp))
        render_detectors()
        ui.notify(f"seeded {len(all_rows())} detector(s) in {len(groups)} row(s)")

    def seed_from_kinematics() -> None:
        if not all_rows():
            do_seed()
            return
        with ui.dialog() as dialog, ui.card():
            ui.label("Replace all detector rows with fresh kinematic defaults? "
                     "Existing edits will be lost.")
            with ui.row():
                ui.button("Replace", on_click=lambda: (dialog.close(), do_seed()))
                ui.button("Cancel", on_click=dialog.close)
        dialog.open()

    def render_detector_card(group: list[dict], row: dict, grid_row: int,
                             n_lanes: int) -> None:
        span_count = row["span_to"] - row["span_from"] + 1
        with ui.card().classes("p-2 gap-1").style(
                f"grid-column:{row['span_from'] + 2} / span {span_count}; "
                f"grid-row:{grid_row}; background:#173017; "
                "border:1px solid #2ca02c;"):
            with ui.row().classes("items-center gap-1 w-full no-wrap"):
                kind_opts = list(dict.fromkeys([*DETECTOR_KINDS, row["kind"]]))
                ui.select(kind_opts, value=row["kind"], with_input=True,
                         new_value_mode="add-unique",
                         on_change=lambda e, row=row:
                         row.__setitem__("kind", e.value)).props("dense").classes("grow")
                ui.button(icon="delete",
                         on_click=lambda group=group, row=row:
                         remove_detector_row(group, row)).props("flat dense size=sm")
            with ui.row().classes("items-center gap-1 no-wrap"):
                ui.label("lanes").classes("text-xs text-gray-400")
                ui.number(value=row["span_from"], min=0, max=n_lanes - 1,
                         precision=0,
                         on_change=lambda e, row=row:
                         set_span(row, "span_from", e.value)) \
                    .classes("w-12").props("dense")
                ui.label("-").classes("text-xs")
                ui.number(value=row["span_to"], min=0, max=n_lanes - 1,
                         precision=0,
                         on_change=lambda e, row=row:
                         set_span(row, "span_to", e.value)) \
                    .classes("w-12").props("dense")
                ui.input(value=row["phase"], placeholder='thru / lt / #',
                         on_change=lambda e, row=row:
                         row.__setitem__("phase", e.value)) \
                    .classes("w-16").props("dense").tooltip("phase: thru / lt / #")
                ui.number(value=row["output_offset"], min=0, precision=0,
                         on_change=lambda e, row=row: row.__setitem__(
                             "output_offset", int(e.value or 0))) \
                    .classes("w-12").props("dense").tooltip("output offset (+ base)")
            with ui.row().classes("items-center gap-1 no-wrap"):
                ui.number("length (ft)", value=row["length_ft"], min=0.1,
                         precision=1,
                         on_change=lambda e, row=row: row.__setitem__(
                             "length_ft", float(e.value or 0))) \
                    .classes("w-24").props("dense")
                ui.number("setback (ft)", value=row["setback_ft"], precision=1,
                         on_change=lambda e, row=row: row.__setitem__(
                             "setback_ft", float(e.value or 0))) \
                    .classes("w-24").props("dense")

    def render_detectors() -> None:
        n_lanes = max(len(lane_rows), 1)
        for row in all_rows():  # reclamp in case a lane was deleted
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
            grid_row = 2
            for gi, group in enumerate(groups):
                tracks = assign_tracks([(r["span_from"], r["span_to"])
                                        for r in group])
                n_tracks = (max(tracks) + 1) if tracks else 0
                span_rows = n_tracks + 1  # detector tracks + the add-cell row
                # slim row header spanning the band's rows
                with ui.column().classes("gap-1 p-1 bg-grey-9 rounded "
                                         "items-center justify-center").style(
                        f"grid-column:1; grid-row:{grid_row} / span {span_rows};"):
                    ui.label(f"Row {gi + 1}").classes("text-xs text-gray-400")
                    ui.button(icon="delete_sweep",
                             on_click=lambda group=group: remove_group(group)) \
                        .props("flat dense size=sm").tooltip("delete row")
                # detector cards, one per track
                covered: set[int] = set()
                for row, track in zip(group, tracks):
                    render_detector_card(group, row, grid_row + track, n_lanes)
                    covered.update(range(row["span_from"], row["span_to"] + 1))
                # add-cell row: a "+" in every uncovered lane column
                add_grid_row = grid_row + n_tracks
                for c in range(n_lanes):
                    if c in covered:
                        continue
                    ui.button(icon="add",
                             on_click=lambda group=group, c=c: add_cell(group, c)) \
                        .props("flat dense").style(
                        f"grid-column:{c + 2}; grid-row:{add_grid_row}; "
                        "border:1px dashed #555; min-height:32px;") \
                        .tooltip(f"add detector in lane {c + 1}")
                grid_row += span_rows

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
        # Flatten the display groups back to a flat detector list (row order,
        # then within-row order); grouping is display-only and not persisted.
        rows = []
        for i, row in enumerate(all_rows()):
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
        decision_length.value = t.decision_length_ft
        advance_length.value = t.advance_length_ft
        direction.value = t.direction
        count_loops.value = t.count_loops
        base_output.value = t.base_output
        thru_phase.value = t.thru_phase
        lt_phase.value = t.lt_phase
        lanes_col.clear()
        lane_rows.clear()
        for lane in t.lanes:
            add_lane_row(lane)
        set_groups_from_detectors(t.detectors)
        refresh_preview()

    def collect_form() -> ApproachTemplate:
        lanes = current_lanes()

        def opt_int(el):  # blank = placeholder (prompt at placement)
            return int(el.value) if el.value is not None else None

        return ApproachTemplate(
            name=name.value or "New approach",
            speed_mph=float(speed.value or 0),
            extension_time_s=float(extension.value or 1.0),
            decision_length_ft=float(decision_length.value or 0),
            advance_length_ft=float(advance_length.value or 0),
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
            decision_length = ui.number("Decision len (ft)", min=0.1, step=1,
                                        precision=1).classes("w-32")
            with decision_length:
                ui.tooltip("length the seeder gives decision detectors "
                           "(the indecision-zone chain); set before seeding")
            advance_length = ui.number("Advance len (ft)", min=0.1, step=1,
                                       precision=1).classes("w-32")
            with advance_length:
                ui.tooltip("length the seeder gives the advance detector; "
                           "set before seeding")
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
            ui.button("Add row", on_click=add_row).props("flat dense")
            ui.button("Seed from kinematics", on_click=seed_from_kinematics) \
                .props("flat dense")
        ui.label("columns are the physical lanes above. Each row is an "
                 "adjacency band: detectors at the same distance from the stop "
                 "bar sit side by side across their lanes. Use \"+\" to add a "
                 "detector in an empty lane (a sibling inherits the row's "
                 "station); edit a cell's lane range to span more lanes. "
                 "Seeding fills the ITE kinematic defaults — edit any value to "
                 "override; seeding never runs again on its own.") \
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
