# Item 23 — Toolbar / layout decision doc (for Items 24 & 27)

Opus planning output per [[ROADMAP.md]] Item 23. This is a **planning session,
not an implementation one**: it synthesizes every toolbar-affecting request
gathered in the 2026-07-07 owner batch into one target layout, backs it with
**runnable static mockups** ([[gui/toolbar_mockup.py]]), and nails down the
exact control set + placement that **Item 24** (Sensor/Centerline fold + unified
dropdown + chrome) and **Item 27** (Template fold + CL dropdown) build. Nothing
here is wired to real commands.

Read the current toolbar in [[gui/app.py]] (`build_ui`'s two `ui.row`s at
~2576/2634, `update_context_bar` ~2512, `change_tool`/`change_draw_kind`,
`TOOL_KEYS`/`DRAW_SUBTYPE_KEYS` ~2364) alongside this doc; the line references
below point at what moves.

---

## 0. Try the mockups first

```
source .venv/bin/activate       # repo root
python EVO/iprj_designer/gui/toolbar_mockup.py     # → http://localhost:8081
```

Three tabs — **A · Two-tier**, **B · Single bar**, **C · Left rail**. Flip the
**Tool** toggle (cyan) and, under Draw, the **sub-kind** toggle (amber) to watch
the context bar reflow; the **owner/sensor** dropdown (green) shows its resolved
file band (`→ _1_2` / `→ _3_4` / `→ both files`). Buttons are inert. Port 8081 so
it never collides with the real app on 8080.

---

## 1. The synthesis — every toolbar-affecting request in one place

The owner batch (ROADMAP 23–27) and carried-over calls collapse to seven moves:

1. **Draw becomes the hub.** Top-level tool toggle shrinks from six
   (`Edit · Draw · Template · Centerline · Sensor · Background`, ~2592) to
   **three: Draw · Edit · Background**. Sensor, Centerline (Item 24) and Template
   (Item 27) stop being top-level tools and fold into Draw **sub-kinds**.
2. **Draw before Edit.** New tool order is `Draw · Edit · Background`; `d`/`e`
   accelerators keep their meaning.
3. **One Owner/Sensor dropdown.** The active-sensor `sensor_sel` (~2635) and the
   `General / Active sensor` `assign_toggle` (~2660) collapse into a single
   dropdown: options **General + S1…Sn**. General is **suppressed for Event Zone
   / Ignore Zone** (a zone must belong to a sensor).
4. **Product name dropped, filename kept.** `"iprj Designer — …"` (~2579) loses
   the product prefix; the filename stays visible and the folder/load menu stays
   next to it (see §4 — the earlier "move filename to row 2" call is retired).
5. **Zone table becomes three-state.** The binary show/hide `view_sidebar`
   toggle (`toggle_zone_panel`, ~2163) becomes **Auto / On / Off** (§5).
6. **Template folds into Event Zone** (Item 27): the `template_sel` picker plus a
   single **CL dropdown** (collapsing `template_follow_switch` "along CL" +
   `template_cl_sel` "pick CL") live in the Event-Zone context; the CL dropdown
   applies to **every** drawn event zone, not just templates.
7. **Height budget.** Keep both toolbar rows fitting inside
   `calc(100vh - 120px)` (§6).

---

## 2. The three options (and why A wins)

The mockups are genuinely distinct so the owner can pick a *shape*, not just
nod at one. All three carry the **same control set** (§3) — they differ only in
arrangement, filename placement, and vertical cost.

| | **A · Two-tier** *(recommended)* | **B · Single bar** | **C · Left rail** |
|---|---|---|---|
| Rows | 2 (tools + context) | 1 | 1 context + vertical rail |
| Sub-kind picker | **segmented toggle** (glanceable) | dropdown (compact) | segmented toggle |
| Filename | inline on row 1, muted | inside folder menu header | inline on context row |
| Canvas height gain vs today | none (2 rows kept) | **+~30 px** (1 row) | +~30 px, widest canvas |
| Overflow risk on Event Zone | **low** (extras get their own row) | **high** (tools+kind+owner+template+CL+globals on one line) | medium |
| Code delta from today | **smallest** — same 2-row + `update_context_bar` visibility pattern already shipped in Phase 3 | medium | **largest** — new rail container, `change_tool` restructure |
| Departs from calibrate.py feel | no | no | yes |

**Recommendation: implement Option A.** Rationale:

- **Matches the ROADMAP's own framing.** Item 23/24 both say "retune
  `calc(100vh - 120px)` so *both bars* fit" — the plan already assumes two
  toolbar rows survive. A banks the consolidation wins (fewer top-level tools,
  one owner dropdown, no product name) without betting the busiest context bar
  (Event Zone: owner + template + CL + values) on a single line.
- **Lowest risk.** A reuses the exact Phase-3 mechanic already in the code:
  build every context control once, flip `set_visibility` per tool/sub-kind in
  `update_context_bar`. B/C both need structural surgery in `build_ui` for
  marginal vertical gain.
- **Segmented sub-kind toggle keeps the six kinds glanceable** — you can see at
  a glance you're in "Event Zone" vs "Centerline"; B's dropdown hides it behind
  a click.

**When to revisit:** if hands-on use finds the canvas too short, promote to
**Option B** — it's a pure re-parent of A's controls onto one row (sub-kind →
dropdown, filename → folder menu) and buys ~30 px. **Option C (left rail)** is
explicitly **deferred**: it's the biggest departure and reopens the
calibrate.py-modeled interaction feel for little more than B's gain.

Everything below specifies **Option A**. Because A/B/C share the control set,
adopting B/C later changes only arrangement, not the semantics Items 24/27 wire.

---

## 3. The decided layout — control set & placement (what Item 24 builds)

### 3.1 Row 1 — grouped by type, with `|` separators (owner's call)

Commands are grouped by *type*, each group fenced by a vertical `|` separator —
modes and permanent tools left-justified, the file cluster right-justified:

```
‹ Draw  Edit  Background ›  │  [snap][ruler][clear-ruler][undo][layers][fit]   ⟵space⟶   │  [template-editor] [📁▾] banks_1_2.iprj + banks_3_4.iprj [save]
```

- **Tool toggle** (top-left) `ui.toggle(["Draw", "Edit", "Background"],
  value="Draw")` — **Draw first**. Replaces the six-entry toggle. Keys: `d`
  Draw, `e` Edit; Background stays click-only (no key today, unchanged).
- **Permanent drawing tools** (left, immediately after the toggle behind a `|`):
  snap switch, ruler + **clear-ruler** (the clear button rides with the ruler),
  undo, layers menu, fit. These apply in every mode, so they stay left-justified
  and always visible.
- **File cluster** (right-justified, after `ui.space()` + a `|`), in order:
  the **template-editor button** (moved here from the Event-Zone bar — see §7),
  the **folder menu** (New / Open / Open second pair / Save / Save As), the
  **filename**, and **save**. The **folder icon sits next to the filename**, and
  the **filename immediately left of Save** (owner's calls); the filename is an
  inline `ui.label`, muted (`text-gray-300`), product prefix **removed** (§4).
- The zone-table three-state control is **not** on Row 1 — it moves to Row 2
  (§5), right-justified above the table.

### 3.2 Row 2 — context bar, gated by tool + sub-kind

`update_context_bar` (~2512) keeps its build-once / toggle-visibility model. New
gating:

**Tool = Draw** → show the **sub-kind toggle** + **owner dropdown** + that
sub-kind's extras:

```
‹ Event Zone  Ignore Zone  Lineal  Text Label  Centerline  Sensor ›  │  [Owner/Sensor ▾ → band]  {extras}   ⟵space⟶   │  [zone-table ▾]
```

The **zone-table three-state** button (§5) is right-justified at the end of this
row, directly above the table it governs (owner's call).

| Sub-kind | Owner/Sensor options | Extras in the context bar |
|---|---|---|
| **Event Zone** | S1…Sn (**no General**) | `template_sel` · **CL dropdown** · placement-values btn (if template) *(template-editor btn is NOT here — it lives in the Row-1 file cluster, §7)* |
| **Ignore Zone** | S1…Sn (**no General**) | — |
| **Lineal** | **General** + S1…Sn | — |
| **Text Label** | **General** + S1…Sn | label-draft fields (text/size/rot°/color/B/I/U) — unchanged from ~2674 |
| **Centerline** | **General** + S1…Sn | `centerline_sel` · add-centerline · name input |
| **Sensor** | S1…Sn (**no General**; picks the active sensor) | add-sensor · delete-sensor |

**Tool = Edit** → `select_count · [properties][rotate][move-along-CL][delete]`
plus the **Owner/Sensor dropdown** (scopes which sensor's zones Edit acts on).
The sub-kind toggle is **hidden in Edit** (unchanged from today — Edit operates
on the last-targeted kind); revisit only if the owner wants to switch the edited
kind without bouncing through Draw.

**Tool = Background** → `[calibrate-by-size][upload-background]` (unchanged, just
regated from the retired Background tool slot — it already exists at ~2717).

### 3.3 The unified Owner/Sensor dropdown — semantics (the load-bearing piece)

One `ui.select` replaces **both** `sensor_sel` and `assign_toggle`. It carries
two pieces of state that today live in two controls:

- **`active_si`** — the active sensor (drives zone drawing/editing target and
  sensor management), and
- **`assign_general` + band** — the owner of a newly drawn owned annotation
  (`v.current_owner()` → `Owner.GENERAL` / `FILE1` / `FILE2`, ~2461).

Resolution — keep them as **two internal fields**, project them through **one
widget**:

- **Displayed value** = `"General"` when the current sub-kind offers General
  *and* `assign_general` is set; otherwise `f"S{active_si+1}"`.
- **On select "Sk"** → `assign_general = False`; `active_si = k`; owner = that
  sensor's band (`S1/2 → _1_2`, `S3/4 → _3_4`).
- **On select "General"** → `assign_general = True`; **leave `active_si`
  unchanged** (so switching back to a zone sub-kind still has a valid sensor).
- **On sub-kind change** to a zone kind (General not offered): if
  `assign_general` was set, the widget snaps to `S{active_si+1}` — General is
  simply absent from the options.

This preserves `current_owner()` and the existing band routing (Item 22)
untouched; only the *input surface* changes.

---

## 4. Filename / header — resolved

**Decision: keep the filename inline on Row 1 in the right-justified file
cluster, immediately left of the Save button (owner's call); drop the
`"iprj Designer — "` product prefix; full path in the folder tooltip.** The
earlier "move filename to row 2" call (from before the bar freed up) is
**retired** — Row 1 now has room because the tool toggle shrank 6→3 and the
product name is gone, and grouping the filename with the folder/save/template-
editor file commands keeps all document-level controls together (§3.1).

Why inline-and-visible (not tucked in the folder menu as in Option B): you must
always know *which* project (and, in overlay mode, *which pair*) you're editing;
a persistently visible filename is cheap now. `title_label`'s two set points
(~1667 single-file, ~1676 overlay-pair) keep working — just drop the
`"iprj Designer — "` literal from both.

---

## 5. Zone-table three-state (Auto / On / Off)

Replace the binary `toggle_zone_panel` (~2163) with a three-state control on the
`view_sidebar` button (a small menu: Auto / On / Off, default **Auto**).

**Placement (owner's call): right-justified at the end of Row 2 (the context
bar), directly above the zone table it governs** — not in the Row-1 tool cluster.
Its state is mode-independent, so the context bar shows it after an `ui.space()`
in every tool (see §3.2). This keeps the control adjacent to the panel it toggles.

- **Auto (default):** the zone panel is visible **only when a zone kind is the
  active target** — i.e. `Tool = Draw` with sub-kind ∈ {Event Zone, Ignore Zone},
  or `Tool = Edit` on a zone kind. Recomputed on every tool / sub-kind change
  (fold the recompute into `update_context_bar`).
- **On:** always visible. **Off:** always hidden.
- Store the mode on the Viewer (e.g. `v.zone_panel_mode`); `update_context_bar`
  calls `zone_panel.set_visibility(...)` from `mode == "On" or (mode == "Auto"
  and _zone_kind_active())`.

---

## 6. Height budget

Two toolbar rows (~2 × 36 px) + status bar (~28 px) + row padding ≈ **108–116 px**.
Keep `calc(100vh - 120px)` as the starting value for both the viewport div
(~2783) and the zone panel (~2799); **verify empirically** after the rows are
rebuilt (open at a typical window height, confirm neither toolbar row wraps and
the canvas shows no vertical scrollbar). Tighten toward `- 112px` only if there's
visible slack. If the owner later adopts **Option B**, drop to one toolbar row
and retune to `calc(100vh - 90px)` for the ~30 px canvas gain.

---

## 7. What Item 27 adds on top (Template fold + CL dropdown)

Item 27 runs **after** 24 (needs the consolidated Draw bar) **and 26** (needs
explicit centerline membership). Against the layout above:

- **No new tool/sub-kind.** Template placement is a **mode of Event Zone**, not
  its own sub-kind: a template chosen in `template_sel` ⇒ drop-template mode;
  blank ⇒ plain event-zone draw. Remove Template from the tool toggle +
  `TOOL_KEYS` (already gone as of Item 24's toggle) and delete its standalone
  context group (~2527–2532 gating).
- **CL dropdown = one control.** Collapse `template_follow_switch` ("along CL")
  + `template_cl_sel` ("pick CL") into a **single CL `ui.select`** in the
  Event-Zone context bar: a CL chosen ⇒ place *along* it; blank ⇒ today's
  toggled-off behavior (aim upstream with a second click). Retire
  `template_follow_switch`.
- **CL dropdown binds to every event zone**, template or not — the drawn zone
  joins that centerline's group via **Item 26's explicit membership** (the reason
  27 depends on 26). No template selected ⇒ plain zone that still takes the
  chosen CL's membership.
- **Template-editor button home — decided (owner's call): the Row-1 file
  cluster**, alongside the folder menu / filename / save (icon `edit_square`,
  between the folder button and the filename). Rationale: editing a template
  file is a document-level action, not part of drawing a zone, so it belongs
  with the other file commands and stays **persistently visible** in every mode
  rather than only under Event Zone. It is therefore **removed from the
  Event-Zone context bar** (which keeps only `template_sel` + CL dropdown +
  placement-values). This is a small deviation from Item 27's suggested-prompt
  wording ("place the template-editor button per the Item 23 plan") — the plan
  now puts it in the file cluster; Item 27 wires it there.
- **Re-verify the height budget** (§6) after this bar gains the CL dropdown.

---

## 8. Interaction risks for the follow-ups

- **`active_si` has many readers.** Folding `sensor_sel` into the unified
  dropdown means every current reader/writer of `active_si` (zone insert
  routing, `change_active_sensor` ~1362 that repopulates the selector, the
  `draw_kind_toggle.set_value` + `sensor_sel.set_value` pairs at ~2042/2067/2204,
  sensor add/delete) must route through the new widget's setter, **not** a
  now-deleted `sensor_sel`. Grep `sensor_sel` and `assign_toggle` and convert
  each site; keep `active_si`/`assign_general` as the source of truth and treat
  the dropdown as pure projection (§3.3) so these readers don't each need
  General-awareness.
- **General ↔ zone-kind transitions.** When the user is on General (Lineal, say)
  and switches to Event Zone, the widget must resolve to a real sensor. Because
  `active_si` is retained independently, snapping to `S{active_si+1}` is safe —
  but test it (General on Lineal → switch to Event Zone → draw → confirm the
  zone lands in `active_si`'s file, not a stale one).
- **`change_draw_kind` retargets + clears selection** (~2454, `cancel_rotate` +
  `set_draw_kind`). The owner-controls-visible recompute (~2465) must now key off
  the widened `OWNED_KINDS` vs zone-kinds distinction for General suppression,
  not the old `assign_toggle` visibility rule.
- **Zone-panel Auto recompute** must fire on both tool *and* sub-kind change, or
  the panel won't appear/disappear when you flip Event Zone ↔ Centerline within
  Draw.
- **Template paths under Draw (Item 27).** The Template-mode `on_down`/`on_move`/
  Escape branches (~2235/2299/2406) currently gate on `v.mode == "Template"`;
  under the fold they must gate on `Tool = Draw ∧ sub-kind = Event Zone ∧
  template selected`. Verify Escape still cancels a pending template drop.

---

## 9. Net effect on the Item 24 / 27 scopes

The ROADMAP flagged 23 "may re-cut the boundaries of 24/27." It doesn't — the
provisional split holds. Refinements to fold into their checkboxes:

- **Item 24** implements **Option A** exactly as §3–§6: tool toggle → 3 entries
  (Draw first); Sensor + Centerline as sub-kinds with their controls migrated
  into the Draw context bar; the **unified Owner/Sensor dropdown per §3.3**
  (retain `active_si` + `assign_general`, one projecting widget); Row-1 grouped
  by type with `|` separators — modes + drawing tools left, **file cluster
  (template-editor · folder · filename · save) right, folder beside the filename
  and filename beside Save**,
  product name dropped (§3.1/§4); **zone-table Auto/On/Off right-justified on
  Row 2** (§5); height budget kept at `- 120px`, verified (§6).
- **Item 27** implements §7: Template folds into Event Zone (no sub-kind),
  `template_follow_switch` + `template_cl_sel` → one CL dropdown bound to every
  event zone via Item 26 membership, **template-editor button wired in the Row-1
  file cluster** (not the Event-Zone bar).
- **Owner/sensor is the only ambiguous seam**; §3.3 + §8 resolve it. No model
  (`model/`) shape changes are required by the layout itself — band routing and
  `current_owner()` are unchanged; Item 24's only model-side test surface is any
  helper that reads the new panel-mode / dropdown projection.
