# Roadmap — iprj Designer

Three rounds of work are complete and archived in [[DESIGN_HISTORY.md]], not
listed here anymore: the Phase 1 MVP (Sessions 1–7 — data model, drawing
core, attributes, templates, centerline placement), a second "Phase 1–4"
round (quick wins/file management, domain accuracy, the toolbar/multi-select
overhaul, and the advanced template engine), and a third numbered-items
round (Items 1–9 and 11 — background-tool rework, per-zone-type conditions,
sensor management, edit-mode/vertex tools, terminology renames, free-draw
polygons, centerline re-stationing, canonical origin, and the multi-sensor
2-file split). Reusing "Phase 1" for two unrelated rounds is exactly the
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
  rule. (Older completed items below — now archived — used a "Fable then
  Sonnet" hand-off that this routing has retired.)
- Tell the agent "do Item N of ROADMAP.md" (or reference it by name) to run
  a scope below; check off items and log decisions in [[DESIGN_HISTORY.md]]
  as they land, the same way every round so far has.

"Future" items at the bottom aren't scoped yet (no Target/Scope/prompt) —
they need a planning pass before they're actionable.

---

# Owner batch — added 2026-07-05

Nine items grouped into four clusters. Numbers **12–20** are new stable IDs
(1–9 and 11 are archived; 10 is below). Within a cluster, file order is
priority order; the clusters as a whole sit **ahead of Item 10** (webserver
deployment) — reorder if that's wrong, the numbers don't move.

Cross-item note: Item 15 (keep detector rows in order) is a bug fix on the
*current* row-per-detector table; Item 16 (side-by-side layout) would
replace that table. If 16 lands first, 15 folds into it — do 15 as the
standalone quick fix only while the current table is still in use.

---

**Cluster A — Quick UI fixes**

## 12 — Move-along-centerline button: Edit mode only (Target: Sonnet)

The move-along-centerline action (`gui/app.py` ~947/2242, Item 8's tool)
currently shows up under Draw, Background, and elsewhere. It only makes
sense on a selected, already-placed zone.

Scope:
- [x] Show/enable the button only in Edit mode (with a zone selected);
      hide it under Draw, Background, and any other mode.

Suggested prompt:
> [Sonnet] Do Item 12 of EVO/iprj_designer/ROADMAP.md: scope the
> move-along-centerline button to Edit mode only (hidden under Draw,
> Background, etc.). Finishing pass included.

## 13 — Clear-ruler icon (Target: Sonnet)

The "clear ruler" control next to the ruler toggle reuses the old waypoint
"marker" icon — a relic. Prefer a ruler-with-an-x style icon (mirroring the
existing waypoint marker but ruler-themed); a plain delete/clear icon is an
acceptable fallback since it sits right next to the ruler icon.

Scope:
- [x] Swap the clear-ruler icon to a ruler-with-x if one is available in
      the icon set, else a generic delete/clear icon.

Suggested prompt:
> [Sonnet] Do Item 13 of EVO/iprj_designer/ROADMAP.md: replace the
> clear-ruler icon (currently the old waypoint marker) with a ruler-with-x
> icon if available, otherwise a delete/clear icon.

---

**Cluster B — Template editor**

## 15 — Keep advanced detector rows in stop-bar order (Target: Opus)

Placed advanced detectors render swapped: the ones nearest the stop bar end
up at the *bottom* of the table. Rows should stay in a consistent order
relative to the stop bar. (See cross-item note above re: Item 16.)

Scope:
- [x] Order detector rows consistently by distance from the stop bar (fix
      the reversed sort); add a model/expansion test if the ordering is
      decided in `model/templates.py`. *(Done as part of the Item 17
      restructure — `seed_detectors` now emits rows in ascending distance
      from the stop bar; see the 2026-07-05 decisions-log entry.)*

Suggested prompt:
> [Opus] Do Item 15 of EVO/iprj_designer/ROADMAP.md: advanced detectors in
> the template editor render in reversed order (nearest the stop bar at the
> bottom). Order rows consistently by distance from the stop bar and test.

## 17 — Rename dilemma → decision; advance/decision taxonomy + even spacing (Target: Opus)

Terminology and detector-chain restructuring in `model/templates.py`
(`DETECTOR_KINDS`, the dilemma/advance expansion) and its editor labels.

Scope:
- [x] Rename the `dilemma` detector kind to `decision` everywhere
      (model, GUI labels, docs, tests); update IPRJ_FORMAT.md if the kind
      string is part of the file-format contract. *(Kind string is internal
      to the template JSON, not the exported iprj contract — IPRJ_FORMAT.md
      unchanged; old `dilemma` kinds migrate on load.)*
- [x] Only the **first** detector (furthest from the stop bar) is
      `advance` and keeps the lane-by-lane option.
- [x] Every detector between that advance detector and the stop-bar-side
      decision detector(s) is also a `decision` detector, defaulting to
      spanning the thru lanes.
- [x] Space the decision detectors **evenly**: keep computing the *count*
      needed to travel between detectors without gapping out (from speed +
      extension time), but once the count is fixed, distribute the
      intermediate detectors so the middle spacing is centered rather than
      leaving the remainder as one uneven gap.

Suggested prompt:
> [Opus] Do Item 17 of EVO/iprj_designer/ROADMAP.md: rename the dilemma
> detector kind to "decision"; make only the furthest-from-stop-bar
> detector "advance" (lane-by-lane), all intermediates "decision" spanning
> thru lanes by default, and space the decision detectors evenly (fixed
> count from speed/extension time, then centered spacing). Tests + docs.

## 18 — Set decision/advance lengths before ITE seeding (Target: Opus)

In the template editor's top (pre-seed) section, expose editable decision
and advance detector **lengths** so they're set before seeding with ITE
kinematics, rather than only editable after expansion.

Scope:
- [x] Add decision- and advance-length inputs to the top/seeding section
      of the template editor; feed them into `model/templates.py`
      expansion (replaces the hardcoded `DILEMMA_LENGTH_FT` / advance
      length defaults as seed values). *(New `ApproachTemplate`
      `decision_length_ft` / `advance_length_ft` fields, default 20 / 10;
      "Decision len (ft)" / "Advance len (ft)" inputs in the editor.)*
- [x] Tests for expansion honoring the supplied lengths.

Suggested prompt:
> [Opus] Do Item 18 of EVO/iprj_designer/ROADMAP.md: let the user set
> decision and advance detector lengths in the template editor's top
> section before seeding with ITE kinematics; thread them through model
> expansion and test.

## 16 — Side-by-side detector table (adjacency rows) (Target: Opus) — larger, optional

Owner's original vision for the template editor table; **nice-to-have, not
required** — current row-per-detector table works, this is a layout
redesign. Big enough to likely want its own planning pass. Do after Items
15/17/18 land on the current table.

Vision:
- One **row per adjacency group**, not per detector. Detectors that overlap
  at all (even offset by 10' if they're 15' long, so they're side by side
  somewhere) share a row.
- Each cell merges the row-info tile fields (name, lanes, phase, output)
  with the detector tile's lane-specific fields, displayed **side by side**
  across lane columns instead of stacked rows.
- Manual (unseeded) mode: "Add row" creates a row of empty cells (a `+` per
  column). Clicking `+` / "add detector" opens the full detector info for
  that cell. Adjacent lane columns then show `+`; clicking one seeds
  distance/length from the initiating detector and inherits lane info from
  its column. Filling a cell's column info stretches the detector, spanning
  multiple columns when applicable.

Scope:
- [ ] Plan the adjacency-grouping + side-by-side table (decision doc first).
- [ ] Implement the grouped table and manual add-detector-per-cell flow.
- [ ] Tests for the adjacency grouping logic (pure model, headless).

Suggested prompt:
> [Opus] Plan then implement Item 16 of EVO/iprj_designer/ROADMAP.md: the
> side-by-side detector table (one row per adjacency group, merged
> row-info + detector fields across lane columns, manual add-per-cell with
> seeded/inherited values). Land a plan first; note it's optional if the
> grouping logic proves too costly.

---

**Cluster C — Centerline & template placement**

## 19 — Place-along-centerline: snap toggle + optional per-centerline target (Target: Opus)

Template placement along a centerline snaps far too aggressively (snap
distance much too high). Make it controllable from the templates toolbar.

Scope:
- [x] Add a "place along centerline" toggle to the **templates** toolbar
      (mirroring the existing snap toggle) so literal centerline snapping
      can be turned off. *(the "along CL" switch; `template_follow_centerline`)*
- [x] Fix/tune the snap distance so it isn't overwhelmingly strong when on.
      *(root cause: `centerline_for` had **no** threshold — any click snapped
      to the nearest datum however far. Added a lateral `CENTERLINE_SNAP_FT`
      = 40 ft threshold via the pure `geometry.nearest_centerline`.)*
- [x] Optional (scope permitting): a place-along-centerline **dropdown** in
      the templates toolbar (like the centerline toolbar's existing
      dropdown) to place along one *selected* centerline only — no
      nearest/snap logic; default none selected. *(the "pick CL" dropdown;
      `template_centerline_idx`, an explicit pick bypasses the threshold.)*

Suggested prompt:
> [Opus] Do Item 19 of EVO/iprj_designer/ROADMAP.md: add a place-along-
> centerline toggle to the templates toolbar and fix the far-too-strong
> snap distance. If cheap, also add a dropdown to place along one selected
> centerline only (default none). Tests where placement math is in model/.

## 20 — Nameable centerlines per session (Target: Sonnet)

Centerlines import with generic names; let the user rename them within a
session (e.g. `N_CL` for the north approach) so template snapping/placement
(Item 19) can reference them by name. Session-only — no need to persist to
the iprj on import.

Scope:
- [x] Editable centerline name in the centerline toolbar, held in session
      state; surface the name wherever centerlines are selected (incl.
      Item 19's dropdown). *(`CenterlineController.name`; `centerline_label`
      falls back to C{n}; both the active-centerline selector and the
      template "pick CL" dropdown show it, done in the same Opus session as
      Item 19 since the two are tightly coupled.)*

Suggested prompt:
> [Sonnet] Do Item 20 of EVO/iprj_designer/ROADMAP.md: make centerlines
> renameable within a session from the centerline toolbar (session state,
> not persisted), and use those names in centerline pickers.

---

**Cluster D — Performance**

## 14 — Zoom freeze / server disconnect on large files (Target: Opus, Fable escalation)

Zooming in too quickly — seemingly on files with large backgrounds and/or
many elements — freezes the app; it "loses connection" to the server
component, then reconnects a few moments later back at the initial zoomed-
out view. Owner is open to Fable if Opus judges the fix a stretch.

Scope:
- [x] Reproduce and characterize (large-background vs. element-count vs.
      zoom-event rate; NiceGUI/websocket round-trip vs. redraw cost).
      *(Profiled banks.iprj: server `svg()` is 7.8 KB / 0.14 ms — not the
      cost. It's zoom-event **rate**: unthrottled wheel → per-event browser
      re-parse of the SVG overlay + re-composite of the 9.6 MP background
      saturates the main thread; the missed socket heartbeat drops the
      connection, and fit-on-reload snaps back to zoomed-out.)*
- [x] Identify the bottleneck (image re-encode per zoom? full-canvas
      redraw? unthrottled zoom events flooding the socket?). *(Not image
      re-encode — background is a static file scaled by CSS transform.
      Bottleneck = unthrottled per-event round-trip forcing a client-side
      overlay re-parse + big-image re-composite every frame.)*
- [x] Optimize (throttle/debounce zoom, cache/downscale the background,
      avoid re-sending large payloads per frame — whatever the profile
      shows). *(Moved the zoom transform client-side — see DESIGN_HISTORY
      Session "Item 14". Verified against banks.iprj: 400 native wheel
      events processed in 12 ms, socket stays connected, zoom is lossless.)*

Routing: Opus investigates and fixes; per CLAUDE.md, escalate the
narrowed-down bug to Fable only if Opus can't land it after honest passes.
**Resolved by Opus — no Fable escalation needed.**

Suggested prompt:
> [Opus] Do Item 14 of EVO/iprj_designer/ROADMAP.md: investigate the
> zoom-in freeze / server disconnect on large-background / many-element
> files, find the bottleneck (image re-encode, full redraw, or unthrottled
> zoom events over the socket), and optimize. Escalate the narrowed bug to
> Fable only if it resists a fix.

---

## 10 — Webserver Deployment (Target: Opus)

The only remaining scoped item; carried over unchanged from the earlier
"Phase 5" round (not started, not dropped). Big enough that its planning
half may still warrant its own session before the implementation, but both
halves are Opus now — no cross-model hand-off.

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
