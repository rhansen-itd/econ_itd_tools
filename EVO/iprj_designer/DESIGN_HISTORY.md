# Design History — iprj Designer

This file archives the build history and design decisions from the Phase 1
MVP (Sessions 1–7): the pure-Python iprj data model, the NiceGUI drawing/edit
core, zone attributes and iprj write-out, approach templates, and centerline
datum placement — plus every round of work since (quick wins/file
management, domain accuracy, the toolbar/multi-select overhaul, and the
advanced template engine, all logged in the decisions log below as they
landed). See ROADMAP.md for what's currently planned; as of 2026-07-04 it
organizes work as named, numbered (stable-ID, not sequential) items ordered
by priority rather than sequential phases — see its intro for why.

Work was originally broken into sessions sized for one focused Claude Code
sitting. Each session ended with something runnable/testable and a short
update to ROADMAP.md (check the boxes, note decisions).

**Architecture rule that made the phasing work:** everything under `model/`
(iprj I/O, units, geometry, templates) is pure Python with no GUI imports.
The GUI is a thin shell over it. This is what lets the eventual webserver
upgrade — and even a framework swap — happen without touching the core. (Now
codified in [[CLAUDE.md]].)

Layout as code landed:

```
EVO/iprj_designer/
├── README.md / ROADMAP.md / IPRJ_FORMAT.md / CLAUDE.md
├── model/          # pure python: iprj_io.py, units.py, geometry.py, templates.py
├── gui/            # framework-specific shell
├── templates/      # approach-template JSON files
└── tests/          # round-trip + geometry tests (pytest)
```

---

## Session 1 — Data model & iprj round-trip (no GUI)

The foundation everything else sits on; also resolves the format unknowns in
IPRJ_FORMAT.md.

Scope:
- [x] Dataclasses: `Project`, `Background/Calibration`, `Sensor`, `EventZone`,
      `Condition`, `IgnoreZone`, `Lineal`, `TextLabel` (`model/iprj_io.py`)
- [x] `load_iprj(path) -> Project` and `save_iprj(project, path)` with
      byte-faithful attribute round-trip (order/format tolerant)
- [x] pytest round-trip tests against every file in `sites/**/*.iprj`
      (29/29 files, `tests/test_roundtrip.py`)
- [x] `units.py`: ft↔m↔px conversions; calibration constructors
      (image-width-known, two-points-known-distance); note the scale is
      re-derived from the reference pair, not the rounded `MeterPerPixel`
- [x] Resolve the IPRJ_FORMAT.md verification checklist; update that doc
      (two items remain open pending vendor software — see doc)
- [x] Small script: `scripts/overlay_zones.py` — zones verified landing on
      the lanes for Banks and US95&SH8

Suggested prompt:
> In EVO/iprj_designer, do Session 1 of ROADMAP.md: build the pure-Python iprj
> data model and load/save round-trip per IPRJ_FORMAT.md, with pytest tests
> against all iprj files under sites/. Resolve the open questions in
> IPRJ_FORMAT.md and update it with findings. Finish with a quick matplotlib
> overlay script proving zones land correctly on the background image.

## Session 2 — Framework spike & scaled image viewer

Decision session: pick the GUI framework by building the same tiny prototype
in the candidates and comparing feel.

Leading candidate: **NiceGUI** — Python-only, browser-based (so the webserver
upgrade is "already done"), `interactive_image` gives mouse down/move/up with
image coordinates plus an SVG overlay layer, `ui.keyboard` for key commands,
and toolbars/dialogs are trivial later. Cost: zoom/pan and hover-coordinate
readout must be built by hand (viewBox math).
Alternative: **Dash/plotly** — zoom + hover coords for free (the part liked in
the EVO plotly tools), but mousemove-granularity drawing and mid-draw keyboard
dimension entry fight the framework (server round-trips, JS escape hatches).
Fallback if neither feels right: FastAPI + a small JS canvas (Konva.js), still
driving the Python model.

Scope:
- [x] Spike A (NiceGUI): load an image, zoom/pan, live cursor readout in
      feet, click to drop a marker — all worked; Spike B (Dash) not needed
- [x] Calibration UI: enter known image width/height in feet, OR click two
      points and type the distance; writes the model's Calibration
      (`units.calibrate_*` on the loaded `Background`)
- [x] Record the framework decision + rationale at the bottom of this file
- [x] Keep: `gui/app.py` opens a project (new-from-image or existing .iprj
      via Session 1 loader) and renders background + existing zones;
      zoom/pan math isolated in `gui/viewport.py` (pure python, tested)

Suggested prompt:
> In EVO/iprj_designer, do Session 2 of ROADMAP.md: spike the GUI framework
> (start with NiceGUI) — scaled background image viewer with zoom/pan, live
> cursor position in feet, and both calibration methods (known image
> width/height; two clicked points + known distance). Render existing zones
> from an iprj loaded with the Session 1 model. Record the framework decision
> in ROADMAP.md.

## Session 3 — Drawing core

Port the interaction model of pyatspm's `video/calibrate.py`
(`~/pyatspm/src/atspm/video/calibrate.py`) to the chosen framework, upgraded
for real-world dimensions.

Scope:
- [x] Free draw: click 4 corners → loop polygon
- [x] **Dimensioned draw** (primary workflow): click point 1, move mouse to
      set direction, press `d` (or start typing digits) → enter first length
      (e.g. 10 ft along the click direction = short side), then second length
      (e.g. 20 ft, extruded toward the mouse side) → rectangle placed
- [x] Snapping (toggle, like `g` in the video tool): snap to other zones'
      vertices; edge midpoints included as snap candidates for adjacent lanes
- [x] Edit mode: select (click / `n`/`b` cycle) zones, drag vertex, drag body
      to move, **Ctrl-drag to copy** — copy is the fast path for laying out
      identical lane loops
- [x] Undo (point-level while drawing, op-level after: add/move/delete),
      delete (`x`/Del)
- [x] Status line showing mode / snap / pending dimension entry

Suggested prompt:
> In EVO/iprj_designer, do Session 3 of ROADMAP.md: implement the drawing
> core — free 4-point loops, dimensioned rectangle drawing (click, aim,
> type lengths in feet), vertex snapping, edit mode with move/copy/delete and
> undo. Use ~/pyatspm/src/atspm/video/calibrate.py as the behavioral
> reference for the state machine and snapping.

## Session 4 — Attributes & full iprj write-out (MVP complete)

Scope:
- [x] Per-zone properties: name, `PhaseNumber`, `OutputNumber` (auto-increment
      on consecutive draws/copies), `ZoneType`, delay/extend
- [x] Sensor management: place/move sensor(s), azimuth, height; assign zones
      to a sensor
- [x] Basic Conditions editing (enable, output, class, velocity range) —
      table form is fine
- [x] Save to `.iprj` (embed background PNG base64) and reload — verified by
      pytest + Playwright; loading in the vendor software still unverified
      (no vendor software on this machine — see the open item in
      IPRJ_FORMAT.md)
- [x] Open-existing-iprj → edit → save workflow solid (Playwright run on
      banks.iprj: sensor switch, zone dialog, draw, save-as, reload)

Suggested prompt:
> In EVO/iprj_designer, do Session 4 of ROADMAP.md: zone attribute editing
> (phase, output with auto-increment, type, name), sensor placement and zone
> assignment, basic conditions, and full save-to-iprj including the embedded
> background image. End-to-end: new project from image → calibrate → draw →
> attributes → save → reopen.

## Session 5 — Toolbar & UX pass

Scope:
- [x] Toolbar for tool/mode selection (keyboard shortcuts stay as
      accelerators) — this was planned-for, now build it
- [x] Zone list/table panel synced with canvas selection; edit attributes
      from the table
- [x] Visual polish: colors by phase, labels on zones, selected-zone
      highlight, layer toggles (background/zones/sensors)
- [x] Keyboard/interaction refinements discovered while using Sessions 3–4

Suggested prompt:
> In EVO/iprj_designer, do Session 5 of ROADMAP.md: add the toolbar, a synced
> zone table panel, and visual polish (phase colors, labels, layer toggles).
> Keep all keyboard shortcuts working as accelerators.

## Session 6 — Approach templates

Split by model per [[CLAUDE.md]] model-routing: schema/UI sub-sessions go to
Sonnet, the pure-math expansion goes to Fable. Do 6.1 → 6.2 → 6.3 in order —
each hands a concrete artifact to the next (schema → expansion function →
UI wired to it).

### Session 6.1 — Template schema & basic inputs (Target: Sonnet)

Scope:
- [x] Template schema (JSON in `templates/`): lane configuration (e.g.
      `L | T | T | R` with widths), approach speed, count loops on/off,
      lane-by-lane advance detectors on/off, starting input/output number,
      approach direction, thru phase, LT phase
- [x] Minimal UI inputs for approach speed / lane configuration (form only —
      no placement logic yet; that's 6.3)
- [x] Template create/edit stays minimal (edit JSON + reload) this session

Suggested prompt:
> [Sonnet] In EVO/iprj_designer, do Session 6.1 of ROADMAP.md: define the
> approach-template JSON schema (lanes, widths, speed, detector toggles,
> starting input/output, direction, phases) and a basic NiceGUI form for
> entering it. No expansion/placement logic yet — that's Fable's Session 6.2.

### Session 6.2 — Template expansion math (Target: Fable)

Scope:
- [x] `model/templates.py`: expand a template into a detector list — count
      loops (5'×lane at stop bar offset), stop-bar zones (30'×lane),
      dilemma-zone and advance detectors placed by **ITE kinematic
      calculations** from approach speed (document formulas + assumed
      perception-reaction time and deceleration in the module)
- [x] Naming convention auto-generated (e.g. `SBL Count`, `Ph 4 SBT Stop Bar 1`,
      `Ph 4 Dilemma`) with sequential input numbers from the starting input
- [x] Pure-python, pytest-covered against the acceptance case in the
      appendix below — no GUI imports

Suggested prompt:
> [Fable] In EVO/iprj_designer, do Session 6.2 of ROADMAP.md: implement
> `model/templates.py` — pure-python expansion of the Session 6.1 schema
> into a detector list, using ITE kinematic calculations for dilemma-zone
> and advance-detector placement from approach speed, with auto
> naming/numbering. Document the kinematic formulas and assumed
> perception-reaction time/deceleration in the module. Write pytest
> coverage against the example template table in the ROADMAP appendix
> (Session 6 acceptance case). No GUI code — hand off a function callable
> with a template + a stop-bar reference point/direction.

### Session 6.3 — Wire expansion into the canvas (Target: Sonnet)

Scope:
- [x] Placement UI: pick template, click stop-bar reference point, aim
      direction (2nd click or mouse) → calls `model/templates.py` and
      places all resulting zones
- [x] Wire the Session 6.1 form values into the expansion call

Suggested prompt:
> [Sonnet] In EVO/iprj_designer, do Session 6.3 of ROADMAP.md: wire the
> Session 6.2 template-expansion function into the canvas — pick a
> template, click a stop-bar reference point, aim direction, and place all
> resulting zones via the existing DrawingController/insert_zone path.

## Session 7 — Centerline datum placement

Same split: the station/offset math is Fable's, the drawing UI is
Sonnet's. 7.3 (persistence) and 7.5 (the placement refactor) are both
`model/`-shaped work — default both to Fable per [[CLAUDE.md]]
model-routing; only pull in Opus first on 7.5 if it turns out to need
re-deciding how re-stationing interacts with the undo model (an
architecture question, not a math one — 7.3's persistence approach is
already decided, see the Session 7.2 decisions-log entry below).

### Session 7.1 — Station/offset geometry engine (Target: Fable)

Scope:
- [x] Station/offset engine in `model/geometry.py`: point + orientation at
      any station along a polyline (point-to-point segments, no arcs)
- [x] Pure-python, pytest-covered

Suggested prompt:
> [Fable] In EVO/iprj_designer, do Session 7.1 of ROADMAP.md: implement a
> station/offset engine in `model/geometry.py` — given a point-to-point
> polyline (station 0 at one end), return point + orientation at any
> station/offset. Pure python, pytest-covered, no GUI imports.

### Session 7.2 — Centerline drawing UI (Target: Sonnet)

Scope:
- [x] Draw an approach "centerline" polyline on the canvas (datum: taken
      along the line between leftmost thru lane and LT lane), station 0 at
      the stop bar
- [x] Edit centerline after the fact (stretch: keep simple if hairy)

Suggested prompt:
> [Sonnet] In EVO/iprj_designer, do Session 7.2 of ROADMAP.md: add
> centerline polyline drawing/editing on the canvas (station 0 at the stop
> bar), using the Session 7.1 `model/geometry.py` engine for any live
> station readout.

### Session 7.3 — Centerline persistence in `.iprj` (Target: Fable)

The vendor format has no native polyline entity — the closest is `Lineal`
(`model/iprj_io.py`), a fixed 2-point line. Persist the centerline through
that instead of adding a new schema concept: one `Lineal` per segment on
save, chained back into an ordered polyline by shared vertices on load.

Scope:
- [x] Save: given a centerline's ordered points, emit one `Lineal` per
      segment (station *i* → *i+1*), `Enable=1`
- [x] Load: given a project's enabled `Lineal`s, reconstruct the ordered
      point list by walking them as an undirected graph of segments and
      chaining runs that share an endpoint — station 0 is the end of the
      chain reachable from the endpoint that appears in only one segment
- [x] Document the identification rule (revised from the original
      one-centerline-per-project scoping — see the 7.3 decisions-log
      entries): `Lineal` carries no name/tag, so a Lineal sharing an
      endpoint with another Lineal is part of a centerline; each ≥2-segment
      simple open chain is one centerline (**multiple per project** —
      intersecting roads). A lone segment is a stray reference line, never
      a centerline; single-segment centerlines are midpoint-split on save
      so they remain recognizable. Noted in IPRJ_FORMAT.md
- [x] Pure-python round-trip pytest coverage in `model/`: points → Lineals
      → points reproduces the same sequence (order-independent input, since
      a chain of undirected segments doesn't carry direction on its own)

Suggested prompt:
> [Fable] In EVO/iprj_designer, do Session 7.3 of ROADMAP.md: implement
> `.iprj` persistence for the Session 7.2 centerline through the existing
> `Lineal` entity — one Lineal per segment on save, reconstructed into an
> ordered polyline by chaining shared vertices on load (station 0 = the
> chain endpoint that appears in only one segment). Pure python in
> `model/`, pytest-covered round-trip, no GUI imports. Document the
> one-centerline-per-project assumption in IPRJ_FORMAT.md.

### Session 7.4 — Wire centerline persistence into the GUI (Target: Sonnet)

Scope:
- [x] On project open, reconstruct the centerlines (Session 7.3,
      `load_centerlines` — plural: typically one per approach/road) from
      the loaded project's `Lineal`s and seed the GUI with them
      (`CenterlineController` currently holds a single polyline — extend
      it or hold one controller per centerline)
- [x] On save, write the current centerline point lists out as `Lineal`s
      via the Session 7.3 `save_centerlines`

Suggested prompt:
> [Sonnet] In EVO/iprj_designer, do Session 7.4 of ROADMAP.md: wire the
> Session 7.3 `load_centerlines`/`save_centerlines` into `gui/app.py` —
> reconstruct all centerlines on project open (extend the single-polyline
> `CenterlineController`, or hold one per centerline) and write them back
> out as Lineals on save.

### Session 7.5 — Curvilinear placement refactor (Target: Fable; escalate to Opus only if it needs an architecture call)

Scope:
- [x] Place loops (and template expansions from Session 6) by station/offset
      so advance detectors follow approach curvature; loop orientation from
      local segment direction
- [x] Re-station attached zones when the centerline is edited afterward

Suggested prompt:
> [Fable, or Opus first if the undo/re-stationing interaction needs a
> design decision] In EVO/iprj_designer, do Session 7.5 of ROADMAP.md:
> refactor loop/template placement to go through the Session 7.1
> station/offset engine instead of straight-line placement, so detectors
> follow centerline curvature, and re-station attached zones when the
> centerline is edited.

---

## Decisions log

*(append as made)*

- 2026-07-01 — Planning docs created; framework leaning NiceGUI pending
  Session 2 spike.
- 2026-07-02 — Session 1 done. Model dataclasses stay in the file's own
  units (world px, y-down); feet enter via `model/units.py` only. Each
  entity carries an `extra: dict[str, str]` for unrecognized attributes, so
  foreign/converter files round-trip losslessly. `save_iprj` always writes
  the vendor dialect (`Config` root, one `<Configuration>` per attribute,
  vendor-canonical key order); the loader accepts both dialects.
- 2026-07-02 — Calibration: vendor files round `MeterPerPixel` to 2 decimals
  (0.08 vs true 0.0762 at Banks), so `units.effective_meter_per_pixel`
  re-derives the scale from `MeterReference0/1` + `ReferenceLength` and only
  falls back to the stored value when the pair is stale (ex27bg2 case).
- 2026-07-02 — `NrOfZonePoints` always equals the actual vertex count in
  real files, so it is derived from the point list on save, not stored.
- 2026-07-02 — **Framework decision: NiceGUI** (Session 2 spike; Dash spike
  not needed). The one feared cost — hand-built zoom/pan — turned out small:
  keep `interactive_image` at its natural pixel size and zoom/pan with a CSS
  transform, so mouse events keep reporting true image coordinates at any
  zoom and all viewport math is ~50 lines of pure python
  (`gui/viewport.py`, unit-tested). Everything else was free: SVG overlay
  in image coordinates for zones/markers/reference, dialogs, mode toggle,
  wheel/drag events with throttling. Verified headless with Playwright
  (installed in the venv, dev-only): zero console errors; cursor readout at
  image center reads exactly (1000, 2400) px on the 2000×4800 Banks image;
  two-point calibration of the raw image at 750 ft over 3000 px yields
  exactly 0.250 ft/px. Revisit only if hands-on feel disappoints.
- 2026-07-02 — Overlay stroke widths/fonts are specified in image px divided
  by the current zoom so they stay readable; the overlay SVG is regenerated
  on zoom. Fine at Session-2 scale; revisit if redraw cost bites once
  drawing interactions land (Session 3).
- 2026-07-02 — **Session 3 done.** The draw/edit state machine is pure
  python in `gui/drawing.py` (`DrawingController`, world-px coordinates, no
  NiceGUI imports — same testability pattern as `viewport.py`); planar
  geometry (hit tests, snap search, dimensioned rectangle) in
  `model/geometry.py`. Both pytest-covered; plus a Playwright end-to-end run
  on Banks (keyboard-driven 10×20 ft rectangle measured exactly 10.0/20.0 ft
  in the overlay SVG, delete/undo, zero console errors).
- 2026-07-02 — Dimensioned draw: the aim direction stays live with the mouse
  while typing side 1 and is **frozen when side 1 is committed**, so the
  mouse is then free to pick the extrude side without swinging the
  rectangle. With an empty side-2 buffer the preview extrudes to the mouse's
  perpendicular distance. Dimension entry requires calibration (status-line
  message otherwise).
- 2026-07-02 — Snapping defaults off (`g` toggles, as in the video tool);
  candidates are other zones' vertices **plus edge midpoints**. Snap and
  vertex-grab radii are divided by the current zoom so they feel constant on
  screen. Vertex drags snap live; body drags snap-correct on release
  (calibrate.py behavior).
- 2026-07-02 — Undo: point-level while a loop is pending, then an operation
  stack (add / delete / move-or-reshape) rather than calibrate.py's
  pop-last-shape — edit actions are undoable too. Redo deferred until it's
  missed in practice.
- 2026-07-02 — New zones land on the first sensor's `event_zones` (a default
  `Sensor` is created for image-only projects) with placeholder names
  "Zone N"; attributes/numbering are Session 4. Mode changes go through the
  toolbar toggle (`l`/`e` accelerators just set it), so toolbar and keyboard
  stay in sync.
- 2026-07-02 — **Session 4 done (MVP complete).** Zone properties dialog
  (`p`/Enter/double-click in Edit mode, or the "Zone props…" button):
  enable, name, phase, output, type, delay/extend, sensor reassignment, and
  a conditions table. Sensor tool (`s`): drag to move, click for properties
  (azimuth/elevation, height in ft ↔ meters stored, GPS); "Add sensor"
  places at image center. "Active sensor" selector picks which sensor
  receives new zones (`DrawingController.retarget`). Save/Save As write the
  vendor dialect with the embedded PNG; the date attribute is re-stamped on
  save. Verified end-to-end with pytest (116) plus two Playwright runs
  (new-from-image and banks.iprj), zero console errors.
- 2026-07-02 — Condition units are metric in the file: velocities **km/h**
  (the one real speed condition stores 40.23 = exactly 25 mph), queue
  lengths meters. Enabled conditions carry wide-open sentinels
  (16091.79 km/h ≈ 9999 mph, 3047.70 m = 9999 ft, 255 counts); new
  conditions are created with the same sentinels. The GUI edits velocities
  in mph. See IPRJ_FORMAT.md.
- 2026-07-02 — New zones fill the first *placeholder* slot (Enable=0, empty
  name, no points) instead of appending, so vendor files keep their fixed
  64-slot arrays and never grow past index 63; from-scratch projects just
  append (sparse converter-form files are known-accepted). `n`/`b` cycling
  and edit-mode preselection skip placeholders.
- 2026-07-02 — `OutputNumber` auto-assigns as max-across-all-sensors + 1 on
  draw *and* Ctrl-drag copy (outputs are rack channels, shared
  project-wide); a copy also bumps a trailing number in the source name
  ("SBT Count 1" → "SBT Count 2"). Undo ops now carry the zone list they
  touched, so undo works across active-sensor switches.
- 2026-07-02 — Vendor-software load test of a generated file remains the one
  open MVP item (no vendor software available here); mitigations unchanged
  (we write the vendor's own dialect, and sparse files are field-proven).
- 2026-07-02 — **Session 5 done.** Toolbar rebuilt as a dense icon row
  (undo/delete/zone-props buttons, a snap switch two-way-bound to
  `ctrl.snap_enabled`, a layers menu) with tooltips documenting the matching
  accelerator; the existing `l`/`e`/`s` tool toggle and Draw/Edit/Sensor
  keys are unchanged. Added a `ui.table` zone list (name/phase/output/type,
  one row per non-placeholder zone across all sensors) in a right-hand
  panel: row click selects (switches active sensor + Edit mode + canvas
  selection), row double-click opens the zone-properties dialog directly —
  `zone_properties()` now takes optional `(si, zi)` so it isn't limited to
  the current canvas selection. Layer toggles are three booleans on `Viewer`
  (`show_zones`/`show_labels`/`show_sensors`, checked in `svg()`) plus a
  CSS-opacity toggle for the background image (kept out of the SVG since
  the background is the raw `<img>`, not overlay content).
- 2026-07-02 — New accelerators: arrow keys nudge the selected zone by
  0.5 ft (falls back to 2 world-px uncalibrated) via `DrawingController`
  (pure python, pytest-covered) — a burst of arrow presses coalesces into
  one undo step, same pattern as drag; any other key breaks the coalesce.
  `f` re-fits the view, `Ctrl-S` saves (a small head-script blocks the
  browser's own save-page dialog so the accelerator isn't shadowed).
  Verified end-to-end with Playwright against banks.iprj: zone table
  populated (18 rows), row click/dblclick, layer menu, arrow-nudge status
  message ("nudged 0.5 ft"), f/Ctrl-S — zero console errors.
- 2026-07-02 — **Model-routing policy adopted** (see [[CLAUDE.md]]): Fable
  for pure-python math (`model/`, plus any future pure-python controller
  that lands under `gui/` the way `gui/drawing.py` did), Sonnet for
  NiceGUI wiring, Opus for cross-module architecture decisions. Sessions
  6–8 below are split into model-tagged sub-sessions along this line
  (schema/UI → math → wiring, in that order, so each hands the next a
  concrete artifact). One deviation from the routing as first proposed:
  Session 7.3 (centerline-following placement refactor) is pure
  `model/geometry.py`-shaped work, so it defaults to Fable rather than the
  "Opus or Fable" toss-up — Opus only enters if re-stationing turns out to
  need a real architecture decision (how it interacts with undo/model
  persistence), as a plan handed to the Fable session, not as a
  replacement for it.
- 2026-07-02 — **Session 6.1 done.** `model/templates.py`: `Lane`
  (movement — one or more of L/T/R, validated; width_ft; per-lane
  advance_detector toggle) and `ApproachTemplate` (name, speed_mph, lanes,
  a single template-wide `count_loops` toggle, starting_input/output,
  `direction` — the compass side of the intersection the approach sits on,
  e.g. "N" = north approach carrying SB traffic, not the travel
  direction — thru_phase, lt_phase). JSON load/save mirrors `iprj_io.py`'s
  pattern; `lane_config_str` renders the `12'L | 12'T | 12'T | 12'R` form
  from the roadmap for previews. No expansion/naming logic lives here yet —
  that's Session 6.2, added to this same module. `templates/` holds
  `example_45mph_north.json`, the appendix acceptance case below.
  `gui/templates_ui.py` is a standalone NiceGUI form (own `ui.run`, not
  wired into `gui/app.py` yet — that's 6.3): Open/New/Save/Save As over
  `templates/*.json`, per-lane rows with add/delete, and a live lane-config
  preview string. Verified headless with Playwright: loaded the example
  template, added a lane, saved, reloaded the saved JSON — zero console
  errors.

- 2026-07-02 — **Session 6.2 done.** Expansion lives in `model/templates.py`
  as a two-stage API: `expand_template(t) -> list[DetectorSpec]` (abstract
  approach-local layout: names, input/output numbers, phases, sizes,
  setbacks, lateral offsets) and `place_detectors(specs, stop_bar_ref,
  upstream_dir, units_per_ft)` -> 4-corner polygons in world y-down
  coordinates; `expand_and_place` is the one-call form for Session 6.3.
  `stop_bar_ref` is where the stop bar meets the leftmost lane's left edge;
  `upstream_dir` points away from the intersection; `units_per_ft` lets the
  GUI pass px-per-ft and get world px back. Conventions: setbacks are
  positive-upstream to the detector's downstream edge (count loops at -15
  sit past the bar; the 30' stop-bar zone at -5 straddles it); a lane is on
  the LT phase only when its movement is exactly "L"; advance/dilemma
  detection goes only to thru lanes (per-lane advance toggles on turn-only
  lanes are ignored); the dilemma zone spans first-to-last thru lane;
  duplicate base names get " 1"/" 2" suffixes, unique ones stay bare.
- 2026-07-02 — **ITE kinematics chosen for 6.2** (appendix ~100/~200 were
  placeholders; formulas govern): advance detectors at the safe stopping
  distance `v·t_pr + v²/2a` with t_pr = 1.0 s and a = 10 ft/s² (ITE
  detection-design values) → 283.8 ft at 45 mph; dilemma detector's
  downstream edge at the 2.5 s indecision-zone end → 165.0 ft at 45 mph.
  Constants are module-level in `templates.py` if field practice wants
  different assumptions.

- 2026-07-02 — **Session 6.3 done.** A new "Template" tool in `gui/app.py`'s
  toolbar toggle sits alongside Pan/Draw/Edit/Sensor/Marker/Calibrate: a
  `template` select (populated from `templates/*.json`, same files the 6.1
  editor writes) loads an `ApproachTemplate` via `load_template`; the click
  sequence is stop-bar reference point, then aim upstream (mouse tracks a
  live dashed line plus a translucent preview of every detector, recomputed
  each move via `expand_and_place`), then a second click commits. Placement
  requires calibration (same guard as dimensioned draw) and calls
  `expand_and_place(template, ref, upstream, 1/ft_per_px)`, converting each
  `PlacedDetector` to an `EventZone` (`zone_type=1` for `kind=="stop_bar"`,
  else 0; `output_number` from `DetectorSpec.output_number` — the format has
  no separate input-channel field, and the acceptance case runs input/output
  in lockstep) and inserting it through the existing `insert_zone` (first
  placeholder slot, else append) so template placement and manual drawing
  share one insertion path. Esc backs out an in-progress placement; leaving
  the Template tool clears it too. Verified end-to-end with Playwright
  against `banks.iprj` + the appendix's `example_45mph_north.json`: 11 zones
  landed with exactly the acceptance case's names/phases/outputs
  (33–43), interleaved correctly into the existing zone table; zero console
  errors.

- 2026-07-02 — **Session 7.1 done.** `Centerline` in `model/geometry.py`:
  station 0 at the first point, `locate(station, offset) -> (point, unit
  tangent)` (with `point_at`/`direction_at` shorthands) and the inverse
  `project(point) -> (station, offset)` — the inverse isn't in the 7.1
  scope line but 7.2's live readout and 7.3's re-stationing both need it,
  so it ships with the engine. Conventions: positive offset is to the
  *right of travel in y-down world space* (`offset_normal`, the CCW normal
  in y-up math); orientation is per-segment with no corner blending, a
  station exactly on an interior vertex taking the downstream segment;
  stations beyond either end **extrapolate along the terminal segments**
  (and `project` mirrors this), so a centerline drawn a little short still
  places a 283.8 ft advance detector; consecutive duplicate input points
  are dropped, fewer than two distinct points raises. Unit-agnostic like
  the rest of the module — stations/offsets are in whatever unit the
  polyline's coordinates are.

- 2026-07-02 — **Session 7.2 done.** New "Centerline" tool in `gui/app.py`'s
  toolbar toggle: `gui/drawing.py`'s `CenterlineController` (pure python,
  pytest-covered, same testability bar as `DrawingController`) accumulates
  clicked points into a polyline — click the stop bar first (station 0),
  then click upstream. A click either grabs an existing vertex within
  `handle_radius` or appends a new one, and either way the same
  mouse-down/drag/up gesture repositions it before release, so placing and
  reshaping share one motion; `x`/Del deletes the selected vertex, `u`/
  Ctrl-Z undoes (whole-points-list snapshots — simpler than
  `DrawingController`'s op stack, appropriate for one small polyline).
  `station_readout()` wraps the live points in a Session 7.1 `Centerline`
  and reports `project(cursor)` in feet (or px, uncalibrated) via the
  position label whenever the tool is active; the polyline itself renders
  on the canvas at all times (like zones/sensors) with a "0" label at the
  stop-bar vertex, so it stays visible as a spatial reference once drawn.
  Verified end-to-end with Playwright: tool selection, two clicks placed a
  centerline, live station/offset readout appeared while hovering, a
  vertex drag undid cleanly — zero console errors.
  **Open decision, resolved 2026-07-02:** the centerline was session-local
  Viewer state, not persisted in the `.iprj` schema. Decision (owner call,
  no Opus session needed): store it through the vendor's existing `Lineal`
  entity — one `Lineal` per centerline segment (it's a fixed 2-point line,
  so a polyline becomes a chain of them) — and reconstruct the ordered
  polyline on load by rolling consecutive `Lineal`s back up based on shared
  vertices. No new schema/attribute keys. Scoped as the new Session 7.3
  below; the old 7.3 (curvilinear placement refactor) is renumbered 7.5.

- 2026-07-02 — **Session 7.3 done.** `model/centerline.py`:
  `centerline_to_lineals` / `lineals_to_centerline` (pure conversion) plus
  project-level `save_centerline` / `load_centerline` for Session 7.4 to
  wire in. Save writes segment *i* as `point_0`=point *i*,
  `point_1`=point *i+1* — the per-segment point order is a direction hint,
  so load recovers station 0 exactly (the chain end that is its terminal
  segment's `point_0`), not just up-to-reversal; foreign files where the
  hint is ambiguous fall back to the lower-indexed Lineal's end,
  deterministically. Load identifies the centerline as the largest simple
  open chain (vertices matched at the vendor's 2-decimal precision;
  cycles and branching components are never candidates) among enabled
  Lineals. `save_centerline` replaces in place: blanks the old chain's
  slots to placeholder form, then fills placeholder slots before
  appending, so vendor files keep their fixed 100-Lineal array; enabled
  reference lines in other components and disabled-with-geometry Lineals
  are untouched. One consciously accepted edge (tested + documented in
  IPRJ_FORMAT.md): a *lone* vendor reference line in a project with no
  centerline is indistinguishable from a 2-point centerline, so load
  reports it as one and the first save replaces it — consistent in both
  directions. 24 tests in `tests/test_centerline.py`, including shuffled
  Lineal order, flipped segments, and full save_iprj/load_iprj file
  round-trips.

- 2026-07-02 — **Session 7.3 revised (owner correction, same day):** the
  one-centerline-per-project assumption was wrong — a project typically
  holds two or more (intersecting roads). New identification rule (owner
  call): any Lineal sharing an endpoint with another Lineal is part of a
  centerline; each ≥2-segment simple open chain is one centerline, and a
  *lone* segment is a stray reference line, never a centerline. API went
  plural: `load_centerlines`/`save_centerlines` return/take a list of
  point lists (file order = chain-first-appearance order), and save
  replaces the whole set of chains, leaving lone strays and
  branching/cyclic components untouched. Consequence handled: a genuine
  single-segment (straight) centerline would read back as a stray, so
  save midpoint-splits it into two collinear Lineals — it reloads with
  one interpolated mid vertex, geometrically identical. Remaining edge
  (documented in IPRJ_FORMAT.md): two centerlines drawn with a coincident
  *vertex* misjoin — crossing mid-segment, the normal intersecting-roads
  case, is fine. Still 24 tests / 191 total green; banks.iprj end-to-end
  re-verified with three centerlines including a straight one.

- 2026-07-02 — **Session 7.4 done (chose one-controller-per-centerline).**
  `Viewer.centerlines: list[CenterlineController]` seeded from
  `load_centerlines(project)` on open (falling back to one empty controller
  for a from-scratch project); `active_cli` picks the editable one and
  `Viewer.centerline_ctrl` is now a property returning it, so the
  mouse/keyboard/status wiring from Session 7.2 is unchanged. A toolbar
  "centerline" selector (mirroring the sensor selector) plus an "add
  centerline" button switch/create controllers; `svg()` renders every
  centerline (dim green when inactive, bright + vertex-selectable when
  active) so intersecting-road context stays visible while editing one.
  `do_save` calls `save_centerlines(v.project, [cl.points for cl in
  v.centerlines])` before `save_iprj`; empty/1-point controllers are passed
  through and dropped by `save_centerlines` itself, so an unfinished new
  centerline just doesn't persist. **Verified** in a follow-up pass once the
  tool-permission fault cleared: 191/191 pytest green, plus a Playwright
  run against a scratch copy of `banks.iprj` (never the fixture itself —
  Save/Ctrl-S write in place over `v.source`, so the app was launched
  against a copy) that drew a 3-point and a 2-point centerline, switched
  between them via the toolbar selector, Saved As to a new file, and
  reloaded it: both centerlines came back (the 2-point one midpoint-split
  to 3, per the Session 7.3 convention), zero console errors. One process
  note for future sessions: a first attempt drove the save dialog with an
  unscoped `input` locator and also sent Ctrl-S while `v.source` pointed at
  the real fixture, which briefly overwrote `sites/Banks/banks.iprj` on
  disk before it was caught and restored with `git checkout` — always
  launch `gui/app.py` against a scratch copy when Playwright-testing save
  paths, never the fixture directly.

- 2026-07-02 — **Session 7.5 done (no Opus escalation needed).**
  `model/templates.py`: `place_detectors_on_centerline` /
  `expand_and_place_on_centerline` map each detector corner to a
  (station, offset) on a Session 7.1 `Centerline` and locate it there, so
  detectors follow approach curvature and take orientation from the local
  segment. Sign mapping (documented in the module): the centerline is
  drawn stop-bar-first, so `setback_ft` adds directly to station; positive
  `Centerline` offset is the driver's *left* (tangent points upstream), so
  `lateral_offset_ft` subtracts. The clicked stop-bar reference is
  *projected* onto the datum, keeping its straight-placement meaning; on a
  straight datum the curvilinear form reproduces `place_detectors` exactly
  (pytest-pinned). `PlacedDetector.corners_so` carries the per-corner
  station/offset as the attachment record.
- 2026-07-02 — Re-stationing resolved without an architecture change to
  the undo model: `CenterlineController` keeps an `attached` registry
  (zone → corner station/offsets) and re-derives attached zones' points
  from it after *every* centerline mutation — drag (live), vertex
  add/delete, and snapshot undo — so undoing a centerline edit restores
  the zones for free (they're derived state, no zone-side undo ops
  needed). The reverse direction: the GUI calls `reproject` after manual
  zone edits (drag/nudge/undo), re-deriving the stored station/offsets
  from the zone's moved points, so a hand-adjusted detector keeps its
  adjustment through later centerline edits; untouched zones keep their
  exact placement coords (guard against `project`'s tiny corner-case
  drift). Attachments are session-local — `Lineal` can't carry them, so a
  reloaded project's zones sit where saved but no longer follow edits
  (noted in the app docstring; acceptable, same status the centerline
  itself had before 7.3).
- 2026-07-02 — GUI flow: with any usable centerline drawn, the Template
  tool is one click — live 11-detector preview follows the hover point
  along the *nearest* centerline (smallest |offset| of the projection, no
  distance cap — draw the approach's centerline first or expect
  attachment to the nearest one), and the click places + attaches. With
  no centerline the Session 6.3 ref-then-aim two-click flow is unchanged.
  Manual free/dimensioned draw stays straight-line and unattached — the
  refactor covers engine-placed detectors, where curvature matters
  (283.8 ft advance loops), not a hand-drawn 5 ft loop. Ctrl-drag copies
  of attached zones are deliberately *not* attached.
- 2026-07-02 — Verified: 200/200 pytest (9 new: straight-datum
  equivalence incl. off-datum ref + unit scaling, 90°-bend advance-loop
  rotation with hand-computed corners, corners_so round-trip, attachment
  restation/undo/reproject). Playwright end-to-end: bent 3-point
  centerline, one-click template placement ("along C1", outputs 33–43,
  zone table 11 rows), vertex drag moved the advance detector ~40 img px,
  `u` restored it to 0.00 px residual, zero console errors. Process note:
  the e2e ran against a small *generated* scratch project — banks.iprj in
  the NiceGUI app plus headless Chromium OOM-kills on this 6.5 GB machine
  (the server alone reached ~1.4 GB RSS); the banks-scale math is already
  pinned by pytest.

- 2026-07-02 — **Memory: NiceGUI 3 script mode was re-executing the whole
  app per page request.** Measured: server ready at 162 MB, then ~11 MB
  *permanently retained per GET of /* on Banks (OOM-killed this 6.5 GB
  machine during the 7.5 e2e). tracemalloc traced it to
  `ui_run.py: runpy.run_path(sys.argv[0])` — with UI built in the global
  scope, NiceGUI 3 re-runs the entire script (argparse → `load_iprj` 8 MB
  XML parse → new `Viewer` → `build_ui`) for *every* page request and
  retains a full project copy per client. Fix: `main()` now loads the
  project once and passes `ui.run(lambda: build_ui(viewer), ...)` — a root
  page function — so only the (small) element tree builds per client and
  the one Viewer stays shared (single-user semantics unchanged; Session
  8.1 owns multi-session). After: 130 MB flat across 51 GETs, Banks +
  headless Chromium runs comfortably. Two consequences: the Session-4
  "poll startup with a socket, not GETs" caveat is root-caused (each GET
  was a full project re-parse) and no longer load-bearing, and shrinking
  the background image is unnecessary — the server never decodes pixels
  anyway (see next entry).
- 2026-07-02 — Background image is now served as a temp *file*
  (`Viewer.image_file`), never a PIL object: NiceGUI retained per-client
  state around PIL-sourced `interactive_image` (~60 MB/request on Banks,
  measured before the root-function fix made it moot); a file source is
  streamed. Only the dimensions (`image_w`/`image_h`) are kept — pixels
  are never decoded server-side. `Viewer.image` (PIL) is gone.
- 2026-07-02 — **Attachments re-derived on project open** (owner request —
  7.5 attachments were session-local since `.iprj` can't carry them).
  Heuristic in `gui/drawing.py`: a 4-corner zone whose corners form an
  exact station/offset rectangle on a loaded centerline (two distinct
  stations x two distinct offsets, each corner reproduced by `locate`,
  tol 0.05 world px — 10x the vendor's 2-decimal rounding, well under
  hand-drawn slop) is attached to the laterally nearest centerline;
  `derive_attachments` runs in `Viewer.__init__` and a notification
  reports the count. Corner readings are collected *per segment* and the
  rectangle searched over the (tiny) combination space, because plain
  `project()` picks the wrong segment for corners on the concave side of
  a bend — caught live when the bend-straddling dilemma zone came back
  10/11 in the e2e; regression-tested. Known accepted edges: a zone
  hand-moved *off* the exact grid on a curved leg reloads unattached
  (its reprojected corners are no longer a station/offset rectangle);
  a hand-drawn rectangle drawn perfectly on-grid re-attaches — which is
  the behavior the owner asked for ("appears snapped → assume attached").
  205 pytest green; e2e extended: place → Save As → relaunch → "11 zones
  re-attached" notification → vertex drag re-stations identically
  (39.5 px, matching the in-session drag) → zero console errors; Banks
  browser smoke at 130 MB RSS, 18 rows, zero console errors.
- 2026-07-03 — **ROADMAP Phase 1 done** (quick wins, template undo, ruler,
  file management; Sonnet). Terminology: README/ROADMAP now say "Econolite
  Evo (Epiq)". Background-visibility bug root-caused: `interactive_image.js`
  sets the `<img>`'s opacity via an inline Vue `:style` binding, which beats
  a plain `.bg-off img { opacity: 0 }` class rule regardless of selector
  specificity — fixed with `!important`.
- 2026-07-03 — **Template placement is one undo step.** `DrawingController`
  gained `insert_many(zones) -> indices`, which runs the same
  placeholder-slot-else-append rule as `_insert` per zone but records a
  single `("batch", [sub_op, ...])` undo entry; `undo()` replays the
  sub-ops in reverse through a new `_undo_one` helper (refactored out of the
  old inline undo body). `gui/app.py`'s `place_template` now builds all of a
  template's `EventZone`s and calls `v.ctrl.insert_many(zones)` once instead
  of looping `insert_zone`, so a single `u`/Ctrl-Z removes every detector
  the template placed, restoring any placeholder slots it took over. Covered
  by two new `tests/test_drawing.py` cases; e2e-verified (11 detectors
  placed → one undo → back to the pre-placement row count).
- 2026-07-03 — **2-Point Ruler tool.** New "Ruler" toolbar entry (`r`
  accelerator) mirrors the Template tool's click-driven interaction rather
  than a literal held-mouse-button drag: first click sets the start point,
  live distance tracks the cursor via `Viewer.describe()` (same pattern as
  Centerline's station readout) regardless of whether the button is held, a
  second click locks the end point. A real click-drag-release also finishes
  it in one gesture (`on_up` finalizes if the pointer moved past
  `handle_radius / 3` since mousedown) so both usage styles from the roadmap
  wording ("click to start... drag... click to end") work. The finished
  measurement (amber line + label) persists on screen across tool switches
  until replaced or cleared via the (renamed) "clear markers & ruler"
  toolbar button, matching how markers already behaved.
- 2026-07-03 — **In-app New/Open/Upload, no CLI restart.** `main()` now
  holds `state = {"viewer": Viewer(...)}` and hands `build_ui` a page
  function closing over `state`, rather than capturing one `Viewer`
  directly — New/Open build a fresh `Viewer` (blank `Background()`, one
  from an uploaded image via `ui.upload`, or one loaded from an existing
  `.iprj` path picked from a `sites/**/*.iprj` dropdown or typed manually),
  assign it into `state["viewer"]`, and call `ui.navigate.reload()` so the
  next page function invocation on that client picks up the new project —
  no server process restart, consistent with the existing single-user model
  (other Session-7.4-era notes on shared `Viewer` state still apply). A
  from-scratch project's `Viewer.source` is set to a non-`.iprj` placeholder
  path (`untitled.png`, or the uploaded file's own name) purely so the
  existing `save()` logic's `suffix == ".iprj"` check forces a Save As
  dialog on first save, reusing the CLI's "new project from a plain image"
  behavior rather than adding a parallel code path. e2e-verified: blank
  canvas (0 zones, gray placeholder), image upload (background loads,
  title reflects the uploaded filename), and Open (18 zones round-trip on
  the scratch Banks fixture) — zero console errors in all three.
- 2026-07-03 — **ROADMAP Phase 2 done (domain codes & rotation math;
  Fable).** Owner read the vendor codes out of the Evo software, resolving
  the Session 1/4 "(open)" items; everything landed in a new pure-python
  `model/domain.py` (enums + names + rules), IPRJ_FORMAT.md updated.
  - **Key structural finding:** conditions have *no per-type schema on
    disk* — the vendor writes the identical full attribute set for every
    condition, and which fields are meaningful follows from the owning
    zone's `ZoneType`. So the designer keeps the single `Condition`
    dataclass and adds `domain.condition_fields(zone_type)` /
    `conditions_allowed(zone_type)` for the UI to filter by (Phase 3.2
    wires this): Presence → output/delay/extend/queue/vehicle counts;
    Motion → class/direction/delay/extend/velocity/ETA (+ output — real
    speed conditions in the wild carry one); Sidewalk → none. Unknown
    future codes fall back to showing the full field union.
  - **`ZoneType` names are Motion(0)/Presence(1)/Sidewalk(2)** — replaces
    the Session-1 "standard/stop bar/legacy" guesses; consistent with them
    (stop-bar = presence detection). `ConditionClass` is the Motion
    condition's **vehicle-class filter** (0 all, 1 car, 2 bike/ped, 3 small
    truck, 4 big truck, 5–7 the car+truck combos), not a condition-type
    discriminator; `Direction` is sensor-relative (0 both, 1 approaching,
    2 receding). Speed bounds display as 0–9999 mph (the stored
    `16091.79` km/h sentinel). `gui/app.py` now derives `ZONE_TYPE_NAMES`
    from the domain enum and delegates `new_condition` to
    `domain.default_condition`; template placement writes
    `ZoneType.PRESENCE` for stop-bar detectors, `MOTION` otherwise (as
    before, now by name).
  - **Ignore Zone / generic Lineal model helpers** (`domain.new_ignore_zone`,
    `insert_ignore_zone`, `new_lineal`, `insert_lineal`, placeholder
    predicates): same fill-placeholder-slot-else-append rule as event
    zones, but capped at the vendor array sizes (10 ignore zones/sensor,
    100 lineals) with `ValueError` past the cap — the vendor UI can't
    represent more. `new_ignore_zone` defaults `IgnoreEverything=1` (38 of
    48 enabled ignore zones in the site survey; what a `0` zone still
    ignores stays open). Documented hazard: generic lineals share the
    Lineal pool with the centerline chain encoding, so their endpoints
    must never snap onto another Lineal's endpoint or they merge into a
    centerline on reload.
  - **Rotation math in `model/geometry.py`:** `polygon_centroid` (shoelace
    area centroid, vertex-mean fallback for degenerate/​<3-point input),
    `rotate_points(points, angle_deg, pivot=None)` (default pivot = the
    centroid), and `rotation_angle_deg(pivot, from_pt, to_pt)` for Phase
    3.2's two-click pivot workflow. Convention: standard math rotation,
    which renders clockwise-on-screen per positive degree in this
    project's y-down world coords; angle-measure and rotate share the
    convention so drag-to-rotate follows the mouse without sign fixups.
    228 pytest green (14 new domain tests, 8 new geometry tests).

- 2026-07-03 — **ROADMAP Phase 3.1 done (UI architecture plan; Opus).**
  Output is [[PHASE3_UI_PLAN.md]], a design doc for the Phase 3.2 (Sonnet +
  Fable) build. Key calls made:
  - **Toolbar → two tiers.** The single ~26-control overflow row becomes a
    persistent chrome row (file menu, one tool toggle, snap/undo/layers/fit/
    zoom/panel) plus a per-tool **context bar** rebuilt on tool change via
    `set_visibility` toggles (same pattern as `zone_panel`), so nothing
    scrolls. Flat 9-mode toggle collapses to **6 primary tools** — Select,
    Draw, Template, Centerline, Sensor, Measure — with sub-types surfaced in
    the context bar (Draw: Loop/Ignore/Lineal; Measure: Ruler/Calibrate/Marker,
    folding three transient point-drop utilities into one).
  - **Draw sub-modes via a `DrawKind` draw-target descriptor** at the
    pure-python `DrawingController` seam (Fable), not in NiceGUI: bundles the
    live list + factory + insert helper + placeholder predicate + shape
    (`polygon` 4-click/dimensioned vs `segment` 2-click) + render style.
    Polygon kinds (Loop, Ignore Zone) reuse the whole existing draw/edit/snap/
    dimension path — only `_commit_zone` generalizes; the undo stack already
    carries each op's list so cross-list undo needs no change. Flagged a real
    gap: **generic lineals don't currently round-trip through the GUI** (only
    centerline *chains* are surfaced; lone strays survive in the file but
    aren't editable), so 3.2 needs a Fable `load_lineals`/`save_lineals` plus
    the documented endpoint-coincidence guard (a lineal sharing an endpoint
    re-reads as a centerline).
  - **Pan dropped as a mode.** Default tool becomes **Select**; pan is implicit
    (middle-drag, already global; + space-drag to add). Empty-canvas left-drag
    in Select becomes the marquee multi-select — the gesture the old Pan mode
    occupied. Fallback if ambiguous: a momentary Hand toggle, not a mode.
  - **Multi-select** = `selection: list[int]` + `anchor` on the controller
    (keep a `selected` property for incremental migration), scoped to one
    element kind/sensor for v1. Group move/delete/nudge and the 2-click
    rotate (wiring Phase 2's `rotate_points`/`rotation_angle_deg`) reuse the
    existing `("batch", […])` undo entry — the load-bearing reuse that leaves
    the undo model untouched. Recommended rotation **detaches** attached
    zones (manual override, mirrors hand-move-off-grid).
  - **Routing:** recommended Fable-first sequencing — 3.2a (controller/model
    pure-python: `DrawKind`, multi-select state, marquee/group helpers,
    lineal round-trip), then Sonnet 3.2b (toolbar + draw kinds + Pan removal)
    and 3.2c (multi-select sync + rotate).
  - **Owner decisions (same day, folded into the plan):** Pan dropped
    (confirmed); bulk-edit deferred to a follow-up (v1 ships single-selection
    Properties + group Delete/Move/Rotate); rotation detaches attached zones
    (they're already oriented by the centerline, so a hand-rotate is a
    deliberate override). **Accelerators: `d` enters Draw** (top level); within
    Draw, **`z` Loop · `l` Lineal · `i` Ignore**; `v`/`e` Select, `t` Template,
    `c` Centerline, `s` Sensor, `r` Measure. Two collisions the plan resolves
    at the pure-python seam (Fable, 3.2a): `d` no longer starts dimensioned-
    rectangle entry (a digit does — drop `d` from `_key_draw`'s `starts_dim`),
    and `l` no longer enters Draw (remove the `l`/`e` set-mode shortcuts in
    `DrawingController.key`; all tool/sub-type keys are handled app-side with an
    early return before delegating to the controller).

- 2026-07-03 — **Input/output terminology unified to "output" (owner
  clarification).** The detection unit's output channel maps 1:1 to the
  controller input it drives, so "input" and "output" were two names for one
  thing — and the `.iprj` format only ever stored `OutputNumber`. Removed the
  redundant input alias wherever it was a channel number: dropped
  `ApproachTemplate.starting_input` and `DetectorSpec.input_number` (numbering
  is output-only now), the template editor's "Starting input #" field, and the
  `starting_input` key from `example_45mph_north.json`. `template_from_dict`
  now filters to known dataclass fields, so any legacy template still carrying
  `starting_input` loads without error (the value was redundant with
  `starting_output`). ROADMAP Phase 4's placement prompt is **Base Output** /
  `output_offset` (was "Base Input"), and IPRJ_FORMAT.md's `OutputNumber` row
  now states the 1:1 output→controller-input mapping. Tests updated
  (`s.output_number`, `test_expand_without_count_loops_shifts_outputs`); the
  acceptance case still numbers 33–43. Historical entries above keep their
  original "input" wording as the record of what was built at the time.

- 2026-07-03 — **Phase 3.2a (Fable): DrawKind, multi-select, lineal
  round-trip, accelerator seam.** Pure-python pass per PHASE3_UI_PLAN
  §4/§6/§7; no GUI wiring touched beyond one `app.py` docstring line.
  Decisions made at the seams:
  - `DrawKind` (frozen dataclass in `gui/drawing.py`) generalizes only the
    commit target — `make(points, seq)` / `insert` / `is_placeholder` /
    `shape` — with instances `LOOP_KIND` / `IGNORE_KIND` / `LINEAL_KIND`.
    `Lineal`'s two endpoint fields are adapted through module-level
    `element_points`/`set_element_points`, so the `("points", …)` undo op
    shape is unchanged and the stack still survives retargets (now
    including kind switches: `retarget(zones, kind=…)`). Cap `ValueError`s
    from `domain.insert_*` are caught in `_insert` and surfaced on a new
    one-shot `ctrl.warning` field for 3.2b to `ui.notify`.
  - `LINEAL_KIND` sets `snappable=False`: a lineal endpoint must never snap
    (endpoint coincidence merges it into a centerline chain on reload).
    Belt-and-braces, `save_lineals` — added to `model/centerline.py` beside
    the chain logic it reuses — *skips* endpoint-coincident or degenerate
    strays and returns the skipped list for the GUI to report; call it
    after `save_centerlines` so the guard sees the final chain vertices.
    `load_lineals` returns working copies of the single-segment components,
    mirroring the centerline load/save split.
  - Multi-select is `selection: list[int]` + `anchor`; `selected` became a
    property (get = anchor, set = collapse-to-one), so every existing
    `gui/app.py` call site — including its `ctrl.selected -= 1` index fixup
    — works unchanged. **Shift-click toggles membership; Ctrl-drag keeps
    its existing copy meaning** (the plan's "Ctrl/Shift-click" was
    ambiguous and Ctrl was already taken). Group move/nudge/delete write
    one `("batch", …)` op (delete recorded high-index-first so undo
    restores low-to-high); nudge bursts coalesce for groups as they did for
    singles. Marquee = `geometry.polygon_intersects_rect` (touching counts;
    handles 2-point segments) + `ctrl.marquee_select(a, b, additive=)`.
    Snap-on-release stays single-zone — a group already moved as one rigid
    delta.
  - §2.1 accelerator fixes landed: `d` no longer starts dimension entry
    (digits after the first corner do — hint text updated); `l`/`e`
    set-mode shortcuts removed from `DrawingController.key`. The app-level
    `l`/`e` bindings still route those keys until 3.2b moves all tool
    accelerators up. Suite: 274 tests pass (39 new across
    `test_drawing.py`, `test_geometry.py`, new `test_lineals.py`).

- 2026-07-03 — **Phase 3.2b (Sonnet): two-tier toolbar, Pan dropped,
  draw kinds wired.** NiceGUI wiring per PHASE3_UI_PLAN §3/§4/§5 on top of
  3.2a's controller/model. Decisions made at the seams:
  - Row 1 (chrome) holds the file menu (New/Open/Save/Save As), the 6-tool
    toggle (Select/Draw/Template/Centerline/Sensor/Measure), snap, undo,
    layers, fit, save, and the zone-panel toggle. Row 2 (context bar) is
    *one* row built once at page load; every tool's controls live in it
    simultaneously and `update_context_bar()` calls `.set_visibility()` on
    each control per the active tool/sub-type, rather than the "one row per
    tool" reading of the plan diagram — this lets a control genuinely
    shared across tools (the sensor selector shows for Draw, Select, *and*
    Sensor) exist once instead of three times.
  - Draw's sub-type toggle and Select share one `DrawingController`
    (`Viewer.draw_kind_name` + `draw_zones()`/`set_draw_kind()`): switching
    sub-type or active sensor calls `ctrl.retarget(...)`, so Select always
    edits whatever the Draw toggle last pointed at — picking "Ignore Zone"
    in Draw and then switching to Select edits ignore zones. The zone table
    stays Loop-only (it has no columns for ignore zones/lineals); selecting
    a table row forces the toggle back to Loop first.
  - Pan is gone. `space_pan` (a `Viewer` flag toggled by the keyboard
    handler's keyup/keydown on the space key) and the existing
    middle-button check now gate the pan branch in `on_down`; Select's
    empty-canvas drag is a marquee instead. The marquee-vs-click/drag
    decision needed one small addition to `gui/drawing.py`: a public
    `DrawingController.dragging` property (vertex-or-body-drag in
    progress), so the GUI can tell "nothing was hit" apart from "something
    was hit but didn't move" without reaching into the controller's
    underscore-prefixed drag state. `on_down` snapshots `selection`/`anchor`
    before calling `mouse_down` and starts a marquee only when neither
    changed and nothing is dragging — a shift-click toggle or a ctrl-drag
    copy always changes one of those, so they're correctly never mistaken
    for a marquee start.
  - Selection-set membership (`zi in ctrl.selection`, not `== ctrl.selected`)
    now drives the white-outline highlight for all three kinds — event
    zones, ignore zones (now white-vs-yellow-dashed), and lineals
    (white-vs-gray) — so a marquee's multi-selection is visible immediately
    rather than only from 3.2c onward. The zone **table**'s selection sync
    stays single (`selection="single"`), and rotate/bulk-edit are still
    out of scope — both remain 3.2c per the plan.
  - Verified with a scripted Playwright/Chromium session (not just pytest,
    since `gui/` has no unit coverage by design): every tool/sub-type
    switch, the keyboard accelerators, an empty-canvas marquee (0 hits) and
    a full-image marquee (7 zones), a 2-click Lineal placement, a 4-click
    Ignore Zone placement + undo, and a Save As round-trip — checked the
    saved file's stray-lineal and ignore-zone counts against expectations
    with no browser console/page errors. Suite: 274 tests pass unchanged
    (3.2b is GUI wiring; the one `drawing.py` addition is a read-only
    property with no new test surface).

- 2026-07-03 — **Phase 3.2c (Sonnet): multi-select table sync, rotate.**
  PHASE3_UI_PLAN §6.4/§6.5, closing out Phase 3. Decisions at the seams:
  - The zone table is now `selection="multiple"`: its checkbox column
    syncs to/from `ctrl.selection` via `on_table_select` (built from
    `e.selection`'s full row list each time, so it's idempotent rather than
    delta-based). Scoped to one sensor per §6.1 — checking a row from a
    different sensor than the current pick keeps only that row's sensor
    (mirroring how switching sensors already clears the selection). Plain
    **row click** still selects just that one row (a small, deliberate
    `drawing.py`-side asymmetry: it collapses to a single pick the way a
    canvas click does, distinct from the checkbox column's additive
    multi-select) and double-click still opens Properties for that row
    regardless of the current multi-selection.
  - Bulk edit stays out of v1 (§8.2): the floor is `properties_btn.set_enabled
    (len(selection) <= 1)`, refreshed alongside the selection count, plus a
    guard in `zone_properties()` for the `p`/Enter/context-bar paths (a
    table double-click still bypasses it — that's an explicit "just this
    row" request, not "operate on the current selection").
  - Rotate is a new `DrawingController.rotate_selection(angle, pivot)` +
    `selection_centroid()` pair (`gui/drawing.py`, since it needs the
    controller's private undo stack — the same reasoning that put
    `dragging` there in 3.2b) plus `Viewer`-level click/drag state
    (`rotate_armed`/`rotate_pivot`/`rotate_ray`/`rotate_angle`) mirroring
    how Template's ref-then-aim flow already lives at that layer. Read
    the plan's "two-click workflow, default pivot = centroid" as: the
    Rotate button arms the tool with a *visible* centroid-seeded pivot
    marker; click 1 drops the real pivot (usually near that seed, but
    anywhere); the first mouse-move after that freezes the reference ray
    for `rotation_angle_deg`; click 2 commits. A zero-angle commit (two
    clicks with no mouse movement between) is treated as a no-op — no undo
    entry, nothing to detach — rather than recording a null rotation.
  - Attachment interaction (§6.4): `rotate_selection` returns the rotated
    elements; the GUI pops each one out of every `CenterlineController
    .attached` dict by `id(zone)` and reports a count in the toast. Ignore
    zones/Lineals are never attached, so the pop is a harmless no-op for
    those kinds — no kind check needed.
  - Verified with a scripted Playwright/Chromium session against
    `sites/Banks/banks.iprj`: checkbox multi-select (additive, matches the
    selection-count label), row-click collapse back to one, Properties
    disabling/re-enabling across that transition, and the full rotate
    arm → pivot click → live preview (pivot cross + dashed rotated outline
    + live angle readout) → commit → "rotated N zone(s)" toast cycle — no
    browser console errors. Suite: 280 tests pass (6 new in
    `test_drawing.py` covering `selection_centroid`/`rotate_selection`,
    including the batch-undo and zero-angle-noop cases).

- 2026-07-04 — **ROADMAP Phase 4.1 done (advanced template engine — math &
  schema; Fable).** `model/templates.py` rebuilt around "math seeds flexible
  defaults", run schema-first then seeding per the ROADMAP notes. Decisions:
  - **Schema v2: explicit `TemplateDetector` rows** (kind, `spanning_lanes`,
    length, setback, `output_offset`, phase role) are the editable source of
    truth for expansion. `seed_detectors` fills them from the kinematics;
    expansion only ever reads stored values, so a Phase 4.2 override fully
    replaces the computed one (pinned by
    `test_seeded_rows_are_defaults_not_constraints`). An empty `detectors`
    list means "expand seeded defaults", which is also how v1 templates
    behave after upgrade. `spanning_lanes` are contiguous ascending 0-based
    lane indices; width = sum of spanned lane widths at expansion.
  - **Continuous-coverage advance chain.** A call gaps out when the clear
    gap between successive detectors exceeds what the detection-channel
    extension carries at design speed, so `advance_setbacks_ft` chains
    advance detectors downstream from the SSD at a pitch of
    `length + v·t_ext` until the extension bridges the remaining gap to the
    dilemma detector's upstream edge (`gap_max = v·t_ext`). Assumed
    extension: `DEFAULT_EXTENSION_TIME_S = 1.0 s`, a per-template field
    (`extension_time_s`) like the Session 6.2 PRT/decel constants are
    module-level. At 45 mph/1.0 s that's two rows (283.8, 207.8 ft); 30 mph
    or a 2.0 s extension needs one — the acceptance case is now 13
    detectors, outputs 33–45.
  - **Placeholders vs. literals.** `direction`/`thru_phase`/`lt_phase`/
    `base_output` are Optional: a present value is a baked literal that
    placement never overrides; None means "prompt at placement", filled from
    a new `PlacementContext` (`expand_*` all take an optional `context`).
    `missing_placeholders()` is usage-aware (lt_phase only required if some
    row carries the "lt" role) — the seam for the 4.3 placement prompt. New
    `ApproachTemplate()` defaults all four to placeholder.
  - **Base + Offset numbering** (output-only, per the 2026-07-03 entry):
    rows store `output_offset`, assigned output = `base_output + offset`.
    v1's `starting_output` maps onto the Base Output literal in
    `template_from_dict` (offsets seed 0,1,2,…, so the numbers come out
    identical); v1 files load unchanged and upgrade to v2 on save.
  - **Anchor (Station 0) lane line.** Lateral offsets now originate at the
    anchor lane line — default: right side of the *leading block* of
    movement-"L" lanes (`default_anchor_lane_line`; 0 = leftmost lane's left
    edge when there is none; a shared LT lane is not exclusive, and an L
    lane after a non-L lane doesn't count), overridable per template via
    `anchor_lane_line` (a lane-line index 0..n). Lanes left of the anchor
    get negative offsets; the placement click is now the anchor point, and
    the appendix acceptance case re-pins laterals to −12/0/12/24. GUI status
    strings updated to say "anchor point (stop bar at the LT/thru lane
    line)".
  - **Compat wiring kept minimal:** `place_template` in `gui/app.py` now
    catches the unresolved-placeholder `ValueError` and notifies (real
    prompt is 4.3); `templates_ui.py` renamed to "Base output #", gained an
    extension-time field, and saves blank direction/phase/output fields as
    placeholders (it still doesn't edit detector rows — that's the 4.2 grid
    editor). New `templates/example_45mph_generic.json` is the all-
    placeholder companion to the v1-format `example_45mph_north.json`
    (kept as the legacy-load fixture). Suite: 304 tests pass (24 net new).

- 2026-07-04 — **ROADMAP Phase 4.2 done (grid editor UI; Sonnet).**
  `gui/templates_ui.py` gained a Detectors section below Lanes: one flat CSS
  Grid container whose columns are the template's physical lanes (column 1 a
  fixed-width row header, column width weighted by `lane.width_ft` so wider
  lanes get wider columns) and whose rows are `TemplateDetector` entries,
  each placed by explicit `grid-column`/`grid-row` rather than nested
  per-row grids. Decisions:
  - **Merge = span, not a special mode.** A row's value cell (length/setback
    editors) is positioned at `grid-column: {2 + span_from} / span {span_to
    - span_from + 1}`; widening a row's "to lane" number simply grows that
    span, so the cell visually stretches across the lane columns it now
    covers — no separate "merge cells" action. Verified with a Playwright
    session: widening a single-lane count row's span from lane 0 to 0-2
    changed its CSS `grid-area` from `.../span 1` to `.../span 3` and the
    saved JSON came back with `spanning_lanes: [0, 1, 2]`.
  - **`detector_rows` is plain-dict state, not UI-element-backed.** Unlike
    `lane_rows` (which keeps the live `ui.number`/`ui.input` handles),
    detector rows are dicts (kind/span_from/span_to/length_ft/setback_ft/
    output_offset/phase) rebuilt into elements on every structural change
    (`render_detectors()` clears and redraws the whole grid). This was
    necessary because a span edit changes *layout* (grid-column), not just a
    value — easier to redraw the section than to reposition one cell's DOM
    node. Non-layout field edits (length, setback, kind, phase, output
    offset) just mutate the dict without a redraw.
  - **"Seed from kinematics" materializes, then never re-runs.** The button
    calls `seed_detectors()` on a throwaway `ApproachTemplate` built from the
    current lanes/speed/extension-time fields and replaces `detector_rows`
    wholesale (confirmation dialog if rows already exist); after that, every
    field is a plain editable value; Save writes exactly what's in the grid.
    This is the Phase 4.1 "seed, don't constrain" contract made concrete in
    the UI — there's no live recompute-on-lane-change wired up, by design.
  - **Phase field is free text, not a select.** `TemplateDetector.phase` is
    `"thru" | "lt" | int`; a plain `ui.input` (placeholder `thru / lt / #`)
    covers all three without a custom widget, parsed in
    `collect_detectors()`/`_parse_phase` the same way `model/templates.py`'s
    private `_validate_phase` does (duplicated rather than imported, since
    that helper is intentionally private to the model module).
  - Verified with a scripted Playwright/Chromium session: seeding on a
    1-lane/45 mph template (5 rows) and a 3-lane/1-LT template (11 rows,
    matching the Design History Session 6 acceptance shape), widening a
    span and confirming the `grid-area` CSS change, editing length/setback/
    phase/output-offset, Save As to a JSON file, then reloading that file
    through `model/templates.py` and `expand_template` — merged span came
    back as a 36 ft-wide "SBLT Count" detector at output 131 (base 32 +
    offset 99), phase 4 as the literal typed. No browser console errors.
    Suite unchanged: 304 tests pass (Phase 4.2 is GUI-only, no `model/`
    changes).

- 2026-07-04 — **ROADMAP Phase 4.3 done (canvas placement UI; Sonnet).**
  `gui/app.py`'s Template tool now carries a `Viewer.template_context`
  (`model.templates.PlacementContext`), threaded into every
  `expand_and_place`/`expand_and_place_on_centerline` call — both the live
  preview in `svg()` and the committing `place_template`. Decisions:
  - **Prompt is scoped to what the template actually needs.**
    `missing_placeholders(template, None)` (a fresh, all-`None` context)
    gives the fixed set of fields *this template* requires — usage-aware,
    so an all-thru template never asks for LT phase — independent of
    whatever the user has already filled in; that set drives which
    `ui.select`/`ui.number` widgets the dialog builds. A template with
    every field baked (the Session 6.3-era `example_45mph_north.json`)
    yields an empty set, so picking it opens no dialog at all — placement
    behaves exactly as before 4.1.
  - **Auto-prompt on pick, manual re-open via a context-bar button.**
    `change_template` resets `template_context` and calls
    `edit_placement_values(auto=True)`, which is a no-op when the field set
    is empty; a new pencil-icon "placement values" button (visible whenever
    a template is selected) calls the same dialog with `auto=False`, always
    opening — including on a fully-baked template, showing a "no
    placeholders" message — so values (most usefully Base Output) can be
    reviewed or changed between repeated placements of one template across
    several approaches, without re-picking it from the dropdown.
  - **The canvas click is still the anchor point** — Phase 4.1 already
    redefined `stop_bar_ref`/the click to mean the anchor lane line rather
    than the leftmost lane edge, and `place_detectors`/
    `place_detectors_on_centerline` were unchanged by 4.3, so "snap to the
    anchor point" was a wiring consequence of passing `template_context`
    through, not new geometry.
  - **Placement is guarded at the click, not just at expansion.** `on_down`'s
    Template branch checks `missing_placeholders` before doing anything
    with the click and reopens the values dialog instead of consuming the
    click as a reference point — so a user who dismisses the auto-prompt
    doesn't lose their click as a wasted anchor placement.
  - Verified with a scripted Playwright/Chromium session against a blank
    scratch project (a plain gray PNG, calibrated by known width): picking
    `example_45mph_generic.json` (the all-placeholder companion template)
    auto-opened the dialog; filling direction=N/thru=4/lt=7/base=33 and
    applying updated the status line to the anchor-click prompt; anchor +
    aim clicks placed 13 detectors at outputs 33–45 (the Phase 4.1
    45 mph/1.0 s acceptance shape) with a matching toast. A second run
    confirmed `example_45mph_north.json` (fully baked) opens no dialog on
    pick, and the manual button still opens one showing "no placeholders."
    Zero console errors in both runs. Suite unchanged: 304 tests pass
    (4.3 is GUI-only, no `model/` changes).

- 2026-07-04 — **Template editor wired into the Template tool's context bar**
  (owner-reported gap after Phase 4.3: `gui/templates_ui.py` had no entry
  point from `gui/app.py` since Session 6.1, when it was built as a
  standalone NiceGUI form). `gui/templates_ui.py` owns its own `ui.run`
  event loop, so it can't be mounted into `gui/app.py`'s page directly — a
  new editor button (pencil-and-square icon, next to the template picker
  and "placement values" button, visible whenever the Template tool is
  active) spawns it as a `subprocess.Popen` on `state["template_editor_port"]`
  (`--port` + 1000) the first time it's clicked, polls the port (up to ~5 s)
  until it accepts a connection, then `ui.navigate.to(..., new_tab=True)`
  opens it in a new browser tab; a later click reuses the same subprocess
  (checked via `proc.poll()`) rather than spawning a second one on the same
  port. The tracking state (`template_editor_proc`) lives on `state`, not
  `Viewer`, so it survives a New/Open project swap; the subprocess is
  registered with `atexit.register(proc.terminate)` the same way `Viewer`'s
  temp background-image file already is. If a template is currently picked
  in the Template tool, its path is passed as the editor's positional
  argument so it opens straight to that file instead of a blank form.
  **First landed as a File menu item, then moved same-day** (owner
  preference: it belongs with the rest of the Template tool's controls, not
  buried in the file menu) — behavior is otherwise identical. Verified with
  a scripted Playwright/Chromium session: the button is absent from the
  File menu and hidden outside the Template tool, visible only once that
  tool is active; first click spawned the subprocess and opened a new tab
  titled "Approach Template Editor"; a second click (after closing that
  tab) reused the running process and opened promptly with no second
  "starting…" notification; picking `example_45mph_north.json` in the
  Template tool first and then opening the editor (after killing the
  previously-spawned instance so a fresh one launched) opened directly to
  "Approach template — example_45mph_north.json". Zero console errors.
  Suite unchanged: 304 tests pass (gui-only change).

- 2026-07-04 — **ROADMAP Item 1: Background tool rework + Ruler as an
  independent overlay** (Measure renamed, in-place background upload,
  Ruler relocated, Marker deleted). The one real design decision: how
  "move Ruler to the persistent chrome row — general-purpose, not tied to
  any workflow" should actually behave. Two readings were possible — just
  relocate its button while keeping it a mode you switch into via the tool
  toggle, or make it a true overlay that works simultaneously with
  whatever tool is active. Asked the owner; **chose the overlay**: `Viewer`
  drops `measure_kind`/`markers` entirely and gains `ruler_active` (a bool,
  not a mode), checked in `on_down`/`on_move`/`on_up`/`refresh_status`
  ahead of the `v.mode` dispatch chain — same priority tier as the
  existing `space_pan` gesture, so a ruler measurement can be taken
  mid-Draw or mid-Select without losing that tool's state (verified: the
  Select context bar and its selection stayed intact through a full
  ruler measurement in the Playwright run below). The persistent chrome
  row gained the ruler toggle (`straighten` icon) and "clear ruler"
  (`wrong_location`) next to the tool toggle; the `r` key now toggles
  ruler instead of switching to the old Measure tool. `b` was **not**
  reused as Background's accelerator despite being the obvious mnemonic —
  `gui/drawing.py`'s edit-mode already binds `n`/`b` to cycle-selection, so
  Background is toggle-toggle-only (click the tool bar), no key.
  Background (renamed from Measure) keeps 2-point and known-width/height
  calibration unchanged, and gains an upload button (image icon) that
  replaces `project.background`'s image in place via
  `units.decode_background_image` + the same temp-PNG-file serving
  `Viewer.__init__` already does, then `ui.navigate.reload()` — zones,
  sensors, and centerlines are untouched since only `bg.image_base64`/
  `image_w`/`image_h`/`image_file` change; existing calibration values are
  left as-is (not reset) since they're a separate concern the user
  re-runs if the new image is at a different scale. The known-width/height
  calibration button switched from `straighten` (now Ruler's) to
  `aspect_ratio`.
  Verified with a scripted Playwright/Chromium session against
  `sites/Banks/banks.iprj`: the tool toggle reads Select/Draw/Template/
  Centerline/Sensor/**Background** (zero "Measure"/"Ruler"-as-toggle/
  "Marker" text remaining); toggling Ruler on while the Select tool was
  active, taking a full click-drag-click measurement (314.0 ft), and
  toggling it off left the Select tool's own status/context bar untouched
  throughout; the upload dialog opened from the Background context bar and
  a real 400×300 PNG uploaded through it replaced the visible background
  while all 18 zones across S1/S2 stayed listed in the zone table
  afterward, with zero console errors.
- 2026-07-04 — **ROADMAP Item 2: per-zone-type condition field filtering**
  (Sonnet). `gui/app.py` gains a `_COND_FIELD_SPECS` table (label/widget-kind/
  unit-conversion per `Condition` field) keyed by the same field names
  `domain.CONDITION_FIELDS` already used; `zone_properties()`'s
  `add_cond_row` now only builds widgets for `domain.condition_fields(
  zone.zone_type)`, and "Add condition" is disabled when
  `domain.conditions_allowed(zone.zone_type)` is false (Sidewalk). `class`/
  `direction` got real `ui.select` dropdowns (using `VEHICLE_CLASS_NAMES`/
  `DIRECTION_NAMES`, previously not editable at all) rather than raw
  numbers, matching how `class` was already a name-backed field elsewhere;
  `queuelength_min/max` convert m↔ft and `velocity_min/max` convert km/h↔mph
  at the widget boundary like the rest of the dialog.
  **Decision on stale saved values** (the scope's open question): a zone
  type's hidden fields are **not rendered and not cleared** — `apply()`
  only writes back the fields in the current `condition_fields()` set, so a
  Presence zone's stray pre-fix velocity value (if any exists in a real
  file) is left exactly as loaded rather than silently zeroed. Chose this
  over active-clearing because opening/editing a zone's *other* fields
  (name, phase, an unrelated condition's output) shouldn't have the side
  effect of discarding data nobody asked to touch; a future explicit
  "clean stale fields" action can be its own opt-in tool if the stray
  values turn out to matter in practice.
  Also not done: the field set is fixed to `zone.zone_type` at dialog-open
  time, not reactive to the Type `ui.select` in the same dialog — changing
  Type and clicking Apply changes `zone.zone_type` correctly, but the
  Conditions section won't re-filter until the dialog is reopened. Out of
  this item's scope; flagged here in case it surprises someone later.
  Verified with a real headless Chromium session (Playwright) against
  `sites/Banks/Banks_EVO.iprj`: a Presence zone ("SB Stop Bar") shows only
  output/delay/extend/queue min-max/ped-cars-truck min-max, no velocity/
  class/direction; a Motion zone ("SB Mid") shows output/class/direction/
  delay/extend/v min-max/eta min-max, no queue/vehicle-count fields, with
  `class`/`direction` rendering as dropdowns ("All"/"Both directions"); and
  a Sidewalk zone (`sites/Banks/sh-55 & banks_evo.iprj`, "EZ 1: PH 2
  StopBar") shows "Add condition" disabled (`aria-disabled: true`). Zero
  console errors in all three. `pytest` (304 tests) unaffected.
- 2026-07-04 — **ROADMAP Item 4 done** (sensor management: nudge, delete,
  status fix). Arrow-key nudge on the active sensor while the Sensor tool is
  active reuses `NUDGE_FT`/`v.ft_per_px()` the same way `DrawingController.
  _nudge` does, but moves `position_x`/`position_y` directly — no undo entry,
  matching the existing drag-to-move behavior (which also isn't undoable).
  Delete sensor (context-bar trash icon + `x`/Del) blocks removing the last
  remaining sensor; otherwise a dialog offers **reassign** (move the
  sensor's non-placeholder event/ignore zones onto another sensor via the
  existing `insert_zone` placeholder-slot logic, so conditions travel with
  the zone object) or **delete zones too** (drop them with the sensor,
  consistent with `DrawingController.delete_selected` also not scrubbing
  stale `CenterlineController.attached` entries on delete). Reassign target
  defaults to the lowest-numbered other sensor. Fixed `add_sensor()` calling
  `refresh_status()` (it called `update_sensor_options()` but not
  `refresh_status()`, so the footer kept showing the old active sensor).
  Verified with a headless Chromium (Playwright) session against
  `sites/Banks/banks.iprj`: adding S3 immediately showed "S3 active" in the
  footer; 6 ArrowRight presses moved S3's on-screen marker right (bbox x
  532.1→535.3px, y unchanged); `x` on the empty new S3 opened a "No zones on
  this sensor" one-button Delete dialog; `x` on S2 (15 zones) opened the
  reassign/delete-children dialog defaulting to S1, and "Reassign & Delete"
  moved all 15 rows onto S1 in the zone table, collapsed the sensor
  dropdown to just S1, and left the status line reading "S1 active". Zero
  console errors throughout; `pytest` (304 tests) unaffected.

- 2026-07-04 — **ROADMAP Item 5, model half** (insert-vertex; Fable).
  `model/geometry.py` gains `nearest_edge_insertion(pt, poly) ->
  (insert_index, point)`: clamped projection of *pt* onto the nearest
  polygon edge, edges wrapping (last→first) for 3+ points so a closing-edge
  hit appends, with a 2-point open polyline treated as its single segment
  (same open-shape convention as `polygon_intersects_rect`). A projection
  clamping to a shared vertex ties between the two adjacent edges and
  resolves to the lower edge index — where the vertex lands in the list is
  cosmetic in that case. Chose nearest-edge-to-cursor over the scope's
  "midpoint if simpler" fallback; the projection is the same ~10 lines.
  `DrawingController.insert_vertex(p=None)` (Edit mode, exactly one
  selected element) inserts at the nearest edge to *p*, defaulting to the
  live cursor — the shape the `v`-key wiring needs. One `("points", …)`
  undo op, and it resets `_nudging` so an arrow-nudge burst doesn't
  coalesce across the insertion (it bypasses `key()`, which normally does
  that reset). Lineals are refused — they store exactly two endpoint
  fields, no vertex list to grow. Like any manual vertex edit, the GUI
  must `reproject` a centerline-attached zone afterward (existing
  drag-vertex convention; `reproject`'s length check already handles the
  corner-count change). Not done here (Sonnet half): the Select→Edit
  rename, dropping the `v` tool alias, and wiring `v` to this method.
  12 new tests; full suite 316 passing.

- 2026-07-04 — **ROADMAP Item 5, Sonnet half** (Select→Edit rename,
  insert-vertex key wiring; Sonnet). Renamed the "Select" tool to "Edit"
  everywhere it's user-facing in `gui/app.py`: the tool-toggle option/
  default value, `Viewer.mode`'s default and every comparison against it,
  status/notify strings, tooltips, and the module docstring's usage guide
  (including the accelerator line and the Edit-tool paragraph); mirrored
  in two stale "Select tool" mentions in `gui/drawing.py` docstrings.
  Dropped `v` from `TOOL_KEYS` (was aliased to Select alongside `e`), so
  `e` is now the only tool accelerator and a bare `v` falls through
  `on_key`'s existing `v.ctrl.key(name, ...)` dispatch into
  `DrawingController._key_edit`, where a new `name == "v"` branch calls
  `self.insert_vertex()` (always returns `True` so the status line/warning
  surface either way, matching the existing `delete_selected` pattern —
  no new app.py wiring needed since `reproject_attachments()` already runs
  after any successful `ctrl.key()`). Full suite 316 passing; server boot
  smoke-tested (`gui/app.py --port`), no console/startup errors.

- 2026-07-04 — **ROADMAP Item 6** (Loop → Event Zone terminology; Sonnet).
  Renamed the "Loop" draw sub-type/kind label to "Event Zone" throughout
  `gui/app.py`: `DRAW_KINDS`/`DRAW_SUBTYPE_KEYS` keys, `draw_kind_name`'s
  default and every comparison against it, the sub-type toggle's options/
  default value, the zone-properties notify message, tooltips, and the
  module docstring's usage guide. Mechanical rename only — `gui/drawing.py`'s
  `LOOP_KIND.name = "loop"` internal field was left alone since it never
  actually surfaces in the UI (it's read only for `shape == "segment"`
  kinds in `DrawingController.status()`, and Loop's `make()` always sets
  `zone_name` so its `_commit_element` fallback never triggers either);
  changing it would've been scope creep with no visible effect.
  `gui/templates_ui.py` still says "Loop" (count-loops checkbox/field),
  per the roadmap's carve-out — untouched. Full suite 316 passing; server
  boot smoke-tested, no console/startup errors.

- 2026-07-04 — **ROADMAP Item 7, controller half** (free polygons past 4
  points; Fable). `DrawingController.mouse_down` no longer auto-commits a
  polygon draw at 4 points — only `shape == "segment"` kinds keep a fixed
  count (2 clicks). Free polygons accept corners indefinitely and commit
  via the new `finish_polygon()`: Enter routes to it from `_key_draw`
  (only at `DIM_OFF`, so dimension entry's Enter-commit is untouched —
  and `gui/app.py`'s existing `on_key` fall-through to `ctrl.key()`
  means Enter-to-finish already works in the app with zero GUI changes),
  and the GUI's dblclick handler will call it directly (Sonnet half).
  Two decisions worth recording: (1) `finish_polygon` folds *trailing*
  points coincident with their predecessor within `handle_radius / 2`
  (zoom-rescaled like the hit tests) before committing, because the
  double-click gesture's own two mousedowns land as pending points before
  the browser's dblclick event arrives — folding only trailing points
  leaves deliberately tight mid-shape geometry alone; (2) finishing with
  fewer than 3 surviving corners is handled-with-feedback (returns True,
  sets `message`, keeps `pending`) rather than discarding the draw.
  Dimensioned rectangles (`_commit_dimension`) are structurally unchanged;
  `preview_polygon` rubber-bands past 4 points; the status line's
  "corner n/4" became "corner n" with an "[Enter/double-click finishes]"
  hint from the 3rd corner on. Test helper `draw_square` now ends with
  `finish_polygon()`. Not done here (Sonnet half): wiring dblclick during
  a pending free-draw to `finish_polygon()` in `gui/app.py` — note the
  existing Edit-mode dblclick → `zone_properties()` handler is
  mode-guarded, so Draw-mode dblclick is currently free. 6 new tests
  (+1 renamed from the old 4-click auto-commit test); full suite 322
  passing.

- 2026-07-04 — **ROADMAP Item 7, Sonnet half** (wire double-click-to-finish;
  Sonnet). `on_dblclick` in `gui/app.py` gained a `v.mode == "Draw"` branch
  alongside the existing Edit-mode one: it calls `v.ctrl.finish_polygon()`
  and, if that handled the gesture (pending free-draw polygon), runs the
  same `notify_ctrl_warning()` / `refresh_overlay()` / `refresh_status()`
  triad every other Draw-mode mutation already does — no new event
  binding needed since `ii.on("dblclick", on_dblclick, ...)` was already
  wired for the Edit-mode zone-properties shortcut. `finish_polygon()`'s
  own no-ops (segment kinds, dimension entry, nothing pending) return
  `False`, so a stray double-click elsewhere in Draw mode is inert.
  Updated the module docstring's key/usage summary to mention that
  free-draw polygons take unlimited corners and finish with Enter or
  double-click. Full suite still 322 passing (no controller-side test
  changes needed — the Fable half already covers `finish_polygon()`
  directly); server boot smoke-tested (`gui/app.py --port`), no
  console/startup errors. Item 7 complete.

- 2026-07-04 — **ROADMAP Item 11 done** (canonical coordinate origin;
  Fable). New `model/coords.py::normalize_origin(project)`: translates
  every coordinate field by `(-Background_PosX, -Background_PosY)` —
  background pos + `MeterReference0/1_X/Y`, sensor positions, event/ignore
  zone points, ETA points, lineal endpoints, text-label positions,
  including disabled vendor placeholder entries (the whole file moves as
  one rigid frame, not just enabled objects). `None` fields (converter-form
  files omit keys) stay `None` so save doesn't invent attributes.
  Calibration (`MeterPerPixel`/`ReferenceLength`, translation-invariant)
  is deliberately untouched — `test_calibration_untouched` asserts
  `effective_meter_per_pixel` is unchanged. Wired into `load_iprj` at the
  end of parsing (`model/iprj_io.py`), so every load path (File > Open,
  scripts, tests) picks it up automatically; `save_iprj` needed no change
  since it just serializes whatever the in-memory `Project` holds — it
  naturally writes `Background_PosX = Background_PosY = 0`.
  **This deliberately breaks vendor byte-fidelity on save** — rewrote
  `tests/test_roundtrip.py::test_attribute_roundtrip` to assert the new
  contract instead (every coordinate key shifted by the source file's own
  `(-PosX, -PosY)`, everything else value-equal, `Background_PosX/Y == 0`
  after save) rather than exact string/numeric equality across the board.
  New `tests/test_coords.py` (7 tests) covers the shift itself, calibration
  invariance, idempotency, zero/missing-pos no-ops, `None`-field
  preservation, and one-axis-missing files. Documented the new save
  contract in IPRJ_FORMAT.md (new paragraph after the dialect section).
  Full suite 329 passing. This is a prerequisite for Item 9 (see
  ITEM9_SPLIT_PLAN.md §3a) — a matched two-file pair now coregisters
  automatically via the shared image-origin frame instead of a cross-file
  delta computation.

- 2026-07-04 — **ROADMAP Item 9 done** (multi-sensor 2-file split;
  Fable + Sonnet, per ITEM9_SPLIT_PLAN.md). Fable half: new
  `model/multifile.py` — `pair_paths`/`is_valid_pair`/`pair_role` on the
  `<base>_1_2`/`<base>_3_4` filename convention (handles a base that
  itself ends in digits, e.g. `route_12`, without mis-stripping);
  `check_background_match` (two-tier: image dimensions/position/scale/
  rotation/effective-m-per-px hard-fail, pixel-hash soft-warn, degrading
  gracefully when calibration or the image is missing on one or both
  sides); `split_project`/`merge_pair` (primary owns every project-wide
  field — background, lineals, text labels, extra — the secondary gets
  only a deep-copied background plus its sensors; no sensor-index or
  `OutputNumber` renumbering — `save_iprj`'s enumeration gives the `_3_4`
  file `Radarsensor_0/1` for free). Per the plan's §5, pytest coverage
  was in-scope for this Fable session (an explicit exception to the usual
  Fable-skips-tests rule, since the plan makes a green suite the
  Sonnet-handoff gate): 28 new tests in `tests/test_multifile.py`,
  including a synthetic split→save→load→merge round-trip and a real-
  fixture acceptance test against the Franklin_KCID site's actual
  two-file pair. Full suite 357 passing after the Fable half.

  Sonnet half: `Viewer` gained `self.pair: tuple[Path, Path] | None`
  (`gui/app.py`); `add_sensor` caps at `multifile.MAX_SENSORS` (4) with a
  notify. New File-menu action "Open second sensor-pair file (overlay)…"
  loads a second file, resolves primary/secondary via `pair_role` when
  the filenames follow the convention (else a two-button "which is 1-2"
  dialog), runs `check_background_match`, blocks on a hard mismatch,
  confirms on a soft one, then `merge_pair`s and swaps in a new `Viewer`
  with `pair` set. `do_save`/`save`/`save_as` grew the two-file branch
  exactly as the plan specified: plain Save only when `v.pair` is a valid
  naming pair, otherwise redirected to Save-As; Save-As shows a live
  preview of the derived `_1_2`/`_3_4` names as the user types. Title bar
  shows both filenames for a paired project.

  Verified end-to-end in a live browser session (Playwright against the
  running NiceGUI app, not just pytest) using the real
  `Franklin_KCID/Phase 2 & 6 sensor 1 and 2.iprj` +
  `Phase 4 & 8 sensor 3 and 4 with speed.iprj` pair — neither filename
  follows the `_1_2`/`_3_4` convention, so this also exercised the
  orientation-picker dialog: merge succeeded with no background-mismatch
  warning, the sensor selector showed S1-S4, a 5th `add_sensor` was
  correctly blocked, and Save (forced to Save-As, since the merged
  project's `pair` isn't a valid naming pair) wrote a working `_1_2`/
  `_3_4` file pair that reloads and re-merges losslessly (all
  `OutputNumber`s intact). Documented the pairing convention and
  primary-owns-extras rule in IPRJ_FORMAT.md's Container section.

- 2026-07-04 — **ROADMAP Item 8 done** (move an Event Zone along its
  centerline; Fable then Sonnet). Fable half: `CenterlineController` gained
  `zone_station(zone)` (the attached zone's downstream/setback edge —
  `min(s for s, _ in corners)`, the same edge `DetectorSpec.setback_ft`
  measures to) and `move_attached(zone, *, station=None, delta=None)`
  (`gui/drawing.py`) — shifts every stored `(station, offset)` corner by
  the same station delta (offsets unchanged, so the zone keeps its shape
  and follows bends), re-derives `zone.points` via `Centerline.point_at`,
  and returns the zone's prior points (or `None` if unattached / no valid
  datum) so the caller can build an undo entry. Units are world px
  throughout, matching the stored attachment corners.

  Sonnet half: a small dialog on the toolbar (new "timeline"-icon button
  next to Properties/Rotate, `move_along_centerline()` in `gui/app.py`) —
  enabled only in the Edit tool with exactly one Event Zone selected that
  `attached_centerline_for()` finds on some centerline. Shows the current
  station in feet (converted via `ft_per_px()`, blocked with a notify if
  uncalibrated, matching `place_template`'s existing guard), and offers
  either an absolute-station "Set" or a relative "Move by" (+ = upstream).
  `DrawingController` gained a small public `record_points_undo(zone,
  old_points)` so the dialog can push a `("points", zone, ...)` undo entry
  in the same shape `_nudge` already writes — `undo()` restores a
  station-move exactly like a drag, no new undo-op type needed.

  Finishing pass: 8 new tests in `tests/test_drawing.py` covering
  `zone_station`/`move_attached` — the downstream-edge convention,
  relative delta, absolute station, a move that straddles a centerline
  bend (shape preserved via the same per-corner station/offset math
  `restation` uses), the `ValueError` on ambiguous/missing args, `None`
  returns for an unattached zone or a sub-2-point datum, and an undo
  round-trip through `DrawingController.record_points_undo` +`.undo()`.
  Full suite 366 passing. Verified end-to-end in a live browser session
  (Playwright against the running NiceGUI app on `sites/Banks/banks.iprj`):
  drew a centerline, placed the `example_45mph_generic` template along it
  (auto-attaching 13 detectors), confirmed the move button stays disabled
  until a centerline-attached zone is selected (a pre-existing unattached
  zone correctly left it disabled), opened the dialog on "SBT Count 1"
  (current station 54.5 ft), set it to station 50.0 ft (notified, zone
  label visibly moved on the canvas), then confirmed the toolbar Undo
  restored it to 54.5 ft exactly.

- 2026-07-04 — **ROADMAP Item 3 closed — not a bug** (zone duplication
  across sensors on load). Reported on the Perimeter site as one sensor's
  zones appearing duplicated onto both sensors. Investigated and closed: the
  load path in `model/iprj_io.py` is sound — the duplication is a property
  of the source files themselves, not the sensor/zone association logic. The
  loader faithfully represents what the file contains, so no parser change
  and no regression test were warranted. Item 9's split/merge round-trip
  tests still exercise the zone↔sensor association as a standing safety net,
  so a real loader regression here would surface there.

- 2026-07-05 — **Model-routing change (CLAUDE.md).** Fable is now billed on
  usage credits, so it's demoted from routine implementer to a *debugging
  escalation* — used only after Opus/Sonnet fail a specific bug over a few
  passes. Default is now **Opus running whole items end-to-end in one
  session** (plan + model + GUI + tests + docs), retiring the old
  Fable/Opus-plan → Sonnet-implement hand-off: the owner isn't
  usage-constrained on Opus, Opus is at least as strong as Sonnet on every
  task shape here, so each cross-model hand-off was paying for a second
  session to re-ingest context and buying nothing. Sonnet stays as an option
  for a *whole* small mechanical item only (never as the back half of an
  Opus-planned one). ROADMAP.md trimmed at the same time — completed Items
  1–9 and 11 removed (archived here), leaving only Item 10 (webserver).

- 2026-07-05 — **ROADMAP Items 12 & 13 closed (Sonnet, `gui/app.py`).**
  Both were toolbar-only fixes, no `model/` changes, so no new pytest
  coverage was warranted. Item 12: the move-along-centerline button
  (`move_station_btn`) had `set_enabled` logic gating it on a selected,
  centerline-attached zone (`refresh_status`, pre-existing from Item 8) but
  no `set_visibility` call in `update_context_bar`, so it stayed visible
  under Draw/Background/etc. — just added it alongside the other Edit-only
  buttons (`rotate_btn`, `delete_btn`). Item 13: swapped the clear-ruler
  button's icon from `wrong_location` (an old waypoint-marker relic) to
  `clear` — no ruler-themed "ruler-with-x" icon exists in the project's
  Material Icons set (no extra icon set like mdi/eva-icons is loaded), so
  used the documented plain delete/clear fallback.

- 2026-07-05 — **ROADMAP Items 15, 17 & 18 closed (Opus, `model/templates.py`
  + `gui/templates_ui.py`).** One coherent change to the seeding/expansion
  taxonomy, done end-to-end.
  - **Item 17 — dilemma→decision + advance/decision taxonomy.** Renamed the
    `dilemma` detector kind to `decision` everywhere (`DETECTOR_KINDS`,
    `_base_name` → "Ph N Decision", the `DILEMMA_*` constants/functions →
    `DECISION_*` / `decision_setback_ft`, docstrings). Old JSONs that stored
    the `dilemma` kind migrate on load (`template_from_dict`). Restructured
    the thru-lane chain: the **single** furthest-upstream detector (at the
    safe stopping distance) is now the only `advance` detector and keeps the
    lane-by-lane toggle; everything between it and the stop-bar-side decision
    detector is a `decision` detector spanning the thru lanes. Replaced the
    old downstream-stepping `advance_setbacks_ft` with `decision_setbacks_ft`,
    which computes the *count* of intermediates needed for continuous
    coverage (fewest keeping every clear gap ≤ `v·t_ext`) and then spaces
    them **evenly** so the slack is shared across all gaps rather than dumped
    into one (45 mph/1.0 s: one intermediate, two 39.4 ft gaps instead of
    66 + 22.8).
  - **Item 15 — consistent stop-bar order.** Seeding now emits rows in
    ascending distance from the stop bar (count → stop bar → decision chain
    stop-bar-side-first → the single furthest advance), so the grid table no
    longer renders the near-stop-bar advances at the bottom. This falls out
    of the Item 17 restructure (decision setbacks returned stop-bar-side
    first, advance appended last) — output offsets follow the same order.
  - **Item 18 — seed lengths before seeding.** Added `decision_length_ft` /
    `advance_length_ft` seeding inputs to `ApproachTemplate` (default 20 / 10,
    the old hardcoded values), threaded into `seed_detectors` and the
    coverage math, and surfaced as "Decision len (ft)" / "Advance len (ft)"
    inputs in the template editor's top section (load/seed/collect wired like
    the existing extension field). Schema bumped v2→v3 (additive, backward
    compatible: missing keys fall back to the defaults on load).
  - Tests: rewrote the acceptance/seed/kinematics cases in
    `tests/test_templates.py` (12 detectors now, not 13), added even-spacing,
    length-seeding, and kind-migration tests, and fixed the two
    `tests/test_drawing.py` counts (13→12). Full suite green (370).

- 2026-07-05 — **ROADMAP Item 14 closed (Opus, `gui/app.py`) — zoom freeze
  / server disconnect on large files.**
  Investigated end-to-end against the worst realistic case (the default
  `sites/Banks/banks.iprj`: 2000×4800 / 9.6 MP background, 128 event zones).
  - **Bottleneck (measured, not guessed).** Ruled out the two obvious
    suspects: the background is *not* re-encoded per zoom (it's a static
    temp-file `<img>` scaled by a CSS transform), and the server-side
    overlay build is cheap — `Viewer.svg()` is 7.8 KB and 0.14 ms on Banks.
    The real cost was **zoom-event rate**. The wheel handler was the only
    interaction with no throttle (unlike `mousemove`'s `throttle=0.03`), and
    every tick did a full server round-trip: `on_wheel` → `apply_transform`
    → `refresh_overlay` set `ii.content`, which made the browser re-parse the
    SVG overlay (`interactive_image.updated()` → `innerHTML`) *and*
    re-composite the scaled 9.6 MP background — every frame. A fast scroll
    fires 60–120 events/s; that saturates the browser main thread, the
    missed socket heartbeat drops the connection, and the fit-on-reload
    (`ui.timer(0.3, fit_view, once=True)`) is what snaps back to the
    zoomed-out view. "Zooming in too quickly" = event rate, exactly.
  - **Fix — move the zoom transform client-side.** Added `_WHEEL_ZOOM_JS`, a
    `js_handler` on the wheel `.on(...)` that reads the live transform matrix
    (`getComputedStyle`), applies the zoom-at-cursor CSS transform directly
    to the interactive_image root every tick (GPU-cheap, no content
    re-parse), and calls NiceGUI's closure `emit` — which stays throttled
    (`throttle=0.05`) so it can't flood the socket. The emit carries
    **absolute** viewport state `{scale, tx, ty}` (not deltas), so it's
    idempotent: dropped/reordered/last-only syncs just adopt the browser's
    truth. `on_wheel` shrank to "assign `v.viewport`, `apply_transform`,
    update status" so overlay stroke-widths and the status label catch up at
    the throttled rate. `js_handler` must stay an inline arrow (it needs the
    render closure's `emit`; a head-defined global can't see it). Imported
    `gui/viewport.py`'s existing `MIN_SCALE`/`MAX_SCALE` into the JS clamp so
    it can't drift from the Python one.
  - **Why this is robust.** `getComputedStyle` re-reads the matrix each tick,
    so server-driven pan/fit stay authoritative between gestures; the
    transform, wheel listener, and `ii.style` all land on the same
    interactive_image root (Vue attribute fallthrough), so `e.currentTarget`
    is the element being transformed; `e.offsetX/Y` are the img's
    untransformed local coords (= image pixels), the same values the old
    server handler consumed.
  - **Verified (Playwright, headless Chromium, against Banks).** After fit
    (scale 0.16), a burst of 400 native wheel events processed in **12 ms**
    (main thread not frozen), zoom accumulated **losslessly** to the max
    (status `zoom 0.16x` → `zoom 40.00x`, confirming the throttled emit
    reached the server), `socket.connected` stayed **true**, zero JS/server
    errors. Pure `gui/` change (no model logic touched); full pytest suite
    still green (370). **Resolved by Opus — no Fable escalation.**

- 2026-07-05 — **ROADMAP Items 19 + 20 done (Opus, one session) —
  place-along-centerline controls + nameable centerlines.** Run together
  because Item 20's names are what Item 19's per-centerline dropdown labels.
  - **Root cause of "snaps far too aggressively."** `Viewer.centerline_for`
    picked the nearest centerline by `|offset|` with **no threshold** — so
    once *any* centerline existed, *every* template anchor click followed the
    nearest one however far away it was, with no way to opt out. It wasn't a
    mis-tuned distance; there was no distance at all.
  - **Fix (Item 19).** Extracted the nearest-datum selection into a pure,
    tested model helper `geometry.nearest_centerline(centerlines, pt,
    max_offset)` (skips `None` datums; `max_offset=None` = old unbounded
    behavior). `centerline_for` now passes `CENTERLINE_SNAP_FT` (40 ft,
    module constant in `gui/app.py`) converted to world px via `ft_per_px`;
    beyond it, placement falls back to the aim-upstream second click. Added
    an "along CL" **toggle** (`template_follow_centerline`, default on,
    mirroring the snap switch) to disable following entirely, and a "pick CL"
    **dropdown** (`template_centerline_idx`, default blank) that pins
    placement to one specific centerline and **bypasses** the threshold. The
    three combine in `Viewer.template_target_centerline`: explicit pick wins,
    else follow→nearest-within-threshold, else None. `template_status`
    reflects all three states.
  - **Item 20.** Added a session-only `CenterlineController.name` (empty =
    unnamed) and `Viewer.centerline_label(i)` (name or `C{n}` fallback). A
    "name" input in the Centerline context bar renames the active centerline;
    the label flows to the active-centerline selector, the Item 19 dropdown,
    and the placement notification. Not persisted — the `.iprj` Lineals have
    nowhere to carry it (consistent with the attachment-derivation approach).
  - **Model-purity note.** The one piece of new math (nearest-within-
    threshold) lives in `model/geometry.py` and is unit-tested
    (`test_geometry.py`: smallest-offset pick, `None`-entry skipping,
    `max_offset` boundary). The rest is GUI wiring. Verified headless:
    `template_target_centerline` returns the right centerline/None across all
    toggle+dropdown combinations against `sites/Banks/banks.iprj`, the page
    builds and serves (HTTP 200, no errors), full pytest suite green (373).

- 2026-07-05 — **ROADMAP Item 16 done (Opus, one session) — side-by-side
  detector table (adjacency rows).** Replaced the template editor's
  row-per-detector grid with the owner's original vision: one row per
  **adjacency group**, detectors laid out side by side across lane columns.
  - **New pure model — `model/detector_layout.py` (headless, tested).**
    `group_adjacent_detectors(dets)` groups detector indices into table rows
    as **connected components** under longitudinal-extent overlap
    (`setback_ft`..`setback_ft+length_ft`, touching counts), so same-station
    detectors (the count loops, the stop-bar zones, the two advance loops)
    share a row while the two non-overlapping decision detectors stay separate.
    Groups are ordered by ascending min-setback, **input order preserved within
    a group** — so flattening a freshly seeded list reproduces it exactly and
    output numbering never shifts. `assign_tracks(lane_spans)` greedily colors
    laterally-colliding detectors in one group onto separate sub-rows (only
    matters for hand-built rows; seeded rows are one-per-lane, single track).
    The seeded acceptance case (L|T|T|R) collapses **12 detectors → 5 rows**:
    `[count, stop_bar, decision, decision, advance]`.
  - **GUI — `gui/templates_ui.py`.** Editor state moved from a flat
    `detector_rows` to `groups: list[list[dict]]` (explicit display bands built
    once on seed/load via `group_adjacent_detectors`, **not** recomputed on
    every keystroke so cards don't jump rows while a setback is typed). Each
    band is a CSS-grid row (plus tracks); each detector is one card at
    `grid-column: span_from+2 / span count` **merging** the former header
    fields (kind/lanes/phase/output-offset) with the value fields
    (length/setback). A slim col-1 header carries `Row N` + delete-row.
  - **Manual build flow.** **Add row** appends an empty band showing a `+` in
    every lane column; a band with detectors shows a `+` only in its
    *uncovered* columns. Clicking `+` adds a detector in that lane — a sibling
    in a non-empty band **inherits the station** (setback/length) and
    kind/phase from the band's first detector, its own output offset. Per the
    owner's call this session, `+` **always adds a sibling**; spanning multiple
    lanes is done by editing a cell's lane range (no auto-stretch/merge
    heuristic). `collect_detectors` flattens `groups` back to the flat detector
    list — **grouping is display-only, the template JSON / iprj format is
    unchanged** (IPRJ_FORMAT.md untouched).
  - **Verification.** New `tests/test_detector_layout.py` (13 tests: overlap/
    touch/gap boundaries, transitive chain, group ordering + within-group order
    preservation, seeded-acceptance 5-row grouping, track collision). Full
    suite green (386). Headless Playwright smoke against an L|T|T|R template:
    Seed → 5 `Row N` headers and 12 side-by-side cards, `+` present exactly in
    the decisions'/advance's open lanes 0 & 3; Add row → 4 more `+`; clicking
    `+` adds a card; no page errors.

- 2026-07-05 — **ROADMAP Item 21 done (Opus, session 1 of 2) — sensor-scoped
  lineals/centerlines/labels via vendor index bands.** Model-only foundation
  for annotations that travel with the right sensor file; the GUI wiring
  (assignment UI, text-label entity, centerline-name labels) is Item 22.
  - **New pure model — `model/bands.py`.** `Owner` enum (GENERAL/FILE1/FILE2)
    + the three bands over the fixed 100-slot arrays (0–19 GENERAL → both
    files, 20–59 FILE1 → sensors 1&2/`_1_2`, 60–99 FILE2 → sensors 3&4/`_3_4`).
    `owner_of_index` (load-time inference), `sensor_owner` (active si → band,
    matching the split boundary), and `allocate` — a generic lowest-free-slot
    picker that stays inside a band and extends the array only within it, so a
    full band **overflows (returns None)** rather than spilling past slot 99.
  - **Design decision — ownership has no on-disk tag.** The vendor format
    carries nothing per-lineal/label, and the vendor keys slots by index
    (writing slot 10 with 1–9 absent round-trips as slot 10) and auto-writes
    to the lowest free index. So the low GENERAL band is a deliberate reserve:
    the vendor's auto-writes land there and stay "general", never colliding
    with a sensor band. Owner is inferred from the band on load and
    re-materialized on save — a pure function of index, no schema change.
  - **`model/centerline.py`** — `_find_chains` now also returns each chain's
    lowest Lineal index (the owner signal). New `save_/load_centerlines_owned`
    and `save_/load_lineals_owned` band-scope allocation; a multi-segment
    centerline is placed wholly within one band or skipped as overflow. The
    plain `save_centerlines`/`save_lineals`/`load_*` are kept as **GENERAL
    wrappers** so every existing caller and test is unchanged (the GUI adopts
    the `_owned` variants in Item 22).
  - **New `model/labels.py`** — the Textlabel parallel (`save_/load_labels`,
    `_owned`). A label is one slot (no chaining); free = disabled. Disabled
    slots park at the vendor's `Position -9999` sentinel, not `(0,0)`.
  - **`model/multifile.py`** — split now **blanks the *other* file's band**
    (primary keeps GENERAL+FILE1, secondary keeps GENERAL+FILE2), so the
    GENERAL block duplicates into both files and each `_3_4` renders its own
    sensor guides standalone. Merge recombines by band (GENERAL+FILE1 from
    primary, FILE2 from secondary; primary's GENERAL wins). New
    `general_blocks_match` is the annotation soft-warn, parallel to
    `check_background_match`, for when two overlaid files' GENERAL bands
    disagree. Two existing split tests updated for the new (general-in-both)
    ownership; the split→save→load→merge acceptance and the real Franklin
    pair still round-trip losslessly (Franklin's labels all sit in the GENERAL
    band, so merge is unchanged from before — no regression).
  - **Interim behavior between sessions.** Until Item 22 wires ownership to
    the active sensor, the GUI still calls the plain wrappers, so a re-save
    collapses all annotations to GENERAL (→ both files). That's the desired
    "general to both files" change; per-file scoping arrives with the Item 22
    assignment UI.
  - **Verification.** New `tests/test_bands.py` (14) + `tests/test_labels.py`
    (9), band cases added to `test_centerline.py`/`test_lineals.py`/
    `test_multifile.py`. Full suite green (423). Real-file check against the
    Franklin pair: the `_3_4` file's enabled labels infer GENERAL, merge
    recombines, re-split keeps `general_blocks_match` True. IPRJ_FORMAT.md
    updated (split-ownership + Annotations sections).

- 2026-07-05 — **ROADMAP Item 22 done (Opus, session 2 of 2) — text-label GUI
  entity + sensor assignment + centerline-name labels.** Wires Item 21's
  band-scoped persistence to the active sensor and adds text labels as a
  first-class GUI entity.
  - **Text Label = a 4th Draw sub-type, not a new tool.** The ROADMAP calls it
    a "draw kind", so it joins Event/Ignore/Lineal in the Draw toggle (key
    `a`) rather than getting its own primary tool. That meant teaching the
    shared `DrawingController` a **`"point"` shape**: 1-click commit,
    `element_points`/`set_element_points`/`_hit_zone` handle a single-point
    `TextLabel`, and it reuses selection/move/delete/undo/nudge for free. The
    alternative — a bespoke `LabelController` à la `CenterlineController` —
    would have re-implemented all of that; a point label genuinely fits the
    zone machinery once hit-testing knows about 1-point elements. *Caveat:* a
    point label's vertex and body coincide, so Ctrl-drag-copy only fires when
    nothing is pre-selected (the vertex-grab check runs first).
  - **Draw-time editor bar (owner request, same session).** Text Label draw
    mode shows an inline editor (the properties dialog's fields — text / size /
    color / B·I·U / rotation) whose live values are what a click places, so
    editing happens at/before placement, not only via the Edit workflow. The
    controller pulls the draft on commit (`DrawingController.label_draft`
    supplier → `Viewer.label_draft`, applied by `_apply_label_draft`, keeping
    the clicked anchor) instead of the auto-numbered "Label N"; the draft
    ghosts at the cursor (translucent) so the placement is a WYSIWYG click.
  - **Ownership as a transient `_owner`, not an on-disk tag.** Generic lineals
    and text labels carry their band `Owner` as an instance attribute
    (`element_owner`/`set_element_owner`); centerlines carry it on the
    controller (`CenterlineController.owner`). The controller stamps a freshly
    drawn owned element from an `owner_supplier` (`Viewer.current_owner`). A
    toolbar toggle picks **General vs. Active sensor** (`assign_general`);
    `current_owner()` resolves Active sensor via `sensor_owner(active_si)`, so
    the band tracks whichever sensor is live (S1/2 → `_1_2`, S3/4 → `_3_4`). A
    hint label surfaces the resolved band; the label properties dialog also
    exposes an explicit owner select. The GUI now calls the `_owned` save/load
    variants throughout; `save_labels_owned`'s overflow `skipped` list is
    surfaced like the lineal one.
  - **Centerline names now persist — as a no-rotation label at the far end.**
    Retires the "not persisted" note on `CenterlineController.name` (Item 20).
    Each controller manages a `name_label` in the label pool:
    `Viewer.sync_centerline_labels` creates/moves/updates/drops it on
    rename, geometry edits, and before save (position = furthest-from-stop-bar
    vertex, rotation 0, band = the centerline's owner). On load the link is
    **re-derived geometrically** (`model.labels.match_name_labels`, mirroring
    `derive_attachments`): a no-rotation label within `NAME_LABEL_TOL` of a
    centerline's far end is adopted as its name label and its text taken as the
    name. One-to-one, nearest-wins, so coincident far ends resolve
    deterministically. Editing a name label's text (or rotating it away) is
    therefore a legitimate way to rename/detach across reloads.
  - **Model additions** — `domain.new_label`/`insert_label`/
    `is_placeholder_label` (the label draw-kind trio, parallel to the lineal
    ones); `model/labels.py` gains `is_name_label` + `match_name_labels`
    (pure geometry, the re-derivation core).
  - **Verification.** New model tests for `match_name_labels`/`is_name_label`
    and controller tests for the point shape + owner stamping/copy
    (`test_labels.py` +5, `test_drawing.py` +6). Full suite green (434).
    Headless end-to-end: named-centerline → sync → save → reload re-derives
    the name and adopts (not duplicates) its label; a FILE2 name label splits
    only into `_3_4` while a GENERAL label duplicates into both; `svg()`
    renders styled/rotated labels. IPRJ_FORMAT.md gains the centerline-name
    label convention (a soft, re-derived interpretation, parallel to the
    centerline-encoding note — no new on-disk field; Item 21 already covered
    the label array and bands).

- 2026-07-07 — **ROADMAP Item 23 done (Opus) — toolbar/layout planning +
  mockups; no command wiring.** Synthesized the owner-batch toolbar requests
  into one target layout and delivered runnable static mockups
  (`gui/toolbar_mockup.py`, port 8081, inert buttons) plus a decision doc
  (`ITEM23_TOOLBAR_PLAN.md`) that specifies exactly what Items 24 & 27 build.
  - **Three options mocked, Option A recommended.** A · two-tier (segmented
    sub-kind toggle, filename inline on row 1), B · single command bar
    (sub-kind dropdown, filename in the folder menu, ~30 px more canvas), C ·
    left tool rail. Picked **A**: it matches the ROADMAP's own "both bars fit
    `calc(100vh - 120px)`" framing, reuses the shipped Phase-3
    build-once/`set_visibility` context-bar mechanic (smallest code delta),
    and keeps the six draw sub-kinds glanceable. B is the documented fallback
    if the canvas feels short (pure re-parent of A's controls); C is deferred
    (biggest departure for little gain). All three share the same control set,
    so a later switch to B/C changes arrangement, not semantics.
  - **Decided layout.** Top tool toggle shrinks `Edit·Draw·Template·Centerline·
    Sensor·Background` → **`Draw·Edit·Background`** (Draw first); Sensor +
    Centerline (Item 24) and Template (Item 27) fold into the `draw_kind_toggle`
    sub-kinds. Per-sub-kind context matrix + the Edit/Background contexts are
    pinned in plan §3.2.
  - **Unified Owner/Sensor dropdown — the load-bearing seam.** `sensor_sel` +
    `assign_toggle` collapse into one `ui.select` (options General + S1…Sn;
    General suppressed for Event/Ignore zones + Sensor mgmt). Resolution:
    **keep `active_si` and `assign_general` as two internal fields and project
    them through one widget** (§3.3) — General sets `assign_general` without
    touching `active_si`, a sensor sets both; `current_owner()` + band routing
    stay untouched. The many `active_si` readers (§8) are the chief Item-24 risk.
  - **Row-1 grouping + filename (owner review, refined the recommendation).**
    After eyeballing the mockups the owner picked A and asked for command
    grouping by *type* with `|` separators: modes (Draw/Edit/Background)
    top-left, permanent drawing tools (snap/ruler/**clear-ruler**/undo/layers/
    fit) left-justified against Background behind a `|`, and a right-justified
    **file cluster** (folder · template-editor · filename · save) with the
    **filename beside Save**. The earlier "move filename to row 2" call is
    retired; the `"iprj Designer — "` product prefix is dropped. (Also restored
    the clear-ruler button the first mockup pass had accidentally dropped.)
  - **Zone table Auto/On/Off**, right-justified on **row 2** above the table
    (owner's call — not the row-1 tool cluster). Auto = visible only when a zone
    kind is the active target. Height budget: keep `- 120px`, verify empirically.
  - **Item 27 home decisions.** Template = a mode of Event Zone (no sub-kind);
    `template_follow_switch` + `template_cl_sel` → one CL dropdown bound to every
    drawn event zone via Item 26 membership; **template-editor button moves to
    the row-1 file cluster** (owner's call — it's a document-level action, so it
    leaves the Event-Zone context bar and stays persistently visible).
    Provisional 24/27 scope boundaries hold — 23 refines, doesn't re-cut them (§9).
  - **No model/ change** (planning only): mockup imports nothing from `model/`;
    band routing/`current_owner()` unchanged, so no pytest/IPRJ_FORMAT delta this
    session. Validated the mockup runs (HTTP 200) and drove it headless
    (Playwright: every tool/sub-kind switch + all three tabs, zero console
    errors).
- 2026-07-07 — **ROADMAP Item 24 done (Opus, one session) — toolbar &
  drawing-mode consolidation, implementing Item 23's Option A** (`gui/app.py`,
  `model/bands.py`). Sensor + Centerline fold from top-level tools into Draw
  sub-kinds; the active-sensor selector + General/Active-sensor toggle collapse
  into one Owner/Sensor dropdown; Row-1 chrome regrouped. (Template still rides
  with Item 27.)
  - **Effective-mode, not a mode rename — the key design call.** Rather than
    rewrite the ~40 `v.mode == …` branches in on_down/on_move/on_up/on_key/
    refresh, `v.mode` stays the *effective* mode the state machine reads
    (`Draw`/`Edit`/`Background`/`Centerline`/`Sensor`/`Template`). The 3-entry
    tool toggle + the 6-entry `draw_kind_toggle` feed one pure
    `effective_mode(tool, sub_kind)` (module-level, unit-tested): Sensor/
    Centerline sub-kinds resolve to their own modes, everything else under Draw
    to `Draw`. So the drawing-controller branches are untouched — only the
    toggle wiring changed. `change_tool`/`change_draw_kind` share one
    `_enter_mode()` doing the teardown `change_tool` used to (clear template
    preview, end centerline drag, cancel rotate, drop marquee).
  - **`draw_kind_name` diverges from the sub-kind toggle by design.** The
    toggle now carries 6 values; `draw_kind_name` (the Viewer field
    `draw_zones()`/`DRAW_KINDS` read) keeps the last *drawing* kind, so
    Centerline/Sensor sub-kinds don't break the zone/lineal targeting.
    `change_draw_kind` calls `set_draw_kind` only for real drawing kinds
    (`kind not in MODE_SUBKINDS`).
  - **Unified Owner/Sensor dropdown (plan §3.3) — `active_si` + `assign_general`
    stay the source of truth, projected through one widget.** New pure helper
    `model.bands.resolve_owner(assign_general, active_si, general_ok)` centralizes
    the rule so a stale `assign_general=True` can't leak GENERAL onto a
    sensor-scoped annotation. `general_offered(mode, draw_kind)` (module-level,
    tested) gates whether "General" is in the options — owned kinds + Centerline
    yes; zones, Sensor, and Edit no (Edit only scopes the active sensor, so on
    startup the dropdown reads "S1", not "General"). `refresh_owner_sel()`
    rebuilds options+value
    from the fields on every context change, behind a re-entrancy lock so its
    programmatic `set_options` echo can't flip `assign_general` (plan §8). All
    former `sensor_sel.set_value(si)` sites (table select, sensor drag,
    add/delete sensor) route through a new `activate_sensor()`/`refresh_owner_sel`
    instead. `current_owner()` + band routing unchanged, so **no `.iprj`
    format change** → no IPRJ_FORMAT.md delta.
  - **Row-1 chrome (plan §3.1/§4).** Product name dropped; filename is a muted
    inline label in a right-justified file cluster (template-editor · folder ·
    filename · save), folder beside the filename, filename beside Save, full
    path in the folder tooltip. Tool toggle `Draw·Edit·Background` (Draw first,
    `d`/`e` keys). Accelerators: `c`/`s` moved from tool keys to Draw sub-kind
    keys; `t` retired (Template gone until 27).
  - **Zone table Auto/On/Off (plan §5)** on a Row-2 button+menu, right-justified
    above the table; Auto shows it only when a zone kind is the active target
    (`_zone_kind_active()`, recomputed in `update_context_bar`). Stored as
    `Viewer.zone_panel_mode`.
  - **Template deliberately dormant between 24 and 27.** The plan sequences the
    Template fold into Item 27 (needs Item 26's CL membership), so Item 24
    removes Template from the tool toggle/`TOOL_KEYS` and hides `template_sel` /
    values / follow-switch / CL-select (the editor button moved to Row 1 and
    stays visible). Template *placement* is therefore temporarily unavailable
    from the toolbar until Item 27 wires it into Event Zone — an accepted
    interim per plan §7 ("already gone as of Item 24's toggle").
  - **Verified.** 460 pytest pass (19 new: `resolve_owner`, `effective_mode`,
    `general_offered`). App builds end-to-end under NiceGUI script-mode
    (HTTP 200, full toolbar rendered, no server errors); simulated-User click
    driving is blocked only by `ui.toggle` options not being findable elements
    (harness limit), so the mode/owner rules are covered by the pure unit tests
    instead. Height budget kept at `calc(100vh - 120px)`.

- 2026-07-07 — **ROADMAP Item 25 done (Opus, one session) — draw off the
  background: oversized canvas** (`gui/app.py`, `gui/viewport.py`). The drawing
  surface used to *be* the background: the `interactive_image` was sized exactly
  `image_w × image_h`, mouse `offsetX/Y` were bg-image pixels, and nothing could
  live past the image edge. Now the surface is a canvas **2× the background each
  way, background centered**, so zones/lineals/labels/sensors can be placed
  off-image.
  - **Origin decision (settled up front, per the item): world coordinates are
    untouched.** `world_to_image`/`image_to_world` stay anchored to the bg-pixel
    origin; the canvas offset (`canvas_off_x/y = image_w/2, image_h/2`) is applied
    **only at the render/mouse boundary** via two new `Viewer` helpers
    `world_to_canvas` (= `world_to_image` + offset) and `canvas_to_world`
    (= `image_to_world` of point − offset). So a load→save of an untouched
    project is a coord no-op (existing `test_roundtrip` still green, unchanged),
    and an off-image point is just a negative / beyond-extent world pixel value —
    which the vendor format already stores as a plain float (confirmed: nothing
    clamps to image bounds). **No `.iprj` format change → no IPRJ_FORMAT delta.**
    `model/` stays pure — all the offset logic lives in the `gui` layer.
  - **DOM split so the bg bitmap isn't quadrupled.** Rather than composite a
    2×-sized (mostly transparent) PNG — which would 4× the decoded bitmap the
    memory-conscious file-source design (see the Viewer.__init__ note) exists to
    avoid — the layout now nests, inside a new transformed `stage` div, a *static*
    `ui.image` background at the canvas offset **plus** a **transparent,
    bitmap-free** `interactive_image` (no `source`, `size=(canvas_w, canvas_h)`,
    so its SVG viewBox comes from `size`, not a loaded image) that owns the SVG
    overlay and the mouse events. `offsetX/Y` are now canvas px (the overlay is
    the full canvas at natural size). Both children ride `stage`'s transform, so
    pan/zoom move them together.
  - **Transform + wheel moved from `ii` to `stage`.** `apply_transform` styles
    `stage`; the client-side `_WHEEL_ZOOM_JS` is bound to `stage` (so the JS
    `getComputedStyle`/write and the server's style stay on the same element).
    `set_bg_visible` now dims the separate `bg_img` directly (the old `.bg-off img`
    CSS hack is gone). Background-swap (`upload_background`) calls a new
    `_recompute_canvas()` so the canvas tracks the new image size.
  - **`Viewport.fit` gained a `content_origin`** so load/fit frames the
    *background* (passing the canvas offset), not the mostly-empty whole canvas;
    the off-image margin is reachable by panning. Default `(0,0)` keeps every
    existing caller/test identical.
  - **Verified.** 466 pytest pass (6 new: `test_canvas.py` — canvas is 2×/centered,
    world↔canvas round-trip identity, on-image geometry only shifts by the offset,
    off-image click → valid negative world point, bg-swap recompute; plus
    `test_fit_frames_offset_content`). Driven live under NiceGUI + Playwright on
    `ex27.iprj`: viewBox `0 0 3396 1760` (= 2× the 1698×880 bg), zone polygon
    renders at canvas = image+offset, mouse over bg-center reads world
    `(849, 440) px` = exact image center, mouse past the top edge reads
    `(849, −44) px` — a real off-image negative coord — no JS errors.

- 2026-07-07 — **ROADMAP Item 26 done (Opus, one session) — bulk-edit selected
  zones + explicit, persisted centerline membership** (`model/labels.py`,
  `gui/drawing.py`, `gui/app.py`).
  - **File-routing decision (settled first, as the item required): membership
    does NOT override a zone's file — sensor placement still does.** The owner's
    request was "a zone follows its centerline's band owner." But a zone can't
    move to `_1_2` without moving to a sensor in that file: `split_project`
    partitions strictly by sensor and the vendor stores zones in per-sensor
    arrays, so "membership picks the file" is structurally impossible for zone
    *bytes* without silently reassigning the sensor (which loses which sensor's
    detection field the zone covers — sensor and approach are orthogonal; one
    approach's detectors can span sensors). Resolution: membership is an
    **organizational grouping**, not a zone→file override. What *does* follow the
    centerline's band owner is the **membership label** (like the name label), so
    a sensor-owned group's membership travels to the right file. A zone with no
    centerline is unaffected (routed by its sensor). To actually consolidate a
    group into one file the user reassigns its **sensor** — which the bulk editor
    now does in one action. Recorded here + in IPRJ_FORMAT.md.
  - **Membership = the `attached` set, made explicit and persisted — no new
    parallel structure.** `CenterlineController.attached` already *was* "which
    zones belong here" (plus the station/offset corners restation needs); Item 26
    just changes how it is populated. New `attach_projected` (derive corners from
    the current datum by projection — accepts any zone shape, not only an exact
    station/offset rectangle), `detach`, `member_outputs`. The old geometric
    `derive_attachments` becomes a **backward-compat fallback**: it skips
    already-attached zones, and the GUI runs it only when the loaded project
    carries *no* membership label (a pre-Item-26 file). So a file touched by this
    feature is fully label-driven; a legacy file still auto-groups on open.
  - **Persistence mirrors the Item 22 name label; the member key is the zone
    slot, not OutputNumber.** The first cut keyed members by `OutputNumber`, but
    the owner flagged that real projects reuse outputs (count loops all on 9),
    so it isn't unique — reload would attach the wrong zone. Switched to each
    member's **(sensor index, zone index) vendor slot**, which *is* unique and
    round-trips exactly: `save_iprj` writes every `EventZone_{zi}` slot verbatim
    and `load_iprj` restores it to that index (the property `model/bands.py`
    already leans on). Intra-session index shifts (a delete compacts the list)
    are a non-issue: in-session membership is tracked by `id(zone)`, and
    `sync_membership_labels` recomputes the slot from live positions on every
    save. The label `Text` is `"[name]: [sensor_zone slots]"`
    (`format/parse_membership_label`); GUI `sync_membership_labels`
    creates/refreshes/drops one per named centerline with members (parked
    top-left, band = the centerline's owner); `_derive_membership` re-parses on
    load and re-attaches by projecting each slot's zone onto the datum — **zero
    geometry matching**. Told apart from a plain/name label purely by its
    `name: sensor_zone-list` text shape (`is_name_label` excludes it, so the two
    managed labels never cross-adopt).
  - **Absolute sensor indices + pair-role offset, so a bare `_3_4` half
    reconstructs.** Slots are written in absolute (merged-project) sensor space
    (0–3). The split renumbers the `_3_4` half's sensors to 0/1 on disk, so a
    naive local index would break when that half is opened standalone (the
    owner's requirement). Fix: the reader maps absolute↔file-local via the file's
    pair role (`Viewer._sensor_index_offset` — `+2` for a `_3_4` file, else 0),
    on both save (local→absolute) and load (absolute→local), so absolute `2_0`
    resolves to the `_3_4` half's local sensor `0`, a slot for a sensor absent
    from the loaded file just doesn't resolve, and the merged overlay reads
    straight through. **Limitation (documented):** only a *named* centerline
    persists membership (the label needs a name to re-link); in-session
    membership works regardless.
  - **Bulk editor.** `gui/drawing.bulk_reassign` (pure, tested) sets phase,
    nudges output ±1 (clamped ≥0, never set-to-N), and moves zones between
    sensor lists by **reusing `insert_zone`** — the same cross-file move the
    single-zone Properties dialog does. The `bulk_zone_properties` dialog (routed
    from Properties whenever >1 event zone is selected; the old "select exactly
    one" floor is gone) also sets the new centerline field for the whole group,
    and after a sensor move follows the zones to the target sensor and re-selects
    them. Membership is also an editable **Centerline** field in single-zone
    Properties and a **CL** column in the zone table.
  - **Verified.** 481 pytest pass (+15: `test_membership.py` ×5 — persist +
    reload-without-geometry, label follows centerline band, dropped when
    unnamed/empty, **bare `_3_4`-half reconstruction via the offset**, pre-Item-26
    geometric fallback; `test_labels.py` ×4 — slot parse/format round-trip +
    non-membership rejection + name-label exclusion; `test_drawing.py` ×6 —
    `bulk_reassign` phase/output/clamp/cross-sensor, derive-attachments skip,
    `attach_projected`/`member_zones`/`detach`). Headless `Viewer` drive: assign
    membership → sync → both `N_CL` and `N_CL: 0_0` labels in the pool → `svg()`
    renders.
  - **Bulk editor.** `gui/drawing.bulk_reassign` (pure, tested) sets phase,
    nudges output ±1 (clamped ≥0, never set-to-N), and moves zones between
    sensor lists by **reusing `insert_zone`** — the same cross-file move the
    single-zone Properties dialog does. The `bulk_zone_properties` dialog (routed
    from Properties whenever >1 event zone is selected; the old "select exactly
    one" floor is gone) also sets the new centerline field for the whole group,
    and after a sensor move follows the zones to the target sensor and re-selects
    them. Membership is also an editable **Centerline** field in single-zone
    Properties and a **CL** column in the zone table.
  - **Verified.** 480 pytest pass (+14: `test_membership.py` ×5 — persist +
    reload-without-geometry, label follows centerline band, dropped when
    unnamed/empty, pre-Item-26 geometric fallback; `test_labels.py` ×4 —
    parse/format round-trip + non-membership rejection + name-label exclusion;
    `test_drawing.py` ×6 — `bulk_reassign` phase/output/clamp/cross-sensor,
    derive-attachments skip, `attach_projected`/`member_outputs`/`detach`).
    Headless `Viewer` drive: assign membership → sync → both `N_CL` and
    `N_CL: 5` labels in the pool → `svg()` renders.

- 2026-07-07 — **ROADMAP Item 27 done (Opus, one session) — fold Template into
  Draw › Event Zone; one CL dropdown for every drawn zone** (`gui/app.py`,
  `gui/drawing.py`). Completes the Draw-hub fold (Item 24 did Sensor +
  Centerline).
  - **Template is a sub-state of "Draw", not an effective mode.** The old
    standalone Template tool went away in Item 24; rather than resurrect a
    `"Template"` effective mode, template placement is now the predicate
    `Viewer.template_placement_active()` = *Draw ∧ Event Zone ∧ a template
    picked*. The `on_down`/`on_move`/`on_dblclick`/Escape/`draw_zones`/status
    branches that used to gate on `v.mode == "Template"` (dead since Item 24
    dropped it from the tool toggle) now gate on that predicate, checked
    **before** the plain `mode == "Draw"` branch — so a picked template turns a
    click into a template drop and a blank picker leaves plain free-draw
    untouched. `effective_mode()` is unchanged (never returns "Template"); the
    drawing state machine still only sees Draw/Edit/Background/Centerline/Sensor.
  - **One CL dropdown replaces the Item-19 follow-switch + pick-select.** The
    two controls (`template_follow_switch` "along CL" bool + `template_cl_sel`
    "pick CL" idx) collapsed into a single `event_cl_sel` backed by one field,
    `Viewer.event_cl_idx`. Semantics simplified from three states to two: a
    centerline **chosen** ⇒ place *along* it (one click); **blank** ⇒
    aim-upstream (ref-then-second-click). The old "follow on, no pick ⇒ nearest
    within `CENTERLINE_SNAP_FT`" auto mode is **retired** — the owner picks the
    centerline explicitly now, so `Viewer.centerline_for` and the
    `CENTERLINE_SNAP_FT` constant are gone from the live path (the constant's
    doc moved to a tombstone; `geometry.nearest_centerline` stays, still backing
    the on-load geometric-membership fallback in `derive_attachments`).
  - **The CL dropdown governs *every* event zone, not just templates (the
    Item 26 dependency).** Added an optional `on_commit(el)` hook to
    `DrawingController`, fired in `_commit_element` after a fresh element lands
    (covers free-draw polygons, 2-click segments, and dimensioned rects; bulk
    `insert_many` and Edit-mode copies bypass it and own their own membership).
    The Viewer wires it to `on_zone_committed`, which — for the Event-Zone kind
    with a CL picked — routes the drawn zone through Item 26's
    `set_zone_membership`, so a plain hand-drawn zone joins the chosen
    centerline's group exactly like a template's detectors do. Blank picker ⇒ no
    membership; non-Event-Zone kinds never take one.
  - **Chrome per the Item 23 plan (§7).** The template-editor button already
    lives in the Row-1 file cluster (moved there in Item 24), so it stays put
    and persistently visible. `update_context_bar` now shows the `template`
    picker + `event_cl_sel` in Draw › Event Zone (and the placement-values
    button only once a template is picked); everything template-related is
    hidden in every other tool/sub-kind. `open_template_editor` opens straight
    to whatever template is picked (was gated on the retired `mode ==
    "Template"`). The `t` tool key stays retired (template is reached via `z` →
    the Event-Zone bar).
  - **No `.iprj` format change.** Template placement, the CL dropdown, and the
    membership binding all reuse Item 26's existing membership-label
    persistence; no new persisted field or label shape, so IPRJ_FORMAT.md is
    unchanged.
  - **Height budget re-verified (plan §6).** Kept `calc(100vh - 120px)`. The
    CL dropdown was added to the existing Event-Zone context row, which is
    `no-wrap overflow-x-auto`, so it scrolls horizontally rather than growing:
    headless drive at 1500×950 measured Row 1 = 32 px and the (now busiest)
    Event-Zone Row 2 = 40 px, a single line, and the viewport
    (`calc(100vh-120px)` = 830 px) sits flush at the window bottom. Both
    toolbar bars fit; no regression from this item. (A pre-existing ~50 px
    overflow from the *status bar below* the viewport is independent of Item 27
    — the viewport budget only accounts for the top chrome — and was left as-is.)
  - **Verified.** 492 pytest pass (+11 `tests/test_template_fold.py`:
    `template_placement_active` gating ×3, `template_target_centerline`
    picked/blank/datum-less ×3, `on_zone_committed` membership picked/blank/
    non-event-zone ×3, `DrawingController.on_commit` fires-once + end-to-end
    free-draw→membership ×2). Live Playwright drive (raw-PNG project): Draw ›
    Event Zone shows the template picker + along-CL dropdown; Ignore Zone hides
    them; picking a template opens the placement-values prompt and reveals the
    placement-values button; no console/page errors.

- 2026-07-08 — **Height budget fix (Opus) — the app was ~one row too tall on
  every machine** (`gui/app.py` layout only). The owner ran the app after the
  Items 23–27 batch and found it still overflowed the window by about one row;
  the batch's "height budget" checkboxes (Item 24 "-120px kept", Item 27
  "re-verify") had only ever confirmed the *two toolbar bars* fit, never that
  the whole page did.
  - **Root cause (reproduced, not machine-specific).** The viewport div and the
    zone panel were both `height: calc(100vh - 120px)`. That `120px` covered
    only the chrome *above* the viewport (top padding + the two toolbar rows +
    gaps ≈ 120px), so the viewport stretched flush to the window's bottom edge
    and the **status bar below it had no budget** — it plus the row gaps hung
    off the bottom. A headless Chromium sweep confirmed a *constant* 53px
    overflow at window heights 760/900/1080 (a machine quirk would vary; a fixed
    offset is structural), with `viewportBottom == windowHeight` every time.
  - **Fix: a real flex column, no pixel constant.** Pinned `.nicegui-content`
    to `height: 100vh; padding: 0; gap: 0; overflow: hidden` (via `ui.query`),
    made the canvas row `flex-1 min-h-0` so it absorbs exactly the leftover
    space, and changed the viewport div + zone panel from `calc(100vh - 120px)`
    to `height: 100%`. The toolbar rows and status bar now sit at their natural
    heights and the canvas fills the rest — correct on any font/DPI/mode with
    nothing to keep in sync. (`Viewport.fit` already reads the live viewport
    `clientHeight`, so framing adapts automatically.)
  - **Verified.** Headless sweep at window heights 700/760/900/1080 in Draw ›
    Event Zone (the busiest bar): **0px overflow** at all four, status bar fully
    on screen (bottom == window height), viewport height scales with the window
    (chrome is now exactly 32 + 40 + 21 = 93px of natural row heights). 492
    pytest still pass (layout-only change); no console/page errors.

- 2026-07-08 — **Two post-batch UI fixes (Opus) — zone-table width + ruler
  auto-exit** (`gui/app.py`; both issues the Items 23–27 batch introduced).
  - **Zone table no longer needs a horizontal scrollbar.** The panel was `w-96`
    (384px) but the 7-column table (S · On · Name · Ph · Out · Type · CL, plus
    the multi-select checkbox) measures ~466px, so Quasar's internal scroll
    container scrolled sideways. Widened the panel to `w-[32rem]` (512px) — the
    table now fills it (504px, zero internal overflow) and reads at a glance, at
    the cost of a little canvas width (owner's explicit trade). It grew past
    `w-96` as Item 16 (side-by-side detector table) and Item 26 (the CL column)
    added columns.
  - **Ruler exits when another tool is selected.** The ruler is a cross-tool
    overlay that captures clicks regardless of the active tool (Item 1), so once
    armed it blocked every other tool until toggled off — a trap once
    Sensor/Centerline/Template folded into the Draw sub-kinds (more ways to
    "pick a tool" that didn't clear it). Added `set_ruler_active(False)` to
    `_enter_mode`, the shared teardown for `change_tool` + `change_draw_kind`, so
    selecting any tool or Draw sub-kind drops the ruler. Verified headlessly: arm
    with `r` → select Edit → off; re-arm → switch sub-kind to Lineal → off.
  - 492 pytest still pass (GUI-handler/layout only); no console/page errors.

- 2026-07-08 — **ROADMAP Item 28: Record/Playback architecture & coordinate
  reconciliation (Opus)** — decision document only, no code. Full write-up in
  [RECORD_PLAYBACK_PLAN.md]; key resolutions:
  - **No coordinate-space conflict — it's a units multiply.** Audited against
    the real `86_US95&SH8` site: after `normalize_origin`, the designer's
    `sensor[0]` = (855.95, 313.82) px is *exactly* evo_replay's
    `(s0_px − Background_Pos)`. Both tools share one frame (background top-left
    origin, y-down, no rotation); evo_replay just expresses it in meters, the
    designer in world px / feet. The "meters vs feet" gap Item 28 flagged is a
    unit conversion, not two frames.
  - **`units.py` is not the flagged bug — it's *more* accurate than evo_replay.**
    Swept all 29 `sites/**/*.iprj`: `effective_meter_per_pixel` re-derives the
    calibrated scale from the reference pair (e.g. Banks 0.0762 vs vendor-rounded
    0.08 = 4.75%; divergence 0.87–4.75% across sites) and correctly falls back to
    stored only for the stale pair (ex27bg2). evo_replay uses the *rounded*
    stored value, so it carries up to ~4.75% error. **Decision:** playback reuses
    the loaded `Project` + `effective_meter_per_pixel`, never a second regex
    parse or evo_replay's scale — designer playback is therefore more accurate
    than evo_replay itself.
  - **The transform (EVO → world-feet):** `anchor_ft = px_to_ft(sensor[n].pos,
    emp)`; `world_ft = anchor_ft + m_to_ft(p_m − ref_m)`. The metric offset is
    *true meters* → `m_to_ft` only; `emp`/mpp touches **only** the pixel anchor.
    Scaling the offset by mpp is the tempting bug (re-adds the 2% error, worse
    with distance) — handed to Item 29 as the bug-prone line.
  - **Anchor is per-sensor, not global sensor-0** (one recording = one host =
    one sensor); reduces to sensor-0 for single-sensor sites, one anchor per
    recording for the 2-file/multi-sensor split.
  - **Module placement:** pure `model/replay.py` (parse + align, no pandas — a
    plain frame-indexed `Recording`/`Frame`/`TrackPoint`, since `model/` has zero
    pandas and the UI needs O(1) scrub-by-index); new sibling `capture/` package
    for the side-effectful async websocket recorder (can't live in pure `model/`
    or render-only `gui/`); `gui/` for the Replay mode + Record panel.
  - **Playback UX:** read-only Replay mode, no editing during playback, animated
    markers on a *separate* SVG layer driven by `ui.timer` reusing the existing
    feet→viewport transform; precompute+downsample all frames at load (Item 20
    zoom-freeze lesson).
  - **Recording:** `asyncio.create_task` on NiceGUI's own loop (never
    `asyncio.run`); files to `sites/<site>/recordings/`; credentials in a local,
    uncommitted config; single-host minimum for Item 31, multi-host optional.
  - Left `units.py`'s absolute-0.005 tolerance as a documented smell (not an
    action item — classifies every current site correctly). Checked off Item 28's
    boxes in ROADMAP.md.

- 2026-07-08 — **ROADMAP Item 29: Playback engine in `model/` (Fable)** — the
  pure `model/replay.py` engine, exactly per RECORD_PLAYBACK_PLAN.md.
  - **Shape:** frozen `TrackPoint` / `Frame` / `Recording` dataclasses (plan §3,
    no pandas — verified at import time that `model.replay` pulls in no
    pandas/numpy/PIL/GUI modules); `Recording.frames[i]` gives O(1) timeline
    scrub. Added `ref_seen` and `anchor_ft` beyond the plan's minimum fields —
    the GUI status line and the alignment tests both want them.
    `Recording.to_dataframe()` imports pandas lazily inside the method for
    notebook use. Public seam: `load_recording(project, path, sensor_index=…)` /
    `parse_recording(project, text, …)` + `anchor_world_ft`, re-exported from
    `model/__init__`.
  - **Transform implemented as §1b dictates:** `emp` (via
    `effective_meter_per_pixel`) touches only the pixel-space sensor anchor;
    the track offset from the `C;` reference converts with `m_to_ft` alone. A
    dedicated test asserts +10 m east = +32.8084 ft from the anchor and guards
    that the wrong (mpp-scaled) formula is distinguishable on the real site.
  - **Parse mirrors `evo_replay.parse_evo_data`** (timestamp / `F;` / `C;`
    lines, first `C;` wins, whole file scanned before aligning so a late `C;`
    still anchors; unparseable lines/entities skipped), plus it also captures
    `class` from the entity tuple. One deliberate divergence: an `F;` line with
    zero entities becomes an *empty Frame* rather than vanishing — an empty
    intersection is a real playback moment the timeline should keep.
  - **Guardrails (plan §6):** `downsample_rate`, `max_frames` (default 5000)
    and a new `max_points_per_frame` backstop (default 200) applied at load;
    `None` lifts a cap.
  - **No real recording exists to test against** — evo_replay's `DEFAULT_DATA`
    (`10_37_2_86_EVO_1770311735.txt`) is gone from disk and was never in git.
    The tests therefore run a format-faithful synthetic recording (built to
    `evo_recorder.py`'s exact output grammar) against the **real**
    `86_US95&SH8` site fixture: a point at the `C;` reference lands exactly on
    `sensor[0]`'s world-feet anchor, and an equivalence test pins our
    translation semantics to legacy `evo_replay.align()` on identical input.
    Consequence: plan §7's two open items (no-rotation and y-sign against a
    *live* stream) remain formally open — they are verified against
    evo_replay's behavior, which "works in practice," but the first real
    capture loaded in Item 30 is the true confirmation; a misalignment there
    means flip/rotate in exactly one place (`parse_recording`'s two transform
    lines).
  - Per-sensor anchoring (§1c) tested by re-anchoring the same stream to
    sensor 1 and asserting a rigid shift by the anchor delta. 508 pytest pass
    (16 new in `tests/test_replay.py`).

- 2026-07-08 — **ROADMAP Item 30: Playback UI — timeline + animated overlay
  (Opus, one session)** — wired the Item 29 engine into a read-only "Replay"
  mode in the NiceGUI shell, per RECORD_PLAYBACK_PLAN.md §4/§6.
  - **Replay as a fourth top-level tool** (`Draw/Edit/Background/Replay`).
    `effective_mode` returns `"Replay"`; the existing mouse handlers gate on
    `v.mode`, so drawing/editing is inactive with no per-branch guard needed
    while pan (space/middle-drag) still works — read-only for free. Entering
    the mode reuses `_enter_mode`'s teardown (drops the ruler / active draw
    tool); leaving it pauses playback. Loading a recording never mutates the
    `Project`.
  - **Separate marker layer (plan §4).** A second full-canvas
    `interactive_image` is stacked *above* the static `ii` overlay inside
    `stage` with `pointer-events:none`, so it rides the same pan/zoom transform
    and mouse events fall through to `ii` beneath. Only this layer's `content`
    is rewritten each tick (`refresh_replay_layer`), never the full `svg()` —
    the static zone/centerline overlay renders untouched below. Off-Replay the
    layer is `""` (invisible, inert).
  - **Coordinate path reuses the one seam.** `Viewer.replay_point_to_canvas`
    converts the engine's world-feet back to world-px with the *same*
    calibrated `effective_meter_per_pixel` the anchor used (exact round-trip),
    then `world_to_canvas` — the feet→viewport path every overlay object shares.
    Verified headless on the real `86_US95&SH8` site + the synthetic recording:
    a track point on the `C;` reference renders exactly on sensor-0's canvas
    position (this is the live-alignment confirmation plan §7 handed forward
    from Item 29 — no rotation/sign flip needed).
  - **Transport.** Load dialog (file picker seeded from the site folder +
    `recordings/`, an anchoring-sensor select, and a downsample knob) →
    `load_recording`. Play/pause, 0.5/1/2/4× speed, ±1 frame step, and a
    timeline scrubber, all funnelled through one `set_replay_frame(i)` seam so
    the slider, marker layer, and status line never drift. A `replay_pos` float
    accumulator lets sub-1× speeds animate; playback stops (doesn't loop) at the
    last frame and restarts from 0 on the next play.
  - **Guardrails (plan §6).** Fixed 10 fps `ui.timer`, `active=False` until
    play so it costs nothing off-Replay; per-tick work is O(markers in frame)
    on a small string; the engine's load-time downsample/frame-cap keep a long
    capture from animating 50k frames — carrying forward the Item 20
    zoom-freeze lesson.
  - **Marker styling** mirrors `evo_replay`: color by sensor (`oid % 10` →
    cyan/yellow/lime/magenta/orange/deepskyblue, white fallback) with the
    trailing-4-digit id over each marker. Those two are pure helpers
    (`model.replay.marker_color` / `short_id`) so they're headless-testable and
    the GUI SVG builder just consumes them. 511 pytest pass (3 new render-helper
    tests); GUI wiring exercised by hand + the headless alignment check, and the
    page confirmed to server-render with the Replay tool present.

- 2026-07-08 — **ROADMAP Item 31: Live Recording Integration (Sonnet, one
  session)** — folded `../evo_recorder.py`'s websocket auth + raw-stream
  capture into a "Record" panel, per RECORD_PLAYBACK_PLAN.md §5.
  - **New sibling package `capture/`** (peer of `model/`/`gui/`, plan §2):
    `capture/recorder.py`'s `RecordingSession` ports `evo_recorder`'s login +
    `async for message in websocket` loop unchanged, wrapped so `start()` is
    `asyncio.create_task` on NiceGUI's own *running* loop (never
    `asyncio.run`, which would collide with uvicorn's) and `stop()` cancels
    the task and awaits it so the `with open(...)` block closes the file.
    The blocking login POST runs through `asyncio.to_thread` so it can't
    stall the event loop other sessions/the GUI share. `capture/hosts.py`
    seeds the panel from `evo_recorder_multi.py`'s host list, layered with a
    gitignored `hosts.local.json` override (plan §5's "never commit new
    credentials" — device defaults already public in the committed scripts).
  - **Session lives on `Viewer.record_sessions` (keyed by host), not the
    dialog.** Closing the Record panel without Stop leaves the capture
    running server-side — the same "close ≠ stop" model as leaving
    `evo_recorder.py` running in a terminal — and reopening the panel finds
    it again via `current_session()`. Verified by hand: started a capture
    against an unreachable host, closed the dialog mid-connect, reopened it,
    and the in-flight session (then its login-timeout error) was still there.
  - **File placement** follows plan §5: `sites/<site>/recordings/`
    (`v.source.parent / "recordings"`), filename
    `{host_underscored}_EVO_{epoch}.txt` matching `evo_recorder`'s own
    convention — already covered by the repo's `*EVO*.txt` gitignore rule.
  - **Hand-off to Item 30.** `load_replay_recording` grew optional
    `preset_path`/`preset_sensor` params (both defaulted, so the existing
    `on_click=load_replay_recording` toolbar wiring is untouched — NiceGUI's
    `expects_arguments` only passes the click event to handlers with a
    required parameter). The panel's "Load into Replay" button closes the
    Record dialog and reopens the Item 30 load dialog with the finished
    file's path pre-filled; the user still picks the anchor sensor there
    rather than duplicating that control in both dialogs.
  - **Single-host minimum (plan §5)**, multi-host left out of scope — nothing
    stops two `RecordingSession`s (different hosts) running concurrently
    since they're keyed independently in `record_sessions`.
  - **Bug caught in manual testing, fixed before landing:** the status label
    read `s.running` to mean "recording," so it showed "recording — 0
    frames" during the auth handshake, before the websocket ever connected.
    Reordered the branch to check `st.connected` first, `s.running` second
    (→ "connecting…"), confirmed against a real login-timeout run (screenshot
    showed "connecting…" during auth, then "error: login failed" once the
    unreachable sandbox host timed out, Start reappearing correctly).
  - 6 new tests in `tests/test_capture.py` — no real device/network:
    `RecordingSession._run` driven against a fake async-iterable websocket
    (finite stream write-out, mid-stream cancellation, double-start no-op,
    login-failure status) plus `hosts.known_hosts` default/override merging.
    517 pytest pass (511 prior + 6 new). GUI exercised by hand via Playwright
    against the running NiceGUI server (Record dialog open, Start against an
    unreachable host, status transitions through connecting → error, dialog
    close/reopen preserving session state) — no browser console errors at
    any point.

## Appendix — example template (acceptance case, revised for Items 15/17/18)

45 mph approach, lanes `12' L | 12' T | 12' T | 12' R`, count loops, starting
input 33, lane-by-lane advance detectors, north approach (SB traffic),
phase 4 thru / phase 7 LT:

| Input | Description | Length (ft) | Width (ft) | Distance from stop bar (ft) |
|---|---|---|---|---|
| 33 | SBL Count | 5 | 12 | -15 |
| 34 | SBT Count 1 | 5 | 12 | -15 |
| 35 | SBT Count 2 | 5 | 12 | -15 |
| 36 | SBR Count | 5 | 12 | -15 |
| 37 | Ph 7 SBL Stop Bar | 30 | 12 | -5 |
| 38 | Ph 4 SBT Stop Bar 1 | 30 | 12 | -5 |
| 39 | Ph 4 SBT Stop Bar 2 | 30 | 12 | -5 |
| 40 | Ph 4 SBR Stop Bar | 30 | 12 | -5 |
| 41 | Ph 4 Decision 1 | 20 | 24 (across thru lanes) | 165.0 (ITE kinematic) |
| 42 | Ph 4 Decision 2 | 20 | 24 (across thru lanes) | 224.4 (even-spaced infill) |
| 43 | Ph 4 Advance 1 | 10 | 12 | 283.8 (safe stopping distance) |
| 44 | Ph 4 Advance 2 | 10 | 12 | 283.8 (safe stopping distance) |

Distances are computed from ITE kinematics at the template's design speed.
At 45 mph / 1.0 s extension: the stop-bar-side decision detector sits at
165.0 ft (2.5 s indecision-zone end), the single advance detector at 283.8 ft
(safe stopping distance), and one evenly-spaced intermediate decision detector
bridges the corridor at 224.4 ft (two 39.4 ft gaps). Decision and advance
lengths default to 20 / 10 ft but are template seeding inputs (Item 18). See
the decisions log for the Item 15/17/18 revision.
