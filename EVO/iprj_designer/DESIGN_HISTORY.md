# Design History — iprj Designer

This file archives the build history and design decisions from the Phase 1
MVP (Sessions 1–7): the pure-Python iprj data model, the NiceGUI drawing/edit
core, zone attributes and iprj write-out, approach templates, and centerline
datum placement. See ROADMAP.md for the current Phase 2 execution plan.

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

## Appendix — example template (acceptance case for Session 6)

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
| 41 | Ph 4 Dilemma | 20 | 24 (across thru lanes) | ~100 (ITE kinematic) |
| 42 | Ph 4 Advance 1 | 10 | 12 | ~200 (ITE kinematic) |
| 43 | Ph 4 Advance 2 | 10 | 12 | ~200 (ITE kinematic) |

Distances for dilemma/advance are placeholders — compute from ITE kinematics
at the template's design speed. (Session 6.2's documented formulas give
165.0 ft dilemma / 283.8 ft advance at 45 mph — see the decisions log.)
