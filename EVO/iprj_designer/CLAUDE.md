# CLAUDE.md — iprj Designer working conventions

Read ROADMAP.md first; sessions are scoped there. At the end of a session,
check off completed items, log decisions in the Decisions log, and update
IPRJ_FORMAT.md if format knowledge changed.

## Architecture (non-negotiable)

- `model/` is pure Python — no GUI framework imports, no global state. All
  iprj I/O, unit conversion, geometry, and template expansion lives here and
  is pytest-testable headless.
- `gui/` is a thin shell over `model/`. Assume it may be swapped or wrapped
  as a webserver later.

## Units & coordinates

- **Canonical internal unit: feet**, in world coordinates. Convert to/from
  iprj pixel units and meters only at the I/O boundary (`model/units.py`).
- iprj world space is pixel-scaled, **y-down**. Watch signs when converting
  to any y-up math. See IPRJ_FORMAT.md.
- User-facing dimensions and distances are always feet (this is US
  traffic-engineering work).

## Testing & data

- Round-trip tests run against the real files in `sites/**/*.iprj` — treat
  those as read-only fixtures; never modify files under `sites/`.
- Generated test output (`.iprj`, images) goes to a gitignored `tests/out/`
  or the scratchpad — iprj files embed base64 images and get large. Do not
  commit generated iprj files.
- Use the project venv at the repo root (see repo README).

## Interaction reference

The drawing/edit state machine is modeled on
`~/pyatspm/src/atspm/video/calibrate.py` (draw modes, snapping toggle, edit
mode with drag/copy, undo). Match its feel; upgrade it with real-unit
dimensioned drawing per ROADMAP Session 3.

## Style

- Follow existing repo conventions (plain scripts + notebooks elsewhere in
  EVO/); this subproject is more structured (packages + pytest) by design.
- Superseded code goes to `legacy/` rather than deletion (repo convention).

## Model routing / division of labor

The project owner runs sessions across three Claude models and routes work
by task shape, not strictly by directory:

- **Fable** — pure-Python algorithmic/mathematical work: geometry,
  ITE kinematic placement math, template expansion, and their pytest
  coverage. This is `model/` by default, but also covers any future
  pure-python interaction controller that happens to live under `gui/`
  (e.g. `gui/drawing.py` — no NiceGUI imports, same testability bar as
  `model/`). Fable has a tighter context/token budget than the other two,
  so scope its sessions to one module or one well-bounded algorithm at a
  time; hand it finished model-layer code as read-only context rather than
  the whole app.
- **Sonnet** — `gui/` framework wiring: NiceGUI layout, event handlers,
  dialogs, toolbar/table/canvas plumbing. Standard UI implementation work
  once the underlying pure-python piece it wires into already exists.
- **Opus** — architectural planning: decisions that touch multiple modules
  or change an established seam (e.g. multi-session state for the webserver
  upgrade, or how a new datum/geometry concept interacts with the existing
  undo model). Opus's output is a plan/decision, not the implementation —
  Sonnet or Fable does the actual coding session that follows.

The `model/`-is-pure-python rule above is the load-bearing constraint that
makes this split work; don't treat the folder name as the routing rule by
itself. See ROADMAP.md Sessions 6–8 for the sub-session breakdown this
produces in practice.
