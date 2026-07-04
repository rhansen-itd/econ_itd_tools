# Roadmap — iprj Designer (Phase 2 & Refinement)

Phase 1 (Sessions 1–7: data model, drawing core, attributes, templates,
centerline placement) is complete — see [[DESIGN_HISTORY.md]] for that build
history and the decisions made along the way.

Work below is broken into phases, targeted at different Claude models per
[[CLAUDE.md]] model-routing rules:
* **Fable** — pure Python math, geometry, schema, and tests (`model/`).
* **Sonnet** — NiceGUI wiring, UI interactions, file management (`gui/`).
* **Opus** — cross-module architectural planning.

Tell the agent "do Phase X of ROADMAP.md" (or "Phase X.Y") to run a scope
below; check off items and log decisions in [[DESIGN_HISTORY.md]] as they
land, the same way Phase 1 sessions did.

---

## Phase 1 — Quick Wins, Fixes & File Management (Target: Sonnet)

UI and state-wiring tasks that require no complex geometry or schema changes.

Scope:
- [x] Update documentation terminology: replace references of
      "Wavetronix/SmartSensor" with "Econolite Evo (Epiq)".
- [x] Fix background visibility toggle.
- [x] Fix Template Undo stack: ensure the `DrawingController` captures the
      bulk insertion of a template as a single, undoable operation that
      removes all associated zones.
- [x] Add 2-Point Ruler Tool: a simple canvas tool for quick distance checks
      (click to start, drag to see live distance in feet, click to end).
- [x] In-App File Management: add UI elements to start a New file, Open an
      existing `.iprj` file, and Upload a background PNG without restarting
      the app via CLI.

Suggested prompt:
> [Sonnet] In EVO/iprj_designer, do Phase 1 of ROADMAP.md: execute the quick
> UI wins, fix the undo stack for templates, add the 2-point ruler, and
> build the in-app file management UI.

## Phase 2 — Domain Accuracy & Core Geometry (Target: Fable)

Pure math and data schema work. *(Note: ask user for exact Econolite vehicle
codes, speeds, and direction codes before starting.)*

Scope:
- [x] Fix Loop Types mapping: update to correct vendor specs (0=Motion,
      1=Presence, 2=Sidewalk — vendor-UI names, confirmed 2026-07-03).
- [x] Update condition schema to accurately support different condition
      types (direction, speed, vehicle type) and their specific fields.
- [x] Build pure-Python geometry/schema models for Ignore Zones and generic
      Lineals.
- [x] Implement rotation math: calculate rotation of polygons around a
      calculated centroid or a user-provided 2D pivot point.

Suggested prompt:
> [Fable] In EVO/iprj_designer, do Phase 2 of ROADMAP.md. First, ask me for
> the specific Econolite codes. Then, update the schema/domain accuracy for
> loops and conditions, build the pure-Python models for Ignore
> Zones/Lineals, and implement the planar geometry math for element
> rotation.

## Phase 3 — UX Overhaul & Multi-Select

Split into planning and UI implementation.

### Phase 3.1 — Toolbar & Mode Planning (Target: Opus)

Scope:
- [x] Design a dynamic, context-sensitive command palette to replace the
      overflowing toolbar.
- [x] Plan the restructuring of "Draw" mode into specific sub-modes (Loop,
      Lineal, Ignore Zone).
- [x] Evaluate if a default "Pan" mode is necessary or can be handled
      implicitly.
- [x] Output a design document/plan for Sonnet to implement.

Output: [[PHASE3_UI_PLAN.md]] — two-tier toolbar (persistent chrome + per-tool
context bar), 6 primary tools with sub-types, a `DrawKind` draw-target
descriptor generalizing `DrawingController`, Pan dropped for a default Select
tool with implicit pan gestures, and multi-select as a selection set reusing
the existing `("batch", …)` undo entry. Includes a Fable-first / Sonnet-second
3.2 sub-session sequencing (3.2a controller + model, 3.2b toolbar, 3.2c
multi-select/rotate).

Suggested prompt:
> [Opus] In EVO/iprj_designer, do Phase 3.1 of ROADMAP.md: output a UI
> architecture plan to reorganize the toolbar, restructure the draw modes,
> and handle multi-select gracefully.

### Phase 3.2 — UI Implementation

The Phase 3.1 plan ([[PHASE3_UI_PLAN.md]] — the source of truth for all three
sub-sessions below) splits this into a **Fable-first pure-python pass** then two
**Sonnet** wiring passes: the controller/model generalization (draw-kind
abstraction, multi-select state, lineal round-trip) lands finished code for the
NiceGUI work to sit on, per [[CLAUDE.md]] routing. Do 3.2a → 3.2b → 3.2c in
order.

#### Phase 3.2a — Controller & model (Target: Fable)

Scope (plan §4, §6, §7 — pure-python, pytest-covered, no GUI imports):
- [x] `DrawKind` draw-target descriptor + generalize
      `DrawingController._commit_zone`; add the 2-click `segment` draw path;
      retarget the controller between element lists (event zones / ignore
      zones / lineals).
- [x] Multi-select state (`selection` list + `anchor`), a marquee hit helper in
      `model/geometry.py`, and group move/delete/nudge as `("batch", …)` undo
      ops (reusing the existing batch entry).
- [x] `load_lineals`/`save_lineals` for non-chain stray Lineals, with the
      endpoint-coincidence guard (plan §4.3).
- [x] Accelerator fixes at the seam (plan §2.1): drop `d` from `_key_draw`'s
      dimension trigger (digits still start it); remove the `l`/`e` set-mode
      shortcuts from `DrawingController.key`.

Suggested prompt:
> [Fable] In EVO/iprj_designer, do Phase 3.2a of ROADMAP.md per
> PHASE3_UI_PLAN.md §4/§6/§7: the `DrawKind` draw-target abstraction,
> multi-select controller state with batch-undo group ops, the marquee/group
> geometry helpers, generic-lineal round-trip, and the §2.1 accelerator-seam
> fixes — all pure-python, pytest-covered, no GUI imports.

#### Phase 3.2b — Toolbar & draw kinds (Target: Sonnet)

Scope (plan §3, §4, §5):
- [x] Two-tier toolbar: persistent chrome row + per-tool context bar via
      `set_visibility` toggles; File menu; Draw/Measure sub-type toggles;
      accelerators per plan §2.1.
- [x] Drop Pan; default to Select; space/middle-drag pan; marquee on
      empty-canvas left-drag.
- [x] Wire the three draw kinds (Loop / Ignore Zone / Lineal) to the sub-type
      toggle; render generic lineals distinctly from centerlines; surface the
      10/100 cap `ValueError`s as notifications.

Suggested prompt:
> [Sonnet] In EVO/iprj_designer, do Phase 3.2b of ROADMAP.md per
> PHASE3_UI_PLAN.md §3/§4/§5: build the two-tier toolbar, drop Pan for a
> default Select tool with implicit pan, and wire the Loop/Ignore/Lineal draw
> kinds (built on 3.2a's `DrawKind`) to the sub-type toggle.

#### Phase 3.2c — Multi-select sync & rotation (Target: Sonnet)

Scope (plan §6.4, §6.5):
- [x] Multi-select GUI sync: zone table `selection="multiple"`, `svg()`
      highlights for every selected zone, marquee rectangle + rotation-pivot
      preview.
- [x] Wire the 2-click rotate workflow to `geometry.rotate_points` /
      `rotation_angle_deg`; rotating an attached zone detaches it (plan §6.4).

Suggested prompt:
> [Sonnet] In EVO/iprj_designer, do Phase 3.2c of ROADMAP.md per
> PHASE3_UI_PLAN.md §6: sync multi-selection to the zone table and overlay,
> and add the 2-click rotate workflow wired to Fable's rotation math
> (rotation detaches attached zones).

## Phase 4 — Advanced Template Engine

Replacing the old static template logic with a hybrid mathematical approach
where math seeds flexible defaults.

### Phase 4.1 — Math & Schema (Target: Fable)

Scope:
- [x] Update `model/templates.py` to use `extension_time` and detector length
      alongside approach speed to calculate continuous dilemma zone coverage.
      **Crucial intent:** These ITE kinematic calculations are meant to *seed*
      the default values (setback, length) for the template generation,
      creating a smart baseline that the schema/UI allows the user to
      explicitly override. Do not make the math a rigid constraint.
- [x] Add schema support for dynamic placeholders that get injected at
      placement time: approach direction, relevant phases, and **Base Output**.
- [x] Refactor output numbering to a Base + Offset model: the template schema
      should store an `output_offset` (e.g., 0, 1, 2). At placement time, the
      user provides a `Base Output` (e.g., 32), and the assigned output is
      calculated as `Base Output + output_offset`.
- [x] Add schema support for lane-spanning detectors (e.g.,
      `spanning_lanes: [1, 2]`).
- [x] Define anchor point logic (Station 0) defaulting to the lane line
      between the exclusive left-turn lanes and the thru lanes (i.e., the
      right side of the last exclusive left-turn lane).

**Notes for the Fable session (keep the engine flexible):**
- *Seed, don't constrain.* Write every kinematic result (setback, length, the
  extension-driven spacing) into the schema as an **editable default**; the
  expansion reads the stored value, so a 4.2 user override fully replaces the
  computed one. The math runs to populate defaults, not as a placement-time
  hard rule.
- *Continuous coverage* = no detection gap between successive advance
  detectors: size/space them so a vehicle at design speed stays held by the
  controller (detector length + `extension_time` gap-out) from one zone into
  the next. Document the formula and the assumed `extension_time`, the way
  Session 6.2 documented its PRT/deceleration constants (see the decisions log
  / [[DESIGN_HISTORY.md]]).
- *One channel — output only.* The detection unit's **output channel maps 1:1
  to the controller input it drives**, and `.iprj` stores only `OutputNumber`,
  so this software numbers by *output* exclusively (the redundant "input" alias
  was removed — see the 2026-07-03 decisions-log entry). The numbering model is
  a single space: `Base Output + output_offset`, no separate input number.
- *Placeholders vs. literals.* `direction`/`thru_phase`/`lt_phase` are baked
  into today's template JSON; the new schema should let each be **either a
  fixed value or a placeholder** resolved at placement. Existing templates
  (baked values) must still load — treat a present value as a literal, an
  absent/sentinel one as "prompt at placement."
- *Anchor changes the existing reference convention.* Session 6.2 placed from
  the leftmost lane's left edge; Station 0 now sits at the last
  exclusive-left/thru lane line, so lateral offsets are recomputed relative to
  the new anchor — re-pin the appendix acceptance case to it.
- *Fable budget* (per [[CLAUDE.md]] — one bounded piece per session): run 4.1
  as two passes — **schema first** (placeholders, Base+Offset, `spanning_lanes`,
  anchor config), **then the kinematic seeding** that fills the defaults.

Suggested prompt:
> [Fable] In EVO/iprj_designer, do Phase 4.1 of ROADMAP.md: update the template
> math to include extension times for continuous dilemma zone coverage. Use
> this math to *seed* default schema values, not constrain them. Implement the
> Base Output + output_offset numbering logic, add schema support for
> lane-spanning, and configure the anchor point logic.

### Phase 4.2 — Grid Editor UI (Target: Sonnet)

Scope:
- [x] Build a standalone template editor using NiceGUI Flexbox/CSS Grid columns
      for physical lanes.
- [x] Allow merging cells across lanes (using the Phase 4.1 `spanning_lanes`
      schema).
- [x] Allow user overrides of Fable's mathematically pre-populated (seeded)
      kinematic values.

Suggested prompt:
> [Sonnet] In EVO/iprj_designer, do Phase 4.2 of ROADMAP.md: build the CSS
> Grid/Flexbox lane column UI for editing templates, supporting merged cells
> across lanes and overriding the seeded kinematic values.

### Phase 4.3 — Canvas Placement UI (Target: Sonnet)

Scope:
- [x] Wire the new template engine to the canvas.
- [x] Prompt the user for the dynamic placeholders (phase, direction, and Base
      Output) at placement time.
- [x] Snap the template to the defined anchor point on the canvas.

Suggested prompt:
> [Sonnet] In EVO/iprj_designer, do Phase 4.3 of ROADMAP.md: wire the advanced
> template engine to the canvas and add the UI prompt for dynamic placeholders
> (including Base Output) during placement.

## Phase 5 — Webserver Deployment (Future)

### Phase 5.1 — Architecture Plan (Target: Opus)

Scope:
- [ ] Decide how per-user/project state is isolated across concurrent
      NiceGUI sessions.
- [ ] Decide project file management approach (server-side open/save vs.
      upload/download) and whether auth is in scope.
- [ ] Output a plan for Phase 5.2 — this phase is a decision document, not
      code.

Suggested prompt:
> [Opus] In EVO/iprj_designer, do Phase 5.1 of ROADMAP.md: design
> multi-session state isolation for the NiceGUI app, a project file
> management approach (server-side vs. upload/download), and whether auth
> is in scope. Produce a plan for Phase 5.2 to implement — no code changes
> this session.

### Phase 5.2 — Implementation (Target: Sonnet)

Scope (define fully once 5.1 lands):
- [ ] Implement the Phase 5.1 plan: multi-session safety and project file
      management, harden NiceGUI serving for other users.
- [ ] Packaging (`pip install` entry point or container).

Suggested prompt:
> [Sonnet] In EVO/iprj_designer, do Phase 5.2 of ROADMAP.md: implement the
> Phase 5.1 architecture plan — multi-session state isolation, project file
> management, and hardened NiceGUI serving — then package as a
> `pip install` entry point or container.
