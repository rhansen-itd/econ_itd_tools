# Roadmap — iprj Designer

Two rounds of work are complete and archived in [[DESIGN_HISTORY.md]], not
listed here anymore: the Phase 1 MVP (Sessions 1–7 — data model, drawing
core, attributes, templates, centerline placement) and a second
"Phase 1–4" round (quick wins/file management, domain accuracy, the
toolbar/multi-select overhaul, and the advanced template engine). Reusing
"Phase 1" for two unrelated rounds is exactly the confusion this file is
now organized to avoid — see the note below.

Work below is broken into **named, numbered items** instead of sequential
phases:
- The number is a **stable ID**, assigned once when an item is added and
  never reused or renumbered — not an execution sequence. An item's
  number doesn't change if items above/below it are finished and removed,
  or if the list gets reordered.
- **File order is priority order** (with prerequisites noted inline where
  one item depends on another), read top to bottom. Reordering the file
  doesn't touch the numbers.
- Each item still carries a **Target** model per [[CLAUDE.md]]'s routing
  (Fable — pure Python math/geometry/schema *implementation only* in
  `model/`, plus any pure-python controller work under `gui/`; Sonnet —
  NiceGUI wiring, plus the finishing pass — tests/DESIGN_HISTORY/ROADMAP
  checkboxes/IPRJ_FORMAT — for whatever Fable produced; Opus — cross-module
  architecture planning) and a **Suggested prompt**. See CLAUDE.md's "Core
  vs. finishing work" for why a "Fable then Sonnet" prompt below tells
  Fable to skip tests/docs and tells Sonnet to pick them up.
- Tell the agent "do Item N of ROADMAP.md" (or reference it by name) to run
  a scope below; check off items and log decisions in [[DESIGN_HISTORY.md]]
  as they land, the same way every round so far has.

"Future" items at the bottom aren't scoped yet (no Target/Scope/prompt) —
they need a planning pass before they're actionable.

---

## 1 — Simple GUI Changes: Background Tool Rework (Target: Sonnet)

Highest priority right now; small, independent UI changes that should fit
in one session.

Scope:
- [x] Rename the **Measure** tool to **Background**; move calibration (both
      2-point-click and known-width/height) into it unchanged.
- [x] Add background image upload to the Background tool, for an
      *already-open* project — replace `project.background`'s image and
      re-derive `image_w`/`image_h` (reuse the decode/embed logic
      `new_project`'s upload path already has), without touching zones,
      sensors, or centerlines. Today upload only exists via File > New,
      which starts a blank project.
- [x] Move the Ruler tool (and its "clear ruler" button) out of the
      Measure/Background sub-type toggle and onto the persistent chrome
      row — it's a general-purpose tool, not tied to any workflow.
- [x] Delete the Marker function entirely (`Viewer.markers`, the marker
      click handler, its `svg()` rendering, and the marker half of "clear
      markers & ruler" — that button becomes "clear ruler" and moves with
      Ruler per the point above).
- [x] Give the known-width/height calibration button a new icon, distinct
      from Ruler's (Ruler can take the current "straighten" icon). Aim for
      something that reads as "rectangle with dimension lines on two
      sides" — `aspect_ratio` is a reasonable Material-icon candidate;
      confirm/adjust by eye in the running app.

Suggested prompt:
> [Sonnet] In EVO/iprj_designer, do Item 1 of ROADMAP.md: rename Measure to
> Background (keep calibration), add background-image upload for an
> already-open project, move Ruler + its clear button to the persistent
> toolbar row, delete the Marker function, and pick a new icon for the
> known-width/height calibration button.

## 2 — Conditions: Wire Per-Zone-Type Field Filtering (Target: Sonnet)

Bug: the zone-properties dialog's Conditions section always shows the
same fields (output/class/velocity min/max) regardless of `ZoneType`, so a
Presence (stop-bar) zone can have a nonsensical velocity condition edited
and saved. `model/domain.py` already has the correct per-type split
(`condition_fields`/`conditions_allowed` — Presence: output/delay/extend/
queue length/vehicle counts, no velocity/class/direction; Motion: adds
velocity/class/direction/ETA) from the Phase 2 round, but `gui/app.py`'s
`zone_properties()`/`add_cond_row()` never call it — confirmed by grep,
there's no reference to either function in `gui/app.py` today.

Scope:
- [x] Wire `domain.condition_fields(zone.zone_type)` into the Conditions
      section so only the relevant fields render per row, and
      `domain.conditions_allowed(...)` to hide/disable "Add condition"
      for Sidewalk zones.
- [x] Re-check existing saved conditions against the new field set on
      dialog open (a Presence zone with a stray velocity value from before
      this fix) — decide whether to just not render it or actively clear
      it, and note the choice in DESIGN_HISTORY. **Decided: not render,
      don't clear** — see DESIGN_HISTORY.md.

Suggested prompt:
> [Sonnet] In EVO/iprj_designer, do Item 2 of ROADMAP.md: wire
> `domain.condition_fields`/`conditions_allowed` into the zone-properties
> dialog's Conditions section so each zone type only shows/edits its
> relevant fields (Presence: queue + vehicle counts, no velocity; Motion:
> velocity/class/direction/ETA; Sidewalk: none).

## 3 — Zone Duplication Across Sensors on Load — CLOSED, not a bug (2026-07-04)

Original report: on the Perimeter site, loading appeared to duplicate one
sensor's zones onto both sensors. **Investigated and closed: the load path is
sound — the duplication is a property of the source files themselves, not
`model/iprj_io.py`'s sensor/zone association.** The loader faithfully
represents what the file contains. No parser change and no regression test
were warranted. Item 9's split/merge round-trip tests still exercise the
zone↔sensor association as a standing safety net, so a real loader regression
here would surface there.

## 4 — Sensor Management: Nudge, Delete, Status Fix (Target: Sonnet)

Three small, related sensor-menu gaps.

Scope:
- [x] Arrow-key nudge for the active sensor while the Sensor tool is
      active (mirrors the zone nudge in `gui/drawing.py`'s
      `DrawingController._nudge`, `NUDGE_FT` step).
- [x] Delete sensor: a button in the Sensor context bar plus `x`/Del.
      Prompt whether to delete the sensor's zones/conditions along with it
      or reassign them to another sensor first (blocks deletion of the
      last remaining sensor, or handle by falling back to a blank default
      the way a from-scratch project does).
- [x] Fix the active-sensor status text: `add_sensor()` calls
      `update_sensor_options()` but never `refresh_status()`, so the
      status line still reads the old sensor after adding a new one (e.g.
      add S3, footer still says "S1 active") until something else
      happens to trigger a refresh. Same check needed anywhere else a
      sensor change might skip the status refresh.

Suggested prompt:
> [Sonnet] In EVO/iprj_designer, do Item 4 of ROADMAP.md: add arrow-key
> nudge for the active sensor, a delete-sensor button + x shortcut
> (prompting reassign-vs-delete-children), and fix add_sensor() to call
> refresh_status() so the footer reflects the newly active sensor.

## 5 — Edit Mode Rename & Add-Vertex Shortcut (Target: Fable then Sonnet)

Scope:
- [x] Rename "Select" to "Edit" throughout the UI (tool toggle label,
      status strings, docstring/tooltips); drop `v` as an alias so `e` is
      the only accelerator for it (currently `TOOL_KEYS` maps both `v` and
      `e` to Select — see `gui/app.py`).
- [x] New `v` shortcut: insert a vertex into the single selected
      element, at the nearest edge to the cursor (or its midpoint if
      that's simpler for a first pass). No existing vertex-insertion logic
      to build on (`gui/drawing.py`/`model/geometry.py` — confirmed by
      grep), so this is new: a pure-python `model/geometry.py` helper
      (nearest-edge projection on a polygon) plus a `DrawingController`
      method, then the Sonnet-side key wiring. **Model half done
      2026-07-04** (`geometry.nearest_edge_insertion` +
      `DrawingController.insert_vertex`, nearest-edge not midpoint,
      tested — see DESIGN_HISTORY.md); **Sonnet half done 2026-07-04**
      (rename + `v` key wiring — see DESIGN_HISTORY.md).

Suggested prompt:
> [Fable] In EVO/iprj_designer, do the model-layer half of Item 5 of
> ROADMAP.md: a nearest-edge-insertion geometry helper and a
> DrawingController method to insert a vertex into the single selected
> element, pytest-covered, no GUI imports. Then [Sonnet]: rename
> Select → Edit everywhere (drop the `v` alias, `e` only) and wire `v` to
> the new insert-vertex action.

## 6 — Terminology: Loop → Event Zone (Target: Sonnet) — done 2026-07-04

Rename "Loop" to "Event Zone" throughout the main editor (toolbar, zone
table, status strings, tooltips — ~12 occurrences in `gui/app.py`/
`gui/drawing.py`, mechanical), matching vendor terminology. The template
editor (`gui/templates_ui.py`) can keep saying "Loop" where that's already
the established word there.

Done — see DESIGN_HISTORY.md.

Suggested prompt:
> [Sonnet] In EVO/iprj_designer, do Item 6 of ROADMAP.md: rename "Loop" to
> "Event Zone" throughout the main editor's UI strings; leave
> gui/templates_ui.py's wording as-is.

## 7 — Free-Draw Polygons: Support More Than 4 Points (Target: Fable then Sonnet) — done 2026-07-04

`DrawingController` currently hardcodes polygon completion at exactly 4
points (`needed = 2 if segment else 4` — `gui/drawing.py`), for both Event
Zones and Ignore Zones. Needs an explicit "finish" action instead of a
fixed count.

Scope:
- [x] `DrawingController`: allow polygon draws to continue past 4 points;
      add an explicit finish trigger (double-click, or an Enter/key
      commit) instead of auto-completing at a fixed count. Keep the
      existing dimensioned-rectangle path's 4-point shape unaffected — this
      is about free (non-dimensioned) draw. **Done 2026-07-04**
      (`finish_polygon()`, Enter already reaches it through the existing
      key dispatch; trailing double-click duplicates folded — see
      DESIGN_HISTORY.md).
- [x] Wire the finish gesture in `gui/app.py` (double-click during a
      pending free-draw commits it; existing snapping/undo behavior
      unchanged). **Done 2026-07-04** (`on_dblclick`'s Draw-mode branch
      calls `v.ctrl.finish_polygon()` — see DESIGN_HISTORY.md).

Done — see DESIGN_HISTORY.md.

Suggested prompt:
> [Fable] In EVO/iprj_designer, do the controller half of Item 7 of
> ROADMAP.md: let free-draw polygons (Event Zone / Ignore Zone) continue
> past 4 points, completing on an explicit finish trigger rather than a
> fixed count; keep dimensioned-rectangle draw unchanged. Then [Sonnet]:
> wire double-click-to-finish in gui/app.py.

## 8 — Move Event Zone Along a Centerline (Target: Fable then Sonnet) — done 2026-07-04

For a zone attached to a centerline (`CenterlineController.attached` —
Session 7.5), add a way to move it precisely along the datum: set an
absolute station (e.g. "200 ft") or nudge by a relative amount (e.g. "+20
ft upstream"). Builds on the existing `Centerline.locate`/`point_at` and
the attach/reproject machinery, so this is mostly a new controller method
plus a small dialog, not new geometry.

Scope:
- [x] `CenterlineController` method to re-station an attached zone by an
      absolute or relative station delta, re-deriving its world points via
      `Centerline.point_at` (mirrors what a manual drag + `reproject`
      already does, just precise/typed instead of dragged). **Done
      2026-07-04** (`zone_station`/`move_attached` — see DESIGN_HISTORY.md).
- [x] Small dialog on the selected zone (Edit tool, only when it's
      centerline-attached) to enter the absolute station or relative
      delta. **Done 2026-07-04** (toolbar button + `move_along_centerline`
      dialog in `gui/app.py` — see DESIGN_HISTORY.md).

Done — see DESIGN_HISTORY.md.

Suggested prompt:
> [Fable] In EVO/iprj_designer, do the model-layer half of Item 8 of
> ROADMAP.md: a CenterlineController method to move an attached zone to an
> absolute station or by a relative delta along its centerline.
> Implementation only — skip pytest coverage and doc updates. Then
> [Sonnet]: add a small dialog (Edit tool, centerline-attached zones only)
> to drive it; also run the finishing pass on Fable's method — pytest
> coverage, check off Item 8 in ROADMAP.md, and log the decision in
> DESIGN_HISTORY.md.

## 11 — Canonical Coordinate Origin (background top-left = 0,0) (Target: Fable) — done 2026-07-04

The vendor writes every object's coordinates relative to the *view at the time
of save* — an arbitrary origin — so `Background_PosX/Y` and all zone/sensor/
ref/lineal/label coordinates drift file to file. We want a **fixed insertion
point instead**: normalize every project on load so the background image's
top-left is world (0,0), which makes any position manipulation reason from one
known datum. This is a companion to (and lands before) Item 9 — it's what
makes the two-file background match a same-frame comparison rather than a
cross-file delta computation (see [[ITEM9_SPLIT_PLAN.md]] §3a).

Note this **deliberately departs from vendor byte-fidelity** on save (we write
`pos = 0,0` and shifted coordinates, not the vendor's originals) — it changes
the round-trip contract for *all* files, so update the `iprj_io` round-trip
tests and IPRJ_FORMAT.md accordingly.

Scope:
- [x] Pure-python `normalize_origin(project)` (`model/coords.py`): shift by
      `(−pos_x, −pos_y)` across **every** coordinate field — background pos
      → (0,0), event/ignore zone points, sensor positions, ETA points,
      `MeterReference0/1`, lineals, text-label positions. Calibration
      (`meter_per_pixel`/`ReferenceLength`) is translation-invariant and
      stays untouched; `test_calibration_untouched` asserts
      `effective_meter_per_pixel` is unchanged.
- [x] Applied at the `load_iprj` boundary — the whole app works in
      image-origin coordinates; save naturally writes 0,0.
- [x] Updated the round-trip tests (they now assert the shifted-not-identical
      contract) and noted the new contract in IPRJ_FORMAT.md.

Done — see DESIGN_HISTORY.md.

Suggested prompt:
> [Fable] In EVO/iprj_designer, do Item 11 of ROADMAP.md: a pure-python
> normalize_origin(project) that translates every coordinate so the
> background image's top-left is world (0,0), applied at the load boundary,
> leaving calibration untouched; update the round-trip tests and
> IPRJ_FORMAT.md for the new (non-vendor-byte-identical) save contract.

## 9 — Multi-Sensor 2-File Split (Read/Write/Overlay) (Target: Opus plan, then Fable + Sonnet) — done 2026-07-04

The vendor software only supports two sensors per file. A 3+ sensor
project needs to be written as a pair of files — sensors 1-2 in one,
sensors 3-4 in another (renumbered 1-2 in that file) — with identical
background image/calibration in both. Reading needs the inverse: open a
second file as an overlay onto the first, after verifying they share the
same background (image, orientation, scale) — fail with a clear reason if
they don't. **Depends on Item 3**: understanding the real sensor/zone
association on load matters before building a feature that splits/merges
sensors across files.

Scope (Opus plan first — this touches file I/O, the file menu, and
project-state assumptions that are currently single-file). **Plan done
2026-07-04 — see [[ITEM9_SPLIT_PLAN.md]]** (filename-only pairing, one
in-memory 4-sensor Project split/merged at the I/O boundary via a new
`model/multifile.py`; two-tier background match; the Save/Save-As pair
rule). All three decisions below resolved there:
- [x] Decide the pairing model: how a "1-2 file" and a "3-4 file" reference
      each other (filename convention only, per the ask below, or an
      in-file marker), and how `Viewer`/`Project` represent "two files,
      one overlaid project" in memory.
- [x] Decide the background-match check (what "same background" means
      precisely — pixel hash? calibration + dimensions? — and the failure
      message when it doesn't match).
- [x] Decide the save-path restriction: **no plain Save** when a project
      spans two files unless they follow the `..._1_2.iprj`/`..._3_4.iprj`
      naming convention (same base name, differing only in that suffix) —
      Save As must re-derive both filenames from one entered name.

Scope (Fable + Sonnet, once the plan lands):
- [x] `model/multifile.py`: naming helpers (`pair_paths`/`is_valid_pair`/
      `pair_role`), `check_background_match` (two-tier), `split_project`/
      `merge_pair`, plus `tests/test_multifile.py` (28 tests — the plan's
      §5 explicitly folded pytest coverage into the Fable session as the
      Sonnet-handoff gate, an exception to the usual Fable-skips-tests
      rule).
- [x] `gui/app.py`: File menu action ("Open second sensor-pair file
      (overlay)…") to merge a second file's sensors into the current
      project — `pair_role` decides primary/secondary when the filenames
      follow the convention, otherwise a two-button dialog asks; a soft
      background mismatch confirms before merging, a hard mismatch blocks.
      `add_sensor` caps at `MAX_SENSORS` (4) with a notify. `do_save`/
      `save`/`save_as` grow the two-file branch from the plan (plain Save
      only when `Viewer.pair` is a valid naming pair, otherwise redirected
      to Save-As; Save-As previews the derived `_1_2`/`_3_4` names).
- [x] Finishing pass: verified end-to-end in a live browser session
      (Playwright) against the real Franklin_KCID two-file site — merge,
      the 4-sensor cap, and Save writing a validated `_1_2`/`_3_4` pair all
      confirmed working; see DESIGN_HISTORY.md and IPRJ_FORMAT.md for the
      logged decisions and format contract.

Suggested prompt:
> [Opus] In EVO/iprj_designer, plan Item 9 of ROADMAP.md: a vendor file
> only holds 2 sensors, so a 3+ sensor project needs to read/write as a
> pair of files (sensors 1-2 / 3-4, identical background). Decide the
> pairing model, the background-match check, and the save-path
> restriction (only a `..._1_2`/`..._3_4` naming pair may Save; anything
> else is Save-As only). Output a plan for Fable (model split/validation,
> implementation only) and Sonnet (File-menu wiring, plus the finishing
> pass: tests for Fable's model code, ROADMAP/DESIGN_HISTORY/IPRJ_FORMAT
> updates) to implement.

## 10 — Webserver Deployment (Target: Opus plan, then Sonnet)

Carried over unchanged from the earlier "Phase 5" round (not started;
deprioritized below the items above, not dropped).

Scope:
- [ ] Decide how per-user/project state is isolated across concurrent
      NiceGUI sessions.
- [ ] Decide project file management approach (server-side open/save vs.
      upload/download) and whether auth is in scope.
- [ ] Output a plan for the implementation pass — this half is a decision
      document, not code.
- [ ] Implement the plan: multi-session safety, project file management,
      harden NiceGUI serving for other users.
- [ ] Packaging (`pip install` entry point or container).

Suggested prompt:
> [Opus] In EVO/iprj_designer, plan Item 10 of ROADMAP.md: design
> multi-session state isolation for the NiceGUI app, a project file
> management approach (server-side vs. upload/download), and whether auth
> is in scope. Produce a plan for Sonnet to implement — no code changes
> this session.

---

## Future (not yet scoped)

- Display objects from a live stream.
- Upload and play back a recorded playback file.
- Integrate the line-up/calibrate workflow (see
  `~/pyatspm/src/atspm/video/calibrate.py`) more directly into the app.
