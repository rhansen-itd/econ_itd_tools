# iprj Designer

A GUI tool for creating and editing Econolite Evo (Epiq) `.iprj` project files:
draw detection loops of known real-world dimensions over a scaled background
image, assign attributes (phase, output number, zone type), and export a
valid `.iprj`.

## Why

Existing workflow requires either the vendor software or the DXF → Excel → iprj
pipeline (`EVO/dxf_iprj_excel_conv.py`). This tool replaces that with direct
interactive drawing, modeled on:

- **pyatspm video calibration tool** (`~/pyatspm/src/atspm/video/calibrate.py`)
  — the interaction model: draw/edit state machine, point snapping, edit mode
  with drag-to-move and Ctrl-drag-to-copy, keyboard commands.
- **EVO gate drawing / plotly viewers** (this repo) — hover coordinates, zoom,
  background image with real-world scaling.

Unlike the video tool, **units matter here**: the user calibrates the
background image (known image width/height in feet, or two clicked points a
known distance apart) and then draws loops by real dimensions (e.g. a 10'×20'
rectangle placed by two clicks and typed lengths). The calibration maps
directly onto the iprj format's own `MeterPerPixel` / `ReferenceLength` /
`MeterReference0/1` fields.

## Design constraints

- **Browser-ready from day one.** A future goal is running this as a web
  server. The GUI framework is chosen so no rewrite is needed (see
  DESIGN_HISTORY.md's Session 2 entry — NiceGUI, with the geometry/model
  layer kept framework-agnostic either way).
- **Model/GUI separation.** All iprj parsing/serialization, unit conversion,
  and geometry lives in pure-Python modules with no GUI imports, testable
  against the real example files in `sites/`.

## Documents

- [ROADMAP.md](ROADMAP.md) — currently planned work, as named/numbered items
  ordered by priority, with suggested prompts for each.
- [IPRJ_FORMAT.md](IPRJ_FORMAT.md) — reverse-engineered notes on the `.iprj`
  file structure and coordinate system.
- [CLAUDE.md](CLAUDE.md) — working conventions for Claude Code sessions in
  this directory.

## Status

Session 1 complete (2026-07-02): `model/` has the pure-python data model
(`iprj_io.py`) with lossless load/save round-trip verified against all 29
`.iprj` files under `sites/`, and unit/calibration handling (`units.py`).
`scripts/overlay_zones.py` renders a site's zones over its background image
to eyeball coordinate correctness.

Session 2 complete (2026-07-02): **framework decided — NiceGUI** (see
ROADMAP decisions log). Run the viewer with

    python gui/app.py [site.iprj | image.png] [--port 8080]

(defaults to `sites/Banks/banks.iprj`) and open `http://localhost:8080`:
wheel zoom at cursor, drag to pan, live cursor readout in feet, marker
drops, existing zones/sensors/reference rendered, and both calibration
methods (known image width/height; two clicked points + typed distance).

Session 3 complete (2026-07-02): the drawing core. In Draw mode (`l`),
click 4 corners for a free loop, or click one corner, aim with the mouse,
and type the side lengths in feet (`10` Enter `20` Enter) for a dimensioned
rectangle extruded toward the mouse. `g` toggles snapping to other zones'
vertices/edge midpoints. Edit mode (`e`): click or `n`/`b` to select, drag
corners or the body, Ctrl-drag to copy, `x`/Del to delete, `u`/Ctrl-Z to
undo. The status line at bottom left tracks mode/snap/dimension entry.
State machine is pure python (`gui/drawing.py` + `model/geometry.py`).

Session 4 complete (2026-07-02) — **the MVP loop works end to end**: new
project from an image → calibrate → draw → attributes → Save → reopen.
Zone properties dialog (`p`, Enter, or double-click on a selected zone in
Edit mode): enable, name, phase, output, zone type, delay/extend, sensor
assignment, and a conditions table (velocities edited in mph, stored km/h
per the file format). Sensor mode (`s`): drag a sensor to move it, click it
for azimuth/height/GPS; "Add sensor" places one at image center. The
"active sensor" selector chooses which sensor new zones land on. Outputs
auto-increment across the project on draws and Ctrl-drag copies, and copies
bump a trailing number in the name ("SBT Count 1" → "SBT Count 2"). Save /
Save As write the full vendor-dialect `.iprj` with the embedded background
PNG. One caveat: a generated file has not yet been loaded in the vendor
software (not available on this machine).

Session 5 complete (2026-07-02): icon toolbar (undo/delete/zone-props,
snap switch, layer-visibility menu), a synced zone table panel (row
click/double-click selects/edits), arrow-key nudging, `f` fit-view, and
`Ctrl-S` save — all keyboard accelerators from earlier sessions still work.

Approach-template schema (`model/templates.py`, Phase 4.1): lane
configuration (movement + width + per-lane advance-detector toggle),
design speed and extension time, and editable per-detector rows
(spanned lanes, length, setback, output offset, phase role) that ITE
kinematic math *seeds* with defaults — including an advance-detector
chain sized for continuous dilemma-zone coverage. Approach direction,
thru/LT phase, and Base Output may each be baked into the template or
left as placeholders prompted at placement (output = Base Output +
per-detector offset). JSON load/save (v1 files upgrade transparently),
and a standalone form (`python gui/templates_ui.py`) to create/edit
template files under `templates/`.

The Phase 1 MVP (data model, drawing core, attributes, templates, centerline
placement) is complete, and so is everything since — a UX/file-management
pass, domain-accuracy fixes, the toolbar/multi-select overhaul, and the
advanced template engine — see [DESIGN_HISTORY.md](DESIGN_HISTORY.md) for
the full build log and decisions. Current work is tracked in
[ROADMAP.md](ROADMAP.md).

Run tests with `pytest` from this directory (uses the repo-root `.venv`).
