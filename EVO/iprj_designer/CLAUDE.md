# CLAUDE.md — iprj Designer working conventions

Read ROADMAP.md first; sessions are scoped there. At the end of a session,
check off completed items, log decisions in the Decisions log, and update
IPRJ_FORMAT.md if format knowledge changed.

## Scoping new ROADMAP items

When the owner hands over a batch of requests to scope, **group them into
session-sized items** — each item should be a reasonable single working
session / one context window (plan + implement + tests + finishing pass),
**not** one item per bullet the owner listed. Merge small/related requests
(e.g. several toolbar tweaks → one "toolbar pass") and keep genuinely large
or independent work as its own item; split a request only when it's too big
for one session. Assign new stable IDs continuing from the last one used
(unless the owner says to restart), note dependencies between items inline,
and keep the Target/Scope/Suggested-prompt format the existing items use.

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

**Default to Opus, run whole items end-to-end in one session** —
architectural decision, model-layer implementation, GUI wiring, tests, and
the doc/checkbox finishing pass all together. The owner is not
usage-constrained on Opus, and Opus is at least as strong as Sonnet on
every task shape here (including NiceGUI wiring), so the old
plan-then-implement hand-off *across* models is no longer worth its cost:
each hand-off pays for a second session to re-ingest the diff and
re-establish what's untested, buying nothing when the same model could just
have continued.

- **Fable** — held in reserve as a **debugging escalation**, not a routine
  implementer (it's now billed on usage credits). Bring Fable in only when
  Opus or Sonnet has failed to fix a *specific* bug after a few honest
  passes; hand it the narrowed-down problem, not a fresh feature. A Fable
  session stays scoped to the fix — whoever escalated to it records the
  outcome.
- **Sonnet** — use only for a *whole* small, mechanical, low-ambiguity item
  (a pure rename, boilerplate wiring over a piece that already exists) when
  you'd rather not spend an Opus session on it. Assign it the entire item,
  finishing pass included; **never** split one item across Opus-plan +
  Sonnet-implement — that reintroduces the hand-off tax this section exists
  to avoid. Sonnet buys speed/cost here, not a better result, so reach for
  it only when the task is genuinely a toss-up on quality.
- **Opus** — everything else, which is most things: anything with design
  ambiguity, cross-module reach, or a new seam, plus routine feature work
  where a single capable session end-to-end beats a hand-off.

The `model/`-is-pure-python rule (see Architecture above) is the
load-bearing constraint regardless of who implements — keep it; don't let a
single-session flow blur `model/` and `gui/`.

### Finishing work is part of the same session

Every item is *certified and recorded*, not just coded. Whichever model runs
it owns all of the following in the **same** session — this is no longer a
separate hand-off pass:

- pytest coverage for new/changed model code,
- the DESIGN_HISTORY.md entry for the session,
- checking off the item's boxes in ROADMAP.md,
- an IPRJ_FORMAT.md update, if the change touched the file-format contract.

(Historical note: earlier rounds split "core" vs. "finishing" across
Fable→Sonnet hand-offs — see DESIGN_HISTORY.md's Sessions 6–8 and the
"ROADMAP Item …" decisions-log entries. That routing predates this change;
don't reintroduce it.)
