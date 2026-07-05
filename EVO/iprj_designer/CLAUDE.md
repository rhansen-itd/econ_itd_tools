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
mode with drag/copy, undo). Match its feel; the real-unit dimensioned
drawing built on top of it is documented in DESIGN_HISTORY.md's Session 3
entry.

## Style

- Follow existing repo conventions (plain scripts + notebooks elsewhere in
  EVO/); this subproject is more structured (packages + pytest) by design.
- Superseded code goes to `legacy/` rather than deletion (repo convention).

## Model routing / division of labor

The project owner runs sessions across three Claude models and routes work
by task shape, not strictly by directory. Fable is billed on usage credits,
so its sessions are scoped to **core implementation only** — a separate
model always runs the finishing pass. See "Core vs. finishing work" below
before writing a Suggested prompt for a Fable session.

- **Fable** — pure-Python algorithmic/mathematical work: geometry,
  ITE kinematic placement math, template expansion. Fable delivers the
  function/method/schema change itself and nothing past that — see below
  for what it must *not* be asked to do in the same session. This is
  `model/` by default, but also covers any future pure-python interaction
  controller that happens to live under `gui/` (e.g. `gui/drawing.py` — no
  NiceGUI imports, same testability bar as `model/`). Fable has a tighter
  context/token budget than the other two, so scope its sessions to one
  module or one well-bounded algorithm at a time; hand it finished
  model-layer code as read-only context rather than the whole app.
- **Sonnet** — `gui/` framework wiring: NiceGUI layout, event handlers,
  dialogs, toolbar/table/canvas plumbing, once the underlying pure-python
  piece it wires into already exists. Sonnet also runs the **finishing
  pass** for whatever Fable produced this round (see below) — including
  for Fable-only items that have no GUI counterpart at all; a finishing
  pass doesn't need a UI task attached to justify the session.
- **Opus** — architectural planning: decisions that touch multiple modules
  or change an established seam (e.g. multi-session state for the webserver
  upgrade, or how a new datum/geometry concept interacts with the existing
  undo model). Opus's output is a plan/decision, not the implementation —
  Sonnet or Fable does the actual coding session that follows, and Sonnet
  still owns the finishing pass afterward unless the finishing work itself
  is an architectural call (e.g. deciding what a new invariant should
  assert) — that's the one case it goes back to Opus.

The `model/`-is-pure-python rule above is the load-bearing constraint that
makes this split work; don't treat the folder name as the routing rule by
itself. See DESIGN_HISTORY.md's Sessions 6–8 (and the later
"ROADMAP Phase ..." decisions-log entries) for the sub-session breakdown
this produces in practice.

### Core vs. finishing work

"Core" = the implementation Fable is scoped for: the algorithm, the
method, the schema/data-shape change. "Finishing" = everything that
certifies and records that change, and it is **never Fable's job**:

- pytest coverage for the code Fable just wrote (new tests, or updating
  existing ones the change touches),
- the DESIGN_HISTORY.md entry for the session,
- checking off the item's boxes in ROADMAP.md,
- an IPRJ_FORMAT.md update, if the change touched the file-format
  contract (e.g. Item 11's origin-normalization).

A Fable Suggested prompt must say so explicitly — e.g. "implementation
only; skip pytest coverage and doc updates" — so Fable doesn't spend
budget on a finishing pass. The next prompt in the sequence (Sonnet,
usually — see above) picks up that finishing work explicitly, alongside
whatever GUI wiring it's already doing. Hand that session Fable's diff
plus a one-line note of what's untested/undocumented, so it isn't starting
cold on what needs finishing.

This split is why some ROADMAP items read "Target: Fable then Sonnet" even
when there's barely any GUI surface to wire — the "then Sonnet" half may
be mostly a finishing pass.
