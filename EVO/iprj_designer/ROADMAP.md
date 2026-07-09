# Roadmap — iprj Designer

Six rounds of work are complete and archived in [[DESIGN_HISTORY.md]], not
listed here anymore: the Phase 1 MVP (Sessions 1–7 — data model, drawing
core, attributes, templates, centerline placement), a second "Phase 1–4"
round (quick wins/file management, domain accuracy, the toolbar/multi-select
overhaul, and the advanced template engine), a third numbered-items round
(Items 1–9 and 11 — background-tool rework, per-zone-type conditions,
sensor management, edit-mode/vertex tools, terminology renames, free-draw
polygons, centerline re-stationing, canonical origin, and the multi-sensor
2-file split), a fourth "owner batch" round (Items 12–20 — quick UI
fixes, the template-editor taxonomy rename + even spacing + side-by-side
adjacency table, centerline placement snap/naming, and the large-file
zoom-freeze fix), a fifth "annotation-ownership" round (Items 21–22 —
sensor-scoped lineals/centerlines/labels via vendor index bands, plus the
text-label GUI entity + centerline-name labels), and a sixth "Draw-hub
consolidation" round (Items 23–27, 2026-07-07 — toolbar planning + mockups,
the Draw-hub toolbar consolidation with a unified owner/sensor dropdown, the
oversized off-image canvas, bulk-edit + explicit persisted centerline
membership, and folding Template into Draw › Event Zone under one CL dropdown;
plus post-batch UI fixes on 2026-07-08 — a full-height flex layout so the page
fits the window, a wider zone table, and the ruler exiting on tool selection).
Reusing "Phase 1" for two unrelated rounds is exactly the confusion this file
is now organized to avoid — see the note below.

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
  rule. (Older completed items — now archived — used a "Fable then
  Sonnet" hand-off that this routing has retired.)
- Tell the agent "do Item N of ROADMAP.md" (or reference it by name) to run
  a scope below; check off items and log decisions in [[DESIGN_HISTORY.md]]
  as they land, the same way every round so far has.

"Future" items at the bottom aren't scoped yet (no Target/Scope/prompt) —
they need a planning pass before they're actionable.

> **Temporary routing note (2026-07-08):** Items 28–31 below use the owner's
> stated per-model division — **Fable for the hardest item, Sonnet for the
> routine one, Opus for the architecture session** — which *inverts*
> [[CLAUDE.md]]'s current Opus-default rule (Fable-as-debugging-escalation).
> This is a deliberate, **time-boxed** override for the next few days while
> the owner has Pro Fable access; once that access lapses or its limits are
> hit, revert to CLAUDE.md's documented rule for any not-yet-started item.
> See CLAUDE.md's routing section for the standing convention.

---

## 28 — Record/Playback: Architecture & Coordinate Reconciliation (Target: Opus) — DONE 2026-07-08 → RECORD_PLAYBACK_PLAN.md

Prerequisite planning session for Items 29–31 — a **decision document, no
code**. Bringing the EVO record/replay capability (`../evo_recorder*.py`,
`../evo_replay.py`) *into* the designer is mostly a plumbing + dependency
question, **not** a genuine coordinate-space conflict: `evo_replay` reads the
**same** `*_iprj.txt` the whole designer is built around, so there is one
source of truth for scale/anchor. The apparent "meters (evo_replay) vs. feet
(designer)" gap is therefore most likely a **units-conversion** detail — and
possibly a latent bug if `model/units.py` was never set up correctly against
these files (owner's flag, 2026-07-08) — rather than two irreconcilable
frames. What still needs deciding is where each piece lands given the
`model/`-is-pure-Python rule and the pandas dependency. Opus owns this
because every downstream item inherits these choices.

Scope — decide and write up (with rationale) each of:
- [x] **Coordinate / units reconciliation.** `evo_replay` aligns EVO tracks
      to map *meters* via a sensor-0 translation it regex-parses from
      `*_iprj.txt`; the designer parses the same sensor positions +
      `MeterPerPixel` but works in **feet/world space**. Because both read the
      one same file, first **audit `model/units.py`'s conversion against a
      real site** — confirm feet↔pixel↔meter round-trips and that the sensor
      anchor lands correctly; if it doesn't, that's a units bug to fix here,
      not a reconciliation to design around. Then define the single transform
      EVO frame → designer world-feet (reusing the loaded `Project`'s sensor
      anchor + `model/units.py`, not a second regex parse) so playback markers
      land in the same space the SVG overlay already uses. Decide whether the
      alignment anchor stays sensor-0 or goes per-sensor for the 2-file /
      multi-sensor split.
- [x] **Module placement.** A new pure `model/replay.py` (parse + align,
      headless-testable) vs. the recording adapter — which is inherently
      side-effectful (websocket, asyncio, live credentials) and so can't sit
      in pure `model/`. Decide the seam (e.g. pure parser in `model/`, a
      recording controller in `gui/` or a new `io/`), keeping `model/` GUI-
      and global-state-free.
- [x] **Data-structure seam.** `evo_replay.load_replay()` returns a pandas
      DataFrame; the designer's `model/` has **no pandas dependency**.
      Decide DataFrame vs. a plain frame-indexed structure (dict/list) —
      this sets the dependency surface and how the engine gets unit-tested.
- [x] **Playback ↔ draw/edit interaction.** Whether playback is a new
      read-only "Replay" tool/mode, how animated markers overlay the
      existing SVG without disturbing draw state, and whether editing is
      allowed during playback.
- [x] **Recording model.** Host/credentials entry, where recordings are
      written (the `sites/` convention?), credential handling/safety, and
      the live-connection lifecycle inside NiceGUI's event loop; how a
      multi-host recording (`evo_recorder_multi.py`) maps onto the
      multi-sensor project model.
- [x] **Performance guardrails.** Downsample / frame-cap / animation cadence
      strategy, carrying forward the large-file zoom-freeze lessons (archived
      Item 20).
- [x] Output the plan as a short design doc under `EVO/iprj_designer/` (e.g.
      `RECORD_PLAYBACK_PLAN.md`) and log the decisions in [[DESIGN_HISTORY.md]].

Suggested prompt:
> [Opus] In EVO/iprj_designer, do Item 28 of ROADMAP.md: produce the
> architecture/decision document for bringing EVO record + playback into the
> designer. Decide coordinate reconciliation (EVO frame → world-feet reusing
> the loaded Project anchor), module placement that keeps `model/` pure, the
> pandas-vs-plain data seam, how playback coexists with draw/edit, the
> recording/credential/file model, and performance guardrails. Land the doc
> and DESIGN_HISTORY entry — no feature code this session.

---

## 29 — Playback Engine in `model/` (Target: Fable — hardest item) — DONE 2026-07-08 — needs Item 28

The correctness-critical core: port `../evo_replay.py`'s parse + align into a
**pure, headless-testable** `model/replay.py`, but retargeted from
`evo_replay`'s map-meter space into the designer's **world-feet** coordinate
space per Item 28's transform. This is the batch's hardest, most bug-prone
piece — coordinate/sign math across meters↔pixels↔feet and y-down world
space, plus alignment against the *loaded project's* sensor anchor rather
than a re-parse — hence Fable.

Scope:
- [x] `model/replay.py`: parse an EVO recording (`F;`/`C;`/timestamp lines,
      per `evo_replay.parse_evo_data`) into a frame-indexed structure in the
      shape Item 28 chose (no pandas unless 28 approved it).
- [x] Align every track point into designer world-feet using the loaded
      `Project` sensor anchor + `model/units.py` — verify markers coincide
      with the corresponding sensor geometry on a real site.
- [x] Downsample / frame-cap per Item 28's guardrails.
- [x] pytest coverage against a real recording fixture under `sites/**`
      (read-only; generated output to `tests/out/` or scratchpad), including
      a coordinate-alignment assertion (a known point lands where expected).
      *(Caveat: no real EVO recording survives anywhere on disk or in git —
      evo_replay's `DEFAULT_DATA` file is gone — so the tests run a
      format-faithful synthetic recording against the real `86_US95&SH8`
      site fixture, plus an equivalence test against legacy
      `evo_replay.align()`. First real capture loaded in Item 30 confirms
      the plan-§7 y-sign/no-rotation open items on live data.)*
- [x] DESIGN_HISTORY entry; check off this item.

Suggested prompt:
> [Fable] In EVO/iprj_designer, do Item 29 of ROADMAP.md following Item 28's
> design doc: build the pure `model/replay.py` playback engine — parse an EVO
> recording and align tracks into the designer's world-feet space using the
> loaded Project's sensor anchor and model/units.py. Keep it GUI-free and
> pytest it against a real site recording, asserting a known point aligns.

---

## 30 — Playback UI: Timeline + Animated Overlay (Target: Opus) — DONE 2026-07-08 — needs Item 29

Wire the Item 29 engine into the NiceGUI shell: a read-only "Replay" mode
(per Item 28) that loads a recording, overlays animated track markers on the
existing `interactive_image` SVG, and drives them with a `ui.timer`. New GUI
seam and mode interaction → Opus.

Scope:
- [x] Recording file picker + load into a playback session (the Item 29
      engine); reuse the existing viewport transform so markers register
      against the background. *(Load dialog picks the file + the anchoring
      sensor + a downsample knob; markers convert world-feet → world-px →
      canvas through the same `replay_point_to_canvas` → `world_to_canvas`
      path all overlay objects use — verified headless that a point on the
      `C;` reference lands exactly on the sensor anchor's canvas position.)*
- [x] Transport controls: play / pause, speed (0.5/1/2/4×), frame step, and a
      timeline scrubber bound to the frame index (all routed through one
      `set_replay_frame` seam so scrubber/markers/status stay in lockstep).
- [x] Animated SVG marker layer (id/sensor labels à la `evo_replay`'s
      styling) refreshed via `ui.timer`, coexisting with — not corrupting —
      draw/edit overlay state (a *separate* `interactive_image` layer stacked
      above the static overlay with `pointer-events:none`; only its content is
      rewritten per tick, plan §4).
- [x] Respect Item 28's guardrails so large recordings don't reproduce the
      zoom-freeze regression (fixed 10 fps cadence, marker-layer-only rewrite,
      timer inactive off-Replay; the engine's downsample/frame-cap at load).
- [x] DESIGN_HISTORY entry; check off this item. (Model-side render helpers —
      `marker_color`/`short_id` — got pytest coverage; pure GUI wiring
      exercised by hand + a headless coordinate/alignment check.)

Suggested prompt:
> [Opus] In EVO/iprj_designer, do Item 30 of ROADMAP.md: add the Playback UI
> on top of the Item 29 engine — a read-only Replay mode with a load-
> recording picker, play/pause/speed/step + timeline scrubber, and an
> animated SVG marker overlay driven by ui.timer that coexists with the
> draw/edit overlay. Land the DESIGN_HISTORY entry.

---

## 31 — Live Recording Integration (Target: Sonnet — routine) — DONE 2026-07-08 — needs Item 28

The routine item: fold the existing recorder logic
(`../evo_recorder.py` / `../evo_recorder_multi.py` — websocket auth + raw
stream capture) into the app as a "Record" panel. The capture logic already
exists; this is mostly a form + start/stop wiring + file placement per Item
28's recording model. Low-ambiguity, so Sonnet — but keep the async/websocket
lifecycle and credential handling exactly as Item 28 specified.

Scope:
- [x] "Record" panel: host + credentials form, start/stop, live status
      (frames captured), and save-location per Item 28's file convention.
- [x] Drive the existing recorder capture from within the app's event loop
      (single-host at minimum; multi-host if Item 28 scoped it in).
- [x] Hand a finished recording straight to the Item 30 playback loader.
- [x] DESIGN_HISTORY entry; check off this item.

Suggested prompt:
> [Sonnet] In EVO/iprj_designer, do Item 31 of ROADMAP.md: add a "Record"
> panel that wraps the existing evo_recorder(_multi) websocket capture — a
> host/credentials form, start/stop, live frame-count status, and save
> location per Item 28's recording model — and hands the finished file to the
> Item 30 playback loader. Follow Item 28 for the credential/lifecycle
> details. Land the DESIGN_HISTORY entry.

---

## 10 — Webserver Deployment (Target: Opus)

Carried over unchanged from the earlier "Phase 5" round (not started, not
dropped). Big enough that its planning half may still warrant its own
session before the implementation, but both halves are Opus now — no
cross-model hand-off.

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

- Display objects from a **live** stream in the canvas (real-time, not a
  recorded file — a follow-on to the record/playback work in Items 28–31).
- Integrate the line-up/calibrate workflow (see
  `~/pyatspm/src/atspm/video/calibrate.py`) more directly into the app.
