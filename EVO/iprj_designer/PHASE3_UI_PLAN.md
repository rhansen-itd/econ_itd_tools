# Phase 3.1 — UI Architecture Plan (for Phase 3.2 to implement)

Opus planning output per [[ROADMAP.md]] Phase 3.1. Phase 3.2 (Sonnet, with a
Fable pure-python pass — see §7) implements this. It covers three things the
ROADMAP asks for: **reorganize the overflowing toolbar into a context-sensitive
command surface**, **restructure the single "Draw" mode into element sub-modes
(Loop / Lineal / Ignore Zone)**, and **handle multi-select gracefully** — plus
the two things those force decisions about: whether **Pan** stays a mode, and
how the new draw kinds and multi-select touch the pure-python
`DrawingController` seam.

Read the current state in [[gui/app.py]] (`build_ui`'s toolbar, `on_down`/
`change_tool`, `svg()`), [[gui/drawing.py]] (`DrawingController`,
`CenterlineController`), and [[model/domain.py]] (`IgnoreZone`/`Lineal`
helpers, `rotate_points`/`rotation_angle_deg`) before starting.

---

## 1. Problems being solved

1. **Toolbar overflow.** One `ui.row(... overflow-x-auto)` holds ~26 controls:
   a 9-entry mode toggle plus file, snap, undo/delete/props, sensor selector +
   add, calibrate, centerline selector + add, template selector, layers, fit,
   clear, save, save-as, panel toggle. Adding Lineal + Ignore Zone draw modes
   and rotation would push it to ~11 modes and even more buttons. It already
   scrolls horizontally; it does not scale.
2. **"Draw" is monolithic.** `change_tool` maps "Draw" → `ctrl.set_mode("draw")`
   and the controller only ever builds `EventZone`s into the active sensor's
   `event_zones`. Phase 2 shipped pure-python models for **Ignore Zones**
   (polygons, per-sensor, cap 10) and **generic Lineals** (2-point lines,
   project-wide pool, cap 100) with no way to draw them.
3. **Pan is the default mode and does nothing else.** The app opens in "Pan",
   where a left-drag pans and clicks are inert — the user must switch tools
   before anything selects. Middle-button drag already pans in *every* mode
   (`on_down`: `button == 1 or (button == 0 and v.mode == "Pan")`), so the
   dedicated mode duplicates a gesture that already works globally.
4. **Selection is single.** `DrawingController.selected: int` drives rendering,
   the zone table (`selection="single"`), delete, nudge, drag, and the
   properties dialog. Group move / group delete / rotate-a-set all need a
   selection *set*.

---

## 2. Target tool taxonomy

Collapse the flat 9-entry toggle into **6 primary tools**, several of which
carry a **sub-type** shown in the context bar (§3). This groups related canvas
utilities and leaves room to grow without widening the top row.

| Primary tool | Sub-types (context bar) | Replaces / folds in | Accel |
|---|---|---|---|
| **Select** (default) | — | Edit **+ Pan** (see §5) | `v` / `e` / `Esc` |
| **Draw** | Loop · Ignore Zone · Lineal | Draw (loop only today) | `d` |
| **Template** | — (template picker in context bar) | Template | `t` |
| **Centerline** | — (centerline picker in context bar) | Centerline | `c` |
| **Sensor** | — (sensor picker in context bar) | Sensor | `s` |
| **Measure** | Ruler · Calibrate 2-pt · Marker | Ruler + Calibrate 2-pt + Marker | `r` |

Rationale for the groupings:
- **Select** is the new home mode; it does selection, single/multi, drag-move,
  and hosts the rotate action. See §5 for why Pan folds in here.
- **Draw** gains a sub-type toggle. All three sub-types are "click geometry onto
  the canvas"; the difference is *what element* and *what shape* (§4).
- **Measure** groups the three transient "drop points on the canvas" utilities
  (Ruler, Calibrate 2-pt, Marker). They never coexist with drawing and share a
  "clear" affordance; folding them removes three top-level slots.

### 2.1 Accelerators (owner-specified) — and the two conflicts they create

Top-level tool keys: **`d` Draw**, `v` (or `e`) Select, `t` Template, `c`
Centerline, `s` Sensor, `r` Measure. **Within Draw, the sub-type keys are
`z` Zone/Loop · `l` Lineal · `i` Ignore** (a sub-type key also enters Draw if
the user isn't in it yet, the way `s` enters Sensor from anywhere). Keep the
rest working unchanged: `g` snap, `u`/Ctrl-Z undo, `f` fit, `p` properties,
arrows nudge, `x`/Del delete, Ctrl-S save.

Two collisions this reshuffle creates, both resolved here (both are
pure-python `gui/drawing.py` changes → Fable, 3.2a):

1. **`d` Draw-mode vs. `d` dimension-entry.** `_key_draw` today starts
   dimensioned-rectangle entry on `d` *or* a digit
   (`starts_dim = name == "d" or name.isdigit()`). Making `d` the top-level
   Draw accelerator (early-return in `on_key`) would shadow that. **Resolution:
   drop `d` from `starts_dim` — dimension entry starts by typing a digit after
   the first corner** (the `d` prefix was only a convenience; digits already
   trigger it). Update the status hint and the app docstring accordingly.
2. **`l` was "enter Draw" — now it's the Lineal sub-type.** Remove the old
   `l`→Draw binding in `on_key` *and* the `l`/`e` set-mode shortcuts inside
   `DrawingController.key` (they'd otherwise shadow the new sub-type/Select
   meanings). All tool/sub-type accelerators are handled at the **app level**
   (setting `tool.value` / the draw sub-type toggle) with an early return
   before delegating to `v.ctrl.key(...)`, so the controller never sees
   `d`/`z`/`l`/`i`/`v`/`e` as mode keys anymore. `z` is safe (only ever used as
   Ctrl-Z — the modifier distinguishes it from plain `z`); `i` is unused today.

---

## 3. Toolbar architecture — two tiers

Replace the single row with **two rows**:

**Row 1 — persistent chrome (never mode-dependent, never overflows):**
```
[file name]  [File ▾: New Open | Save SaveAs]  ‖  [ Select Draw Template Centerline Sensor Measure ]  ‖  … spacer …  [snap] [undo] [redo?] [layers ▾] [fit] [zoom x.xx] [panel ▾]
```
- File menu collapses New/Open/Save/Save As (4 buttons → 1 `ui.button` +
  `ui.menu`), matching how the layers menu already works.
- The primary **tool toggle** is the only mode control here.
- Global, always-relevant controls stay: snap switch (it applies to every draw
  + edit gesture), undo, layers menu, fit, zoom label, zone-panel toggle. Save
  is common enough to keep a top-level icon in addition to the File menu.

**Row 2 — context bar (rebuilt/shown per active tool):** a single
`ui.row` container whose contents depend on `v.mode`. Contents per tool:

| Tool | Context bar contents |
|---|---|
| Select | sub-selection count · **Properties** (single) / **Bulk edit** (many) · **Rotate** · **Delete** · sensor selector (which sensor's zones are active) |
| Draw | **sub-type toggle** (Loop · Ignore · Lineal) · sensor selector (Loop/Ignore target) · dimensioned-draw hint |
| Template | template selector · centerline selector (read-only hint of which datum it follows) |
| Centerline | centerline selector · **Add centerline** |
| Sensor | sensor selector · **Add sensor** |
| Measure | **sub-type toggle** (Ruler · Calibrate · Marker) · **Clear markers & ruler** · calibrate-by-size button (under Calibrate) |

**Implementation mechanic (recommended):** build every tool's context group
once at page construction, wrap each in its own `ui.row`, and have
`change_tool` flip visibility with `group.set_visibility(mode == …)` — the same
pattern `zone_panel`/`toggle_zone_panel` already uses. This avoids per-switch
element rebuild churn and keeps element references stable for the event
handlers. (A `@ui.refreshable` context-bar function is the alternative; prefer
visibility toggling for lower risk and to preserve widget state like the
selectors' current values.)

Net effect: Row 1 is ~9 stable controls; Row 2 shows at most ~5 at a time.
Nothing scrolls.

---

## 4. Draw sub-modes — the element-kind abstraction

This is the load-bearing architectural change and it lives at the **pure-python
`DrawingController` seam** (Fable territory per [[CLAUDE.md]] — see §7), not in
NiceGUI. `DrawingController` today hardcodes `EventZone`, `self.zones` (one
list), `_commit_zone`, `insert_zone`, and `is_placeholder`. Generalize the
*commit target*, not the interaction machine.

### 4.1 Draw-target descriptor

Introduce a small value object the controller is pointed at — call it a
`DrawKind` (or `DrawTarget`). It bundles everything that differs between element
kinds while leaving the click/snap/dimension/undo machinery untouched:

```
DrawKind:
    shape:        "polygon" | "segment"      # 4-click/dimensioned vs 2-click
    zones:        the live list it mutates    # event_zones | ignore_zones | lineals
    make(points)  -> element                  # factory (domain.new_* / EventZone)
    insert(list, element) -> idx              # placeholder-slot-else-append helper
    points_of(element) -> list[Point]         # for hit-test / render / edit
    is_placeholder(element) -> bool
    style:        render hints (color, dash)  # for svg()
```

Concrete kinds for Phase 3:

| Kind | shape | list | make / insert | cap | render |
|---|---|---|---|---|---|
| **Loop** | polygon | active sensor `.event_zones` | `EventZone(...)` / `insert_zone` | 64 | existing phase-colored fill |
| **Ignore Zone** | polygon | active sensor `.ignore_zones` | `domain.new_ignore_zone` / `domain.insert_ignore_zone` | 10 | yellow dashed (already in `svg()`) |
| **Lineal** | segment | project lineal pool | `domain.new_lineal` / `domain.insert_lineal` | 100 | thin solid gray (new; must differ from centerline green) |

The undo stack already carries the list each op touched (`("replace", zones,
…)` etc.), so retargeting the controller between element lists works with the
existing cross-list undo — no undo-model change needed. `insert_*` raising
`ValueError` past the cap (10 / 100) must surface as a `ui.notify` warning.

### 4.2 `shape == "polygon"` vs `"segment"`

- **Polygon** kinds (Loop, Ignore Zone) reuse the *entire* existing path: free
  4-click, dimensioned rectangle, snapping, edit-mode move/copy/vertex-drag,
  nudge. Ignore zones get dimensioned drawing and snapping for free. Only
  `_commit_zone` changes — build via `DrawKind.make` and route through
  `DrawKind.insert` instead of the hardcoded `EventZone`/`insert_zone`.
- **Segment** kind (Lineal) is a **2-click** gesture (click start, click end),
  no dimension entry, no 3rd/4th corner. This is a new, small branch in
  `mouse_down` gated on `shape == "segment"`; commit after the 2nd click.
  Editing a lineal = drag either endpoint (reuse the vertex-drag path with a
  2-point "polygon").

### 4.3 Persistence gaps to close (model layer, Fable)

- **Ignore zones** already round-trip in `iprj_io` and already render in
  `svg()`; they just have no draw/edit/select path. Wiring is GUI-only once the
  `DrawKind` exists.
- **Generic lineals do NOT currently round-trip through the GUI.**
  `load_centerlines`/`save_centerlines` only handle *chains*; lone segments
  survive in `project.lineals` on save but are never surfaced to the Viewer for
  display or editing. Phase 3.2 needs a `Viewer.lineals` collection plus
  `load_lineals`/`save_lineals` in `model/` (analogous to `model/centerline.py`)
  that read/write the *non-chain* strays. **Hazard (from `model/domain.py`
  docstring):** a generic lineal that shares an endpoint with another lineal or
  a centerline vertex is re-read as part of a centerline chain on load. So the
  Lineal draw kind must **not** snap its endpoints to centerline vertices or
  other lineal endpoints (exclude those from its snap candidates), and
  `save_lineals` must not emit endpoint-coincident strays. This is a
  pure-python model addition — route to Fable, not folded into the Sonnet
  wiring.

---

## 5. Pan — drop it as a mode

**Decision (owner-confirmed): remove "Pan" from the tool set. Default tool is
Select. Panning becomes an implicit gesture available in every tool.**

- Pan gestures: **middle-button drag** (already global) and **space-bar +
  left-drag** (add — the reliable cross-device/trackpad gesture; middle-drag is
  awkward on laptops). Wire space via `ui.keyboard` setting a `v.space_pan`
  flag that `on_down`/`on_move` treat like the old Pan branch.
- In **Select**, an empty-canvas left-drag is the **marquee multi-select** (§6),
  *not* a pan — that is the one gesture the removed Pan mode occupied, and
  marquee is the more valuable use of it now that multi-select exists.
- Startup mode changes from `"Pan"` to `"Select"` (`Viewer.mode` default and
  `tool`'s `value=`). `change_tool`'s current `else: ctrl.set_mode("draw")`
  branch (which "clears any pending loop/dimension entry") maps Select →
  `ctrl.set_mode("edit")`.

**Fallback if hands-on testing finds empty-drag marquee-vs-pan ambiguous:** add
a *momentary* Hand affordance (a toggle button, not a mode) that flips
empty-canvas drag from marquee→pan. Do not reintroduce a full Pan mode. Decide
after trying the default.

---

## 6. Multi-select

The graceful-multi-select requirement. This is **pure-python controller state**
(Fable, §7) with a thin GUI sync layer (Sonnet).

### 6.1 State shape

Replace the single `selected: int` with a selection **set** plus an **anchor**:
- `selection: list[int]` (ordered; `[]` = nothing) — the selected zone indices
  in the active list.
- `anchor: int` — the primary/last-clicked member, for single-item operations
  (properties dialog) and as the rotate default-pivot seed.
- Keep a `selected` property returning `anchor` (or `-1`) so existing call
  sites and the render/status code that read `.selected` keep working during
  the migration; convert them incrementally.

Scope selection to **one element kind / one sensor's list at a time** for v1
(you select loops together, or ignore zones together — not a mixed set).
Switching the active sensor or draw kind clears the selection. Flag
cross-kind/heterogeneous multi-select as explicitly out of scope.

### 6.2 Interactions (Select tool)

- plain click on a zone → select just it (clear others), set anchor.
- **Ctrl/Shift-click** → toggle that zone in/out of the set, update anchor.
- **marquee** (empty-canvas left-drag) → select every zone whose polygon
  intersects the rubber-band rect (add a `geometry` helper — pure python,
  Fable). Shift-marquee adds to the current set.
- `Esc` → clear selection (extends the existing `cancel()` ladder).
- `n`/`b` cycle still selects a single zone (clears the set to one).

### 6.3 Group operations & undo

Reuse the **existing `("batch", [sub_ops])` undo entry** (added for template
`insert_many`) — this is the key reuse that keeps the undo model unchanged:
- **group move / nudge** → one `("points", zone, old_pts)` sub-op per selected
  zone, wrapped in a single `("batch", …)`; `undo()` already replays a batch in
  reverse. Drag-body moves the whole set by the same delta.
- **group delete** → one `("delete", …)` sub-op per zone in a batch (delete
  high-index-first so indices stay valid; restore in the recorded order).
- After any group move that touches attached zones, call the existing
  `reproject_attachments()` (already loops all centerlines) — no change needed.

### 6.4 Rotation (2-click pivot → `model.geometry`)

Phase 2 shipped `polygon_centroid`, `rotate_points(points, angle_deg,
pivot=None)`, and `rotation_angle_deg(pivot, from_pt, to_pt)` with a
convention-matched sign (positive degree = clockwise on screen in y-down). Wire
the **Rotate** action (Select context bar) as a two-click workflow:
1. Click 1 sets the **pivot** (default seed = centroid of the selection's
   combined points if the user just clicks "Rotate" without picking).
2. Move the mouse → live preview rotates the whole selection about the pivot by
   `rotation_angle_deg(pivot, first_ray_point, cursor)`.
3. Click 2 commits: apply `rotate_points` to every selected zone's points as
   one `("batch", [("points", …)…])` undo op.

**Attachment interaction (owner decision — rotation detaches):** rotating an
attached (station/offset rectangle) zone breaks its "exact rectangle on datum"
property, so a rotated zone drops out of the owning
`CenterlineController.attached` set. Rationale (owner): an attached zone is
*already* oriented correctly by the centerline — `restation` derives its points
from station/offset and its heading from the local segment tangent, so
detectors following a curve are rotated along the path for free. You therefore
rarely need to hand-rotate an attached zone; when you do, it's a deliberate
manual override, so detaching (mirroring how a hand-move off the s/o grid
already detaches on reload) is the correct, predictable behavior. Do **not**
reproject the rotated corners to keep a skewed attachment.

### 6.5 GUI sync (Sonnet)

- Zone table: `selection="single"` → `"multiple"`; `on_table_select` and
  `refresh_zone_table` sync the *set* both directions (currently they sync a
  single key).
- `svg()`: render every selected zone with the white-outline highlight (today
  only `zi == ctrl.selected`), and draw the marquee rectangle + rotation-pivot
  cross/preview while those interactions are live.
- Properties button: **exactly one selected → single-zone dialog** (unchanged);
  **many selected → Bulk edit** dialog applying a safe subset (enable, phase,
  type, and a "renumber outputs from N" action) to all. Bulk edit is a stretch;
  the floor is: disable single-zone Properties when >1 selected and rely on
  Delete/Move/Rotate for group work.

---

## 7. Module & model-routing breakdown

Per [[CLAUDE.md]], `model/` and the pure-python `gui/drawing.py` controller are
**Fable**; NiceGUI wiring in `gui/app.py` is **Sonnet**. This plan splits along
that seam. Recommended ordering: **the pure-python pass lands first** (it hands
Sonnet finished controller/model APIs), then the NiceGUI wiring.

| Work | File(s) | Target | Notes |
|---|---|---|---|
| `DrawKind`/draw-target descriptor; generalize `_commit_zone`; segment (2-click) draw path; retarget between element lists | `gui/drawing.py` | **Fable** | Undo model unchanged (ops already carry their list) |
| Multi-select state (`selection`/`anchor`), marquee hit helper, group move/delete/nudge as batches | `gui/drawing.py`, `model/geometry.py` | **Fable** | Reuse `("batch", …)` undo |
| `load_lineals`/`save_lineals` for non-chain strays; endpoint-coincidence guard | new `model/` code (mirror `model/centerline.py`) | **Fable** | Closes the generic-lineal round-trip gap (§4.3) |
| Rotation wiring is math-ready | `model/geometry.py` (done in Phase 2) | — | Just wire it |
| Two-tier toolbar (persistent row + per-tool context bar via visibility toggles); File menu; Measure/Draw sub-type toggles | `gui/app.py` `build_ui` | **Sonnet** | §3 |
| Drop Pan mode; Select default; space-drag pan; marquee vs pan resolution | `gui/app.py` `on_down/on_move/change_tool`, `Viewer.mode` | **Sonnet** | §5 |
| Wire Ignore Zone + Lineal draw kinds to the sub-type toggle; render generic lineals; cap warnings | `gui/app.py` `svg()`, mouse handlers | **Sonnet** | §4 |
| Multi-select GUI sync: table `"multiple"`, `svg()` highlights/marquee, bulk-edit dialog, rotate context action | `gui/app.py` | **Sonnet** | §6.5 |

**Suggested 3.2 sub-session sequencing** (each hands the next a concrete
artifact, the way Sessions 6–7 did):
1. **3.2a (Fable)** — `DrawKind` + multi-select controller state + marquee/group
   helpers + `load_lineals`/`save_lineals`, all pytest-covered, no GUI imports.
2. **3.2b (Sonnet)** — two-tier toolbar, drop Pan, wire the three draw kinds.
3. **3.2c (Sonnet)** — multi-select GUI sync + rotate workflow + bulk edit.

---

## 8. Decisions (resolved by owner, 2026-07-03)

1. **Pan** — **dropped** as a mode (§5). Default Select; pan via middle/space
   drag. Add a momentary Hand affordance only if empty-drag marquee tests
   poorly — never a full Pan mode.
2. **Bulk edit** — **follow-up, not v1.** Ship the floor: single-selection
   Properties + group Delete/Move/Rotate. A multi-zone attribute editor
   (phase/type/enable + output renumber) is a later add.
3. **Rotation detaches attached zones** — **confirmed** (§6.4). Attached zones
   are already oriented by the centerline (they rotate along the path via
   `restation`), so hand-rotating one is a deliberate override and it detaches.
4. **Accelerators** — **`d` Draw** (top level); within Draw, **`z` Loop · `l`
   Lineal · `i` Ignore**; `v`/`e` Select, `t` Template, `c` Centerline, `s`
   Sensor, `r` Measure. See §2.1 for the two conflicts this resolves (`d` no
   longer starts dimension entry — digits do; `l` no longer enters Draw).
