# Roadmap — iprj Designer

Four rounds of work are complete and archived in [[DESIGN_HISTORY.md]], not
listed here anymore: the Phase 1 MVP (Sessions 1–7 — data model, drawing
core, attributes, templates, centerline placement), a second "Phase 1–4"
round (quick wins/file management, domain accuracy, the toolbar/multi-select
overhaul, and the advanced template engine), a third numbered-items round
(Items 1–9 and 11 — background-tool rework, per-zone-type conditions,
sensor management, edit-mode/vertex tools, terminology renames, free-draw
polygons, centerline re-stationing, canonical origin, and the multi-sensor
2-file split), and a fourth "owner batch" round (Items 12–20 — quick UI
fixes, the template-editor taxonomy rename + even spacing + side-by-side
adjacency table, centerline placement snap/naming, and the large-file
zoom-freeze fix). Reusing "Phase 1" for two unrelated rounds is exactly the
confusion this file is now organized to avoid — see the note below.

Work below is broken into **named, numbered items** instead of sequential
phases:
- The number is a **stable ID**, assigned once when an item is added and
  never reused or renumbered — not an execution sequence. An item's
  number doesn't change if items above/below it are finished and removed,
  or if the list gets reordered.
- **File order is priority order** (with prerequisites noted inline where
  one item depends on another), read top to bottom. Reordering the file
  doesn't touch the numbers.
- Each item carries a **Target** model per [[CLAUDE.md]]'s routing and a
  **Suggested prompt**. Default is **Opus, end-to-end in one session**
  (plan + implement + tests + docs, no cross-model hand-off); Sonnet is an
  option for a whole small mechanical item; Fable is a debugging escalation
  only. See CLAUDE.md's "Model routing / division of labor" for the full
  rule. (Older completed items — now archived — used a "Fable then
  Sonnet" hand-off that this routing has retired.)
- Tell the agent "do Item N of ROADMAP.md" (or reference it by name) to run
  a scope below; check off items and log decisions in [[DESIGN_HISTORY.md]]
  as they land, the same way every round so far has.

"Future" items at the bottom aren't scoped yet (no Target/Scope/prompt) —
they need a planning pass before they're actionable.

---

# Annotation-ownership batch — added 2026-07-05

Two items that make lineals, centerlines, and text labels **sensor-owned**
via the vendor's persistent index ranges, and add text-label support to the
GUI. Numbers **21–22** are new stable IDs. **Item 22 depends on Item 21.**
Both Opus, split across two sessions by the model/GUI layer boundary (the
scoping call from the 2026-07-05 planning pass — a single diff would rework
two format contracts *and* ship a new GUI entity at once). They sit **ahead
of Item 10** (webserver) in priority.

Key format facts behind the design (verified 2026-07-05 against
`sites/**/*.iprj`): lineal and text-label slots persist **by index** in the
vendor software — writing lineal 10 with 1–9 absent reloads and re-saves as
lineal 10 — and the vendor auto-writes new annotations to the **lowest free
index**. Every vendor file carries full 100-slot `Lineals_*` and
`Textlabel_*` placeholder arrays (`Enable="0"`; disabled text labels park at
`Position_X/Y="-9999.00"`). A real enabled text label is `FontSize="12"`,
`RotationAngle` in **degrees**, `Textcolor_*` RGB 0–255.

## 21 — Sensor-scoped lineals/centerlines/labels via index bands (Target: Opus)

Today lineals, centerlines, and text labels are **project-wide**, owned
entirely by the `_1_2` file on the 2-file split (`model/multifile.py`,
`model/centerline.py`). Reserve vendor index bands instead, so annotations
travel with the right sensor file — and so the vendor's lowest-free-index
auto-write lands in a neutral "general" band by construction. Bands are
0-based indices (vendor UI numbers are +1), applied to `Lineals_*` **and**
`Textlabel_*` independently:

- **0–19** (vendor 1–20) — *general*, written to **both** files.
- **20–59** (vendor 21–60) — sensors 1&2 → `_1_2`.
- **60–99** (vendor 61–100) — sensors 3&4 → `_3_4`.

Ownership has no on-disk tag; it is **inferred on load from the band an
element's index falls in** and re-materialized on save. Active-sensor →
band mapping mirrors the split boundary: si 0/1 → FILE1, si 2/3 → FILE2.

Model-only (pure `model/`, headless tests); **no GUI behavior change yet** —
everything defaults to the general band (→ both files, already the "general
to both files" change owner asked for) until Item 22 wires ownership to the
active sensor.

**Done 2026-07-05** (Opus, session 1 of 2 — see DESIGN_HISTORY.md). New
`model/bands.py` (Owner/bands/`allocate`) + `model/labels.py`; band-scoped
`_owned` variants in `model/centerline.py` with plain functions kept as
GENERAL wrappers; `model/multifile.py` split/merge reworked. Suite green
(423). Item 22 (GUI) wires ownership to the active sensor.

Scope:
- [x] Add an ownership axis (GENERAL / FILE1 / FILE2) + band constants in
      one place; carry owner on the working copies `load_lineals` /
      `load_centerlines` (and a new `load_labels`) return, inferred on load
      from the element's band. *(`model/bands.py`; `load_*_owned` variants.)*
- [x] Band-scope the slot allocators in `model/centerline.py`
      (`save_lineals` / `save_centerlines`, new `save_labels`): fill free
      slots *within the owner's band*; a multi-segment centerline stays
      inside one band; overflow returns skipped for the GUI to surface.
- [x] Rework `model/multifile.py` split/merge: split blanks the *other*
      file's band (general kept in both); merge recombines by band, with
      `general_blocks_match` as the soft-warn when the two general blocks
      disagree (mirroring `check_background_match`). Each output stays a
      100%-vendor-clean standalone file.
- [x] Route text labels through the band mechanism (`model/labels.py`);
      honor the `-9999` disabled-slot position sentinel and treat `Enable=0`
      as a free slot.
- [x] Tests: band allocation, split blanks the correct band, merge/verify of
      the general block, load infers owner, band overflow, full round-trip
      (`test_bands`/`test_labels` + band cases in existing suites). Updated
      `IPRJ_FORMAT.md` + `DESIGN_HISTORY.md`.

Suggested prompt:
> [Opus] Do Item 21 of EVO/iprj_designer/ROADMAP.md: make lineals,
> centerlines, and text labels sensor-owned via vendor index bands (0–19
> general → both files, 20–59 sensors 1&2 → _1_2, 60–99 sensors 3&4 →
> _3_4). Band-scope model/centerline.py slot allocation, rework
> model/multifile.py split/merge to blank the other file's band and keep
> general in both, infer ownership from index on load, and route text
> labels through the same mechanism. Pure model + full pytest +
> IPRJ_FORMAT/DESIGN_HISTORY. Prereq for Item 22.

## 22 — Text-label GUI entity + sensor assignment + centerline-name labels (Target: Opus) — needs Item 21

Add text labels as a first-class GUI entity and wire Item 21's ownership to
the active sensor. Depends on Item 21's band-scoped persistence.

**Done 2026-07-05** (Opus, session 2 of 2 — see DESIGN_HISTORY.md). Text Label
landed as a 4th Draw sub-type (key `a`) backed by a new `"point"` shape in
`DrawingController`; ownership is a transient `_owner` on lineals/labels and
`CenterlineController.owner` on centerlines, stamped from a General/Active-sensor
toolbar toggle and saved via the `_owned` variants; centerline names persist as
a no-rotation far-end label, re-derived on load by `model.labels.match_name_labels`.
Suite green (434).

Scope:
- [x] New **Text Label** draw kind: create / edit / move / delete, editable
      text, FontSize / color / bold / italic / underline / rotation.
      New-label defaults: FontSize 12, white (255/255/255), no flags,
      rotation 0° (degrees). *(`LABEL_KIND` + `domain.new_label`; label
      properties dialog in `gui/app.py`.)*
- [x] Assign lineals / centerlines / labels by the active sensor (S1/S2 →
      FILE1, S3/S4 → FILE2) the way zones bind via `active_si`, plus an
      explicit **General** choice for the 0–19 band; surface the owning
      band in the relevant toolbars; warn on band overflow (the skipped
      list from Item 21). *(`assign_general`/`current_owner`; General vs.
      Active-sensor toggle + band hint; overflow notify on save.)*
- [x] Centerline-name label: on centerline creation, auto-create a
      no-rotation label at the last (furthest-from-stop-bar) point holding
      the name; update it on rename; on load, re-derive the association (a
      no-rotation label at a centerline's far end → that centerline's name),
      the way `derive_attachments` re-links zones. Retire the "not
      persisted" note on `CenterlineController.name` (`gui/drawing.py`,
      Item 20). *(`sync_centerline_labels`/`_derive_centerline_names`;
      `match_name_labels`.)*
- [x] Tests where logic lands in `model/` (the re-derivation/association);
      GUI finishing pass; `DESIGN_HISTORY.md` + docs. *(model tests for
      `match_name_labels`/`is_name_label`; controller tests for the point
      shape + owner; headless end-to-end round-trip.)*

Suggested prompt:
> [Opus] Do Item 22 of EVO/iprj_designer/ROADMAP.md (needs Item 21): add a
> Text Label draw kind (create/edit/move, FontSize 12 / white /
> rotation-in-degrees defaults), assign lineals/centerlines/labels by active
> sensor with an explicit General option, and auto-create/rename/re-derive a
> no-rotation centerline-name label at each centerline's far end. Tests for
> the model-side association + GUI finishing pass + DESIGN_HISTORY.

---

## 10 — Webserver Deployment (Target: Opus)

Carried over unchanged from the earlier "Phase 5" round (not started, not
dropped). Big enough that its planning half may still warrant its own
session before the implementation, but both halves are Opus now — no
cross-model hand-off.

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
> is in scope. Land the plan first (decision document, no code), then
> implement it in a following session.

---

## Future (not yet scoped)

- Display objects from a live stream.
- Upload and play back a recorded playback file.
- Integrate the line-up/calibrate workflow (see
  `~/pyatspm/src/atspm/video/calibrate.py`) more directly into the app.
