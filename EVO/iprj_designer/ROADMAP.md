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

> **Temporary routing note (2026-07-08, extended 2026-07-09):** Items 28–35
> (the record/playback batch 28–31 and the live-overlay batch 32–35, all done)
> **and the new Items 37–43** (the calibration + interactive-alignment batch
> 37–40 and the track-stitching/fusion batch 41–43, added 2026-07-09 at the
> owner's request) use the owner's stated per-model division — **Fable for the
> hardest item, Sonnet for the routine one, Opus for the architecture
> session** — which *inverts*
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

## 32 — Live Overlay: Architecture & Feed-Tap Seam (Target: Opus) — DONE 2026-07-08 → LIVE_OVERLAY_PLAN.md — needs the Item 28 plan

Prerequisite planning session for Items 33–35 — a **decision document, no
code**, extending [[RECORD_PLAYBACK_PLAN.md]]. The record/playback batch
(28–31) already did the hard parts the live overlay reuses: the coordinate
reconciliation (EVO-meters → world-feet, plan §1b), the animated marker layer
(Item 30), and the websocket capture controller (`capture/recorder.py`, Item
31). What's genuinely new — and must be decided before any code — is the
**real-time seam**: how a frame gets from the live socket onto the canvas *as
it arrives*, not from a file after the fact. Opus owns this because Items
33–35 inherit these choices.

Scope — decide and write up (with rationale) each of:
- [x] **Feed-tap seam.** `capture/recorder.RecordingSession._run` currently
      only writes each websocket message to disk. Decide how a live consumer
      subscribes to that *same* message stream without disturbing capture — a
      subscriber/callback list, an `asyncio.Queue`, or a shared "latest
      message" slot — and whether the overlay requires recording-to-disk or
      can overlay a feed without saving. `capture/` stays the one place the
      socket lives. *(→ synchronous subscriber-callback list; `save: bool`
      lets overlay skip disk; raw-message slot rejected as lossy, queue as
      unbounded — plan §1.)*
- [x] **Incremental parse placement.** `model/replay.py` parses a *whole file*
      (`parse_evo_data`). Live needs a **stateful, one-message-at-a-time**
      parser that holds the `C;` reference + current timestamp across calls and
      emits aligned `Frame`s via the plan-§1b transform. Decide whether this
      extends `model/replay.py` (a streaming class beside the batch parser) or a
      new pure module — reusing the existing transform, not a second copy, and
      keeping `model/` pure. *(→ `LiveAligner` inside `model/replay.py` on
      shared `_parse_ref`/`_parse_frame_entities` helpers; caller supplies the
      timestamp — plan §2.)*
- [x] **Async → GUI push + backpressure.** NiceGUI runs on asyncio and the
      capture task can produce frames faster than the canvas should redraw.
      Decide the refresh strategy — the safest is a shared "latest aligned
      frame" slot the capture side writes and a fixed-cadence `ui.timer` reads
      (drop-to-latest), decoupling socket rate from redraw and reusing Item
      30's marker-layer-only rewrite — vs. pushing each frame directly. Pin
      down drop-to-latest / stale-marker expiry so a fast or bursty stream
      can't flood the UI or leave dead markers on screen. *(→ single latest-
      frame slot + 10 fps timer; whole-stream stall cleared via
      `STALE_TIMEOUT` — plan §3.)*
- [x] **Live-vs-Record UX.** Whether "Live" is a distinct mode, a superset of
      Record (overlay *while* recording), or a toggle inside Replay; how it
      coexists with draw/edit (read-only, per plan §4); and the connection
      lifecycle relative to the existing Record panel (share the auth/host
      form). *(→ new read-only "Live" canvas mode sibling to Replay, sharing
      the Record auth form + `RecordingSession`; superset via `save=True` —
      plan §4.)*
- [x] **Live guardrails.** Marker-per-frame cap, stale-marker timeout (a track
      that stops reporting should fade/clear), reconnect/error surfacing, and
      the Item 20 zoom-freeze lesson carried onto the live path. *(plan §5;
      auto-reconnect an explicit non-goal for the first cut.)*
- [x] Output as a new section of [[RECORD_PLAYBACK_PLAN.md]] (or a sibling
      `LIVE_OVERLAY_PLAN.md`) and log the decisions in [[DESIGN_HISTORY.md]].
      *(→ sibling [[LIVE_OVERLAY_PLAN.md]] + DESIGN_HISTORY entry.)*

Suggested prompt:
> [Opus] In EVO/iprj_designer, do Item 32 of ROADMAP.md: produce the
> architecture/decision document for the live overlay, extending
> RECORD_PLAYBACK_PLAN.md. Decide the feed-tap seam on RecordingSession, where
> the incremental (one-message-at-a-time) aligner lives while keeping `model/`
> pure, the async→GUI push + drop-to-latest backpressure, the live-vs-Record
> UX, and live guardrails. Land the doc and DESIGN_HISTORY entry — no feature
> code this session.

---

## 33 — Streaming Align Engine in `model/` (Target: Fable — hardest) — DONE 2026-07-08 — needs Item 32

The correctness-critical core: a **pure, headless** streaming parser that
ingests EVO messages one at a time (as they arrive live), maintains the `C;`
reference + timestamp as state, and emits `Frame`s aligned into world-feet via
the plan-§1b transform — the incremental counterpart to Item 29's whole-file
`parse_evo_data`. This is the batch's hardest, most bug-prone piece: stateful
parsing of a partial stream plus the coordinate/sign math the plan's §7 open
items flagged (y-down, no-rotation) — which would first bite on *live* data —
hence Fable.

Scope:
- [x] A streaming class in `model/replay.py` (e.g. `LiveAligner`) built from a
      loaded `Project` + sensor index, exposing `feed(message: str) -> Frame |
      None`: it returns an aligned `Frame` when a complete `F;` frame arrives,
      `None` for timestamp/`C;`/partial lines. Holds the `C;` ref + current
      timestamp across calls.
- [x] Reuse Item 29's transform and `TrackPoint`/`Frame` structures exactly —
      **no** second copy of the coordinate math. Handle a stream that sends its
      `C;` reference once at the start and never again.
- [x] Robustness: malformed/partial messages never raise; unknown line types
      are ignored; a frame arriving before any `C;` ref uses the documented
      fallback.
- [x] pytest coverage: feed a recording's messages one-by-one and assert the
      streamed frames match the batch `Recording` (Item 29) **frame-for-frame**
      — identical aligned coordinates. This equivalence test is the key
      correctness guarantee and re-checks the §7 y-sign/no-rotation open items
      on the incremental path. (Use the Item 29 synthetic-recording fixture
      against the real `86_US95&SH8` site; read-only.)
- [x] DESIGN_HISTORY entry; check off this item.

Suggested prompt:
> [Fable] In EVO/iprj_designer, do Item 33 of ROADMAP.md following Item 32's
> design: build the pure streaming `LiveAligner` in `model/replay.py` — feed it
> one EVO message at a time, hold the `C;` reference + timestamp as state, and
> emit aligned world-feet `Frame`s reusing Item 29's transform and structures.
> Keep it GUI-free and pytest it for frame-for-frame equivalence with the
> batch `Recording`.

---

## 34 — Recorder Feed-Tap + Live Status (Target: Sonnet — routine) — DONE 2026-07-09 — needs Item 32

The routine item: give `capture/recorder.RecordingSession` a **subscription
seam** so a live consumer receives each captured message, per Item 32's
decision. The capture logic already exists (Item 31); this is a small,
mechanical fan-out plus a status readout, so Sonnet — but keep the
async/socket/file lifecycle exactly as Items 28/32 specified.

Scope:
- [x] Add a subscribe/callback (or queue) API to `RecordingSession` so
      `_run`'s per-message loop fans each message out to subscribers *in
      addition to* (or instead of, per Item 32) writing it to disk. Don't
      otherwise change auth/socket/file behavior.
- [x] A live status readout the GUI can poll — frames/sec, connection state,
      last-frame time — extending the existing `RecordingStatus`.
- [x] Headless pytest: a mock/fake message source drives `_run`'s fan-out;
      assert subscribers receive every message and the status counters update.
      No real socket; nothing written under `sites/`.
- [x] DESIGN_HISTORY entry; check off this item.

Suggested prompt:
> [Sonnet] In EVO/iprj_designer, do Item 34 of ROADMAP.md: add a subscription
> seam to `capture/recorder.RecordingSession` so a live consumer receives each
> captured message alongside the disk write (per Item 32), plus a frames/sec +
> connection status readout on `RecordingStatus`. Keep the async lifecycle as
> Item 28/32 specified. pytest the fan-out with a fake message source; land the
> DESIGN_HISTORY entry.

---

## 35 — Live Overlay Mode + Render (Target: Opus) — DONE 2026-07-09 — needs Items 33 & 34

Wire the streaming engine (33) and the feed-tap (34) into a "Live" mode that
overlays real-time track markers on the canvas, reusing Item 30's marker
layer. New GUI mode + async render seam → Opus.

Scope:
- [x] A read-only "Live" mode (per Item 32's UX decision) that connects using
      the Record panel's auth/host, subscribes to the feed-tap (34), runs the
      streaming aligner (33) per message, and keeps a shared "latest aligned
      frame" slot. *(New "Live" top-level tool → `effective_mode` "Live"; a
      Live-connect dialog shares the Record panel's `known_hosts` form + anchor-
      sensor pick and an optional `save=True` record-while-overlaying switch.
      The subscribed callback runs `LiveAligner.feed(msg, t=now)` and overwrites
      `v.live_frame = (frame, monotonic)` — one slot, drop-to-latest.)*
- [x] Drive Item 30's marker layer from the latest live frame on a
      fixed-cadence `ui.timer` (drop-to-latest, per Item 32) so socket rate is
      decoupled from redraw; reuse the same feet → viewport transform so live
      markers register at any zoom/pan. *(A 10 fps `live_timer` reads the slot
      and rewrites only `replay_layer` via the shared `_marker_svg` renderer
      Replay and Live now both call — same `replay_point_to_canvas` →
      `world_to_canvas` path, so live markers register at any zoom/pan.)*
- [x] Live guardrails from Item 32: stale-marker timeout, marker-per-frame cap,
      connection/error surfacing; optionally keep recording to disk while
      overlaying. *(`LIVE_STALE_TIMEOUT` (2 s) clears the overlay on a stalled/
      dropped stream; the aligner's `max_points_per_frame` caps markers; the
      timer stops + status surfaces `error`/disconnect; `save=True` keeps a
      capture and its file hands to the Item 30 loader unchanged.)*
- [x] DESIGN_HISTORY entry; check off this item. (Any model-side render helpers
      get pytest coverage; the live GUI/async wiring is exercised by hand plus
      a headless streaming-alignment check.) *(New `tests/test_live.py` drives
      the feed-tap → aligner → slot composition headless against a fake socket +
      the real 86_US95&SH8 site: lossless feed, drop-to-latest slot, frame-for-
      frame match with the batch engine, and the raising-subscriber /
      overlay-without-disk guards. `effective_mode("Live") == "Live"` covered in
      test_toolbar_modes. Full suite 540 pass; page builds headless.)*

Suggested prompt:
> [Opus] In EVO/iprj_designer, do Item 35 of ROADMAP.md: add the Live overlay
> mode on top of Items 33–34 — connect via the Record panel's auth, subscribe
> to the feed-tap, run the streaming aligner per message, and drive Item 30's
> marker layer from the latest frame via a fixed-cadence ui.timer
> (drop-to-latest, per Item 32). Apply Item 32's live guardrails. Land the
> DESIGN_HISTORY entry.

---

## 36 — Zone-Fit Robustness: Partial Matching + Outlier Rejection (Target: Opus)

Slotted for the next improvements batch (owner, 2026-07-09). The overlay-
rotation fix (`model/zonefit.py`) matches a project sensor to its `Z;` stream
slot only when the sensor's **entire** ordered zone signature matches — so an
iprj that isn't exactly concurrent with the capture degrades per-sensor,
all-or-nothing: a zone *moved* (same phase/output/vertex-count) still matches
but silently pollutes the fit, while a zone *added/deleted/re-assigned/
re-shaped* drops that whole sensor's correspondences. Upgrade the matcher to
survive a partially edited iprj — find the zones that still correspond, fit
on those, and reject the rest — while keeping the current refuse-don't-guess
character: a fit should still return `None` before it returns a confidently
wrong transform.

Scope:
- [ ] Per-zone matching when a sensor's full-signature match fails: pair
      zones by unique (kind, phase, output, vertex-count) keys within the
      sensor; align remaining ambiguous zones greedily (e.g. longest common
      ordered subsequence over the signature), never by coordinates alone.
- [ ] Residual-based outlier rejection before the final fit (iterative
      trimming or RANSAC-lite): fit, drop correspondences whose residual is a
      clear outlier (moved loops), refit; cap how many may be dropped so a
      mostly-wrong match still fails the gates rather than "converging".
- [ ] Keep the exact-signature path as the untouched fast path, and keep the
      existing gates (`MIN_ZONES`, `MIN_SPREAD_FT`, `MAX_MEAN_RESIDUAL_FT`)
      as the final arbiter; surface how many zones matched/dropped on
      `ZoneFit` so the GUI/status can report fit quality.
- [ ] pytest coverage over synthetic perturbations of the Banks fixtures
      (generated copies to `tests/out/`/scratchpad, never edits under
      `sites/`): one loop moved, a loop added, a loop deleted, an output
      re-assigned, several combined — asserting the recovered transform stays
      within tolerance of the clean fit — plus an all-sensors-mangled case
      asserting the fit refuses (translation fallback).
- [ ] Update `zonefit.py`'s module docstring + the OVERLAY_ROTATION brief's
      closure note; DESIGN_HISTORY entry; check off this item.

Suggested prompt:
> [Opus] In EVO/iprj_designer, do Item 36 of ROADMAP.md: make the Z;-zone
> similarity fit robust to a stale/edited iprj — per-zone matching by unique
> signature keys when a sensor's full signature no longer matches, plus
> residual-based outlier rejection with a drop cap, keeping the existing
> refuse-don't-guess gates and the exact-match fast path. pytest it over
> perturbed copies of the Banks fixtures; land the docs + DESIGN_HISTORY
> entry.

---

## 37 — Overlay Tab Consolidation: merge Record + Live/Replay into one "Overlay" surface (Target: Sonnet — routine) — DONE 2026-07-09

The routine quick-win of the 2026-07-09 batch, and the surface the calibration/
alignment work (38–40) then builds on. Today Record (Item 31), Replay (Item 30),
and Live (Item 35) are separate entry points. Fold them into a **single
"Overlay" tab/tool** with three sub-modes (Record / Replay file / Live stream)
sharing one host/credentials form and one status line, instead of three
scattered controls. This is UI consolidation over machinery that already exists
and works — no new coordinate, engine, or async behavior — so Sonnet, whole item.

Scope:
- [x] One "Overlay" top-level tool that hosts Record, Replay (file), and Live
      (stream) as sub-modes; retire the separate entry points without changing
      their underlying `RecordingSession` / replay-loader / `LiveAligner`
      wiring. Reuse the shared auth/host form (Live already shares Record's per
      LIVE_OVERLAY_PLAN §4) for both Record and Live.
- [x] Keep the read-only-canvas invariant intact for Replay/Live exactly as it
      is now (that invariant is *relaxed* later by Item 40 — do **not** touch it
      here; this item is a pure re-grouping so 40 has one clean surface to
      modify).
- [x] One consolidated status line (frames/sec, connection state, last-frame
      time — the Item 34/§6 readout) serving whichever sub-mode is active.
- [x] No regression to existing record/replay/live behavior; DESIGN_HISTORY
      entry; check off this item. (Mostly GUI wiring; add/adjust any
      `effective_mode` tests the sub-mode restructure touches.)

Suggested prompt:
> [Sonnet] In EVO/iprj_designer, do Item 37 of ROADMAP.md: consolidate the
> Record, Replay, and Live entry points into a single "Overlay" tool with three
> sub-modes sharing one host/credentials form and one status line, without
> changing the underlying RecordingSession / replay-loader / LiveAligner wiring
> or the read-only-canvas invariant (Item 40 relaxes that later, not here). Land
> the DESIGN_HISTORY entry.

---

## 38 — Sensor-Transform Layer + Interactive Alignment: Architecture (Target: Opus) — DONE 2026-07-09 → CALIBRATION_ALIGNMENT_PLAN.md

Prerequisite planning session for Items 39–40 — a **decision document, no
code** (e.g. `CALIBRATION_ALIGNMENT_PLAN.md`), the sibling of
RECORD_PLAYBACK_PLAN / LIVE_OVERLAY_PLAN for this batch. Opus owns it because
Items 39–40 inherit every choice, and because it must get the **two distinct,
composed transforms** right (owner clarification, 2026-07-09 — these are *not*
two ways of authoring one artifact):

1. **Calibration — relational, background-blind.** Uses the vehicle tracks to
   make the sensors *agree with each other* about where a given vehicle is. It
   never references loops/zones/background. Output = a locked set of per-sensor
   relative corrections; afterward the sensors behave as **one internally-
   consistent rigid body**. This is the residual/vehicle-pair math (Fable, 39).
2. **Group placement — visual, background-referenced.** The user moves/rotates
   that *now-locked* sensor cluster so the vehicle tracks visually sit over the
   zones/background where they belong. The software **holds the inter-sensor
   relationship fixed**, so a drag repositions the whole consistent group, not
   one sensor relative to another. `zonefit.fit()`'s `Z;` global similarity is
   the *automatic* version of this placement; the manual drag is the override/
   refinement when that auto-fit is wrong or absent.

Why they're different jobs (the load-bearing distinction to preserve): calibration
alone **can't** place onto the background — it has no notion of where the
background is; a group drag alone **can't** fix inter-sensor disagreement — a
rigid move preserves relative error. So the pipeline composes them in order:
**EVO frame → per-sensor calibration deltas (sensors agree) → one group rigid
placement onto the map (auto from zonefit, or hand-adjusted) → world-feet →
viewport.**

Key framing established with the owner (2026-07-09), to be turned into decisions:
- **Motivation — the error is upstream and human.** Sensor position/azimuth is
  set today by eyeballing each sensor against the background *independently*, so
  the sensors end up **disagreeing with each other** about where vehicles are.
  Calibration re-estimates that eyeballed placement from vehicle observations so
  the sensors agree and move as one unit; the locked group is *then* fit to the
  background under the standing constraint that they still agree.
- **The two transforms differ in kind, not just in job.** The `Z;` zone transform
  (stream/recording coords ↔ iprj coords) is an **exact, one-way mathematical
  derivation** — deterministic, *not* a source of error; zonefit recovers it to
  float precision. **Vehicle positions are noisy radar approximations**, so
  calibration is inherently a *statistical* fit over many isolated vehicle pairs
  (residual minimization + isolation gates, needs volume), **not** a clean
  closed-form solve like the zone transform. This is exactly why calibration is
  the hard, Fable-worthy piece (39) and why the guardrails/gates matter.
- **Calibration is *relational between sensors*, background-independent.**
  `zonefit.fit()` already recovers **one global similarity** (`a`,`t`) over all
  sensors' matched `Z;` zones pooled together; its ~5–7 ft residual (Banks) *is*
  the inter-sensor placement disagreement left by those independent eyeballed
  placements — the exact thing calibration removes, using vehicle tracks rather
  than the map. zonefit fits a single global transform, so it *structurally
  cannot* fix per-sensor disagreement; that's calibration's job. (Owner:
  calibration is **not** a no-`Z;` fallback.)
- **Group placement keeps the relationship locked.** The interactive move/rotate
  operates on the calibrated cluster *as a rigid body* — the software preserves
  the inter-sensor corrections while the user seats the group onto the
  background "as they see best," overlay tracking live as they drag.
- **Preview + commit (the owner's "both").** Both transforms render as a
  reversible overlay-only state (project untouched); the user can then **commit**
  the composed result — writing the resolved per-sensor correction back into each
  iprj sensor's azimuth/position (what `EVO/sensor_calibration.py` recommends) —
  or keep it as a designer-side layer. Decide the persistence format for the
  uncommitted state.

Scope — decide and write up (with rationale) each of:
- [x] **The two-transform representation + compose order.** How the per-sensor
      calibration deltas and the single group-placement transform are stored and
      composed: EVO frame → **per-sensor calibration** → **group placement**
      (auto `zonefit`/`replay` fit, overridable by the manual drag) → world-feet
      → viewport. Whether calibration is applied in EVO-meter space or world-feet
      space. Confirm it is one layer shared by both replay and live (reuse the
      §1b transform; no second copy).
- [x] **Relational calibration solver seam.** Generalize
      `EVO/sensor_calibration.py`'s S1→S0 vehicle-pair rigid fit to **N sensors
      (3+)** and to a joint "make all sensors agree" solve (background-blind).
      Decide the reference (sensor-0 anchor vs. joint least-squares over all
      pairs), the pairing/isolation gates, and what "locked relationship" means
      numerically (the corrections that make the group internally consistent).
      This is the piece the owner flagged for Fable review (Item 39).
- [x] **Group-placement handle.** How the auto placement (zonefit's global
      similarity) is exposed as an editable group transform, and how the manual
      drag overrides/refines it while the calibration deltas stay locked
      underneath. When there's no `Z;`, the group placement starts from the
      existing translation fallback and is placed by hand.
- [x] **Interactive-authoring UX / persist-into-edit.** How the live/replay
      overlay **persists into draw/edit mode** (relaxing Item 30/35's
      read-only-mode invariant — the load-bearing GUI change), how moving/
      rotating the sensor group re-renders the overlay in real time, and the
      lock/unlock affordance (normal use = move the locked group; unlock only to
      re-run/adjust calibration). Reuse the existing sensor drag/rotate handles.
- [x] **Preview → commit.** Format for the uncommitted state (sidecar keyed to
      project? in-memory only?), and the commit path that folds the composed
      (calibration ∘ placement) result into per-sensor iprj azimuth/position —
      including the sign/units math (world-feet transform → iprj sensor azimuth
      degrees + meter/pixel position) and how re-loading a committed project then
      reads ≈identity.
- [x] **Apply to live *and* recording.** How the composed transform feeds both
      the Item 30 replay render and the Item 35 live render (one path, both), and
      whether committing mid-session re-aligns an in-flight live overlay.
- [x] **Guardrails / degeneracy.** Too-few pairs, collinear pairs, a sensor with
      no matched pairs (it can't be calibrated — keep its uncorrected position
      and flag it), and how the whole flow behaves on a site with no `Z;` (group
      placement is manual from the translation fallback; calibration still runs
      if there are vehicle pairs).
- [x] Output the plan as a design doc under `EVO/iprj_designer/` and log the
      decisions in [[DESIGN_HISTORY.md]] — no feature code this session.
      *(→ [[CALIBRATION_ALIGNMENT_PLAN.md]] + DESIGN_HISTORY entry.)*

Suggested prompt:
> [Opus] In EVO/iprj_designer, do Item 38 of ROADMAP.md: produce the
> architecture/decision document unifying vehicle-pair calibration and the
> "move/rotate a sensor to align the overlay" gesture as one **per-sensor
> overlay transform** composed on top of zonefit's global fit (transform-of-a-
> transform, refine-residual only). Decide the transform layer + compose point,
> the N-sensor relational solver seam (generalizing EVO/sensor_calibration.py),
> the persist-overlay-into-edit interactive authoring UX, the preview→commit-to-
> iprj path with sign/units math, apply-to-live-and-recording, and guardrails.
> Land the doc and DESIGN_HISTORY entry — no feature code.

---

## 39 — Per-Sensor Transform Engine + N-Sensor Calibration Solver in `model/` (Target: Fable — hardest) — needs Item 38

The correctness-critical core: a **pure, headless** transform layer that composes
the two transforms Item 38 defines, plus the relational vehicle-pair calibration
solver. Hardest, most bug-prone piece — the background-blind multi-sensor "make
the sensors agree" least-squares, and the coordinate/sign math composing those
per-sensor deltas with the group placement into world-feet — and the owner
explicitly asked for Fable review/improvement of the existing solver, hence Fable.

Scope:
- [x] The composed transform in `model/` (e.g. `model/calibration.py` or an
      extension of `replay.py`/`zonefit.py` per Item 38): **per-sensor
      calibration deltas → group placement → world-feet**, in Item 38's compose
      order and space. One layer used by both replay and live, reusing the
      existing transform (no second copy of the coordinate math).
- [x] **Relational calibration solver** — port + generalize
      `EVO/sensor_calibration.py` to **N sensors (3+)**: the isolated-pair finder
      and the rigid/similarity least-squares, retargeted from a raw S1→S0 fit to
      a joint, **background-blind** solve that makes all sensors agree (the locked
      inter-sensor relationship). It reads only vehicle pairs, never the map.
- [x] **Group-placement transform** — the editable rigid transform that seats the
      calibrated cluster onto the map, seeded from the existing `zonefit`/
      translation fit and overridable (the value Item 40's drag writes). Keep it
      one rigid transform over the whole locked group.
- [x] The commit math (composed calibration ∘ placement → per-sensor iprj azimuth
      + position) as a pure function, so Item 40 just calls it; round-trips so a
      committed project re-loads to ≈identity.
- [x] Robustness/guardrails from Item 38: too-few/collinear pairs, a sensor with
      no pairs (uncalibrated, flagged — not silently identity-merged), never
      raise on degenerate input.
- [x] pytest coverage against a real multi-sensor site fixture under `sites/**`
      (read-only; output to `tests/out/`/scratchpad), including: a calibration
      recovery test (perturb one sensor's frame, recover the delta that re-agrees
      it), group-placement compose-order correctness (a group move lands markers
      where expected on the background *without* changing inter-sensor
      agreement), and a commit→reload ≈identity round-trip.
- [x] DESIGN_HISTORY entry; check off this item.

Suggested prompt:
> [Fable] In EVO/iprj_designer, do Item 39 of ROADMAP.md following Item 38's
> design: build the pure composed transform (per-sensor calibration deltas →
> group placement → world-feet) plus the N-sensor **relational, background-blind**
> vehicle-pair calibration solver (generalizing EVO/sensor_calibration.py to make
> all sensors agree), the editable group-placement transform seeded from the
> zonefit fit, and the commit math (composed → per-sensor iprj azimuth/position),
> all as pure functions. Keep it GUI-free; pytest calibration-recovery,
> group-placement compose-order, and commit→reload-≈identity against a real
> multi-sensor site.

---

## 40 — Interactive Alignment Mode + Apply Calibration to Live/Recording (Target: Opus) — DONE 2026-07-10; reframed per owner fixes 2026-07-11 — needs Items 38 & 39

> **Owner fixes (2026-07-11, Fable session).** Align reframed as "move the
> sensors": the `Z;` auto-fit stays the automatic default mapping at open;
> Align now shows **ghost sensor copies** that drag/rotate together with the
> tracks against the fixed background, Commit writes the composed move
> (calibration *and* group-placement delta — a pure group drag commits) into
> per-sensor azimuth/position, the 2-click rotate gained its pivot cross +
> live preview, and auto-calibrate is restricted to stream slots mapped to
> project sensors (no more impossible "S5/S6 too few pairs" on a 4-sensor
> site). Details in DESIGN_HISTORY 2026-07-11 and the
> CALIBRATION_ALIGNMENT_PLAN §5 amendment.

Wire the Item 39 engine into the NiceGUI shell: **persist the overlay into
draw/edit** (relaxing the read-only-mode invariant), let the user move/rotate
the calibrated sensor group to seat the overlay on the background with live
feedback, and expose preview→commit. New GUI seam + the invariant change → Opus.

Scope:
- [x] Relax the read-only-canvas invariant so a Replay/Live overlay **persists
      into draw/edit mode** (per Item 38) — the marker layer stays live while
      sensor drag/rotate handles are active; keep the separate `replay_layer`
      + `pointer-events:none` machinery, drive it off the same transform.
      *(First realized only as the **Overlay › Align** sub-mode — the owner
      rejected that reading 2026-07-11: switching to Draw/Edit froze/cleared
      the overlay. Fixed same day (Fable): `marker_source()` keeps a running
      live feed or loaded recording rendering — playback still animating — in
      every non-overlay mode; only picking a different Overlay source stops
      the current one. See DESIGN_HISTORY 2026-07-11.)*
- [x] **Group placement (the normal gesture):** moving/rotating a sensor drags
      the whole calibrated cluster as a **rigid body** (inter-sensor relationship
      held locked by Item 39's calibration) and re-renders the overlay through the
      composed transform **in real time**, for both live and loaded-recording
      overlays — the user seats the tracks over the zones/background by eye.
      *(Left-drag → `translated(G)`; 2-click Rotate-group → `rotated_about(G)`;
      markers re-align from raw meters through `current_alignment()` per render.)*
- [x] "Auto-calibrate" action that runs the Item 39 **relational** solver over the
      current live/recorded pairs (makes the sensors agree — background-blind) and
      locks the result; an **unlock** affordance to re-run/adjust it. This is a
      distinct step from group placement, per Item 38. *(Solves over the
      recording's frames or a bounded live-frame buffer; unlock → per-sensor
      `Cᵢ` nudge via `nudged_delta`.)*
- [x] Preview→commit UI: apply as reversible overlay state, or commit the composed
      result into per-sensor iprj azimuth/position (Item 39's commit math) with
      confirm + undo. *(In-memory until an explicit Commit; confirm dialog +
      snapshot-backed Undo button; calibration stays applied to the uncorrected
      recording so the overlay doesn't jump, plan §5d.)*
- [x] Guardrails surfaced (pair count / residual / degenerate sensor), and the
      Item 20/30 performance carries over (marker-layer-only rewrite; don't
      re-render the static SVG on every drag tick).
- [x] DESIGN_HISTORY entry; check off this item. (Model-side helpers get pytest
      coverage; GUI wiring exercised by hand + a headless transform check.)

Suggested prompt:
> [Opus] In EVO/iprj_designer, do Item 40 of ROADMAP.md on top of Items 38–39:
> persist the Replay/Live overlay into draw/edit mode; make moving/rotating a
> sensor drag the whole calibrated group as a rigid body and re-render the
> overlay live (group placement onto the background); add a distinct
> auto-calibrate action that runs the relational solver over the current pairs
> and locks the inter-sensor agreement; and a preview→commit path that writes the
> composed result into per-sensor iprj azimuth/position. Reuse Item 30's
> marker-layer-only rewrite for performance. Land the DESIGN_HISTORY entry.

---

## 41 — Track Stitching / Fusion: Architecture (Target: Opus) — DONE 2026-07-10 → FUSION_PLAN.md — reviews prior art + data first

Prerequisite planning session for Items 42–43 — a **decision document, no
code**. Previous fusion attempts (`../fusion_visualizer.py` ~100 KB,
`../fusion_strict_logic.html`) failed under Sonnet/other models, so the owner
wants Opus to **review the prior art *and* the raw data first**, then decide
salvage-vs-clean-room before Fable builds the engine (owner's explicit choice,
mirroring how Items 28/32 were scoped). Opus owns it because 42–43 inherit the
approach and the failure post-mortem.

Two distinct stitching problems the owner named, both in scope:
- **Cross-sensor fusion** — the same real vehicle seen by multiple sensors
  becomes **one** fused trajectory (dedup in overlap + continuous ID across
  sensor-to-sensor handoff).
- **Within-sensor stitching** — an object tracked into e.g. the intersection
  that **stops, drops, and re-appears as a new object** when it moves again must
  be re-joined into one continuous track. Temporal-gap + spatial-plausibility
  bridging, not just cross-sensor merging.

Scope — decide and write up (with rationale) each of:
- [x] **Prior-art post-mortem.** Read `../fusion_visualizer.py` /
      `../fusion_strict_logic.html` and the raw recordings; document *why* prior
      attempts failed and what (if anything) is salvageable vs. clean-room in
      `model/`. Note that this per-sensor calibration batch (38–40) removes the
      inter-sensor offset that likely sabotaged earlier cross-sensor matching —
      decide whether stitching should **depend on** a calibrated overlay.
      *(→ FUSION_PLAN §0–1: clean-room in pure `model/fusion.py`; the `.html`
      files are just rendered plotly output; the prior RBF spatial warp is
      retired in favor of the 38–40 calibration, so fusion **depends on** a
      calibrated overlay and drops the RBF + `gates.json`.)*
- [x] **Data model & seam.** Where fusion sits relative to the aligned `Frame`
      stream (`model/replay.py`) — a pure transform over aligned frames producing
      fused track IDs — keeping `model/` pure and headless-testable.
      *(→ §2: `model/fusion.py`, a transform *after* alignment in world-feet
      over the Item 29 `Frame`s → `FusionResult` + `id_of`; parse `Frame.t`→
      seconds, work in tolerant time windows, no pandas.)*
- [x] **Within-sensor gap-bridging policy.** Gap time/distance windows, heading/
      speed continuity, the "stopped in the intersection then resumed" case; how
      to bridge without wrongly merging two different vehicles.
      *(→ §3: velocity-selected time/space windows, forward ±60° cone, class
      gate, refuse-on-ambiguity.)*
- [x] **Cross-sensor association policy.** Overlap-zone dedup + handoff ID
      continuity; whether it runs after calibration (38–40) and how much it
      relies on that alignment quality.
      *(→ §4: overlap dedup + handoff-id continuity; **assumes** calibration,
      degrades flagged (not silently) when uncalibrated.)*
- [x] **Batch vs. streaming.** Whether fusion must also run incrementally on the
      live path (`LiveAligner`) or is replay/batch-first; the state a streaming
      stitcher would carry.
      *(→ §5: batch/replay-first; live stays raw; streaming is a documented
      future upgrade.)*
- [x] **Success criteria & test strategy.** Concrete, checkable acceptance
      (e.g. N hand-labeled trajectories on a real recording that must fuse into
      M), so Item 42 has a real correctness gate — the thing prior attempts
      lacked.
      *(→ §6: labeled acceptance set on the real `86_US95&SH8` fixture (now
      present — the Item 29/33 "no recording" caveat is stale) + deterministic
      synthetic don't-merge cases; label format seeded.)*
- [x] Output the plan as a design doc under `EVO/iprj_designer/` and log the
      decisions in [[DESIGN_HISTORY.md]] — no feature code this session.
      *(→ [[FUSION_PLAN.md]] + DESIGN_HISTORY entry.)*

Suggested prompt:
> [Opus] In EVO/iprj_designer, do Item 41 of ROADMAP.md: produce the
> architecture/decision document for track stitching + fusion. First post-mortem
> the prior art (../fusion_visualizer.py, ../fusion_strict_logic.html) and the
> raw data and decide salvage-vs-clean-room. Design both within-sensor
> gap-bridging (stop/drop/resume) and cross-sensor fusion (overlap dedup +
> handoff ID) as a pure transform over aligned Frames, decide batch-vs-streaming,
> and set concrete success criteria/test strategy. Land the doc and
> DESIGN_HISTORY entry — no feature code.

---

## 42 — Fusion Engine in `model/` (Target: Fable — hardest) — DONE 2026-07-10 — needs Item 41

The correctness-critical core the owner most wants Fable on (prior non-Fable
attempts failed): a **pure, headless** stitching engine over the aligned `Frame`
stream — within-sensor gap-bridging **and** cross-sensor fusion, per Item 41's
design, gated by Item 41's success criteria.

Scope:
- [x] A pure `model/` stitcher (e.g. `model/fusion.py`) consuming aligned
      `Frame`s (Item 29) and emitting fused track IDs — within-sensor bridging
      (stop/drop/resume) + cross-sensor association (overlap dedup + handoff),
      per Item 41. Optionally consumes the calibrated overlay (Item 40) if 41 so
      decided.
      *(→ `model/fusion.py`: `fuse(frames, *, calibrated)` → `FusionResult`
      (`tracks` + `id_of` for Item 43); the caller states whether the frames
      came through a calibrated overlay — uncalibrated widens the cross-sensor
      gate and flags `low_confidence`, per plan §4b.)*
- [x] Streaming variant only if Item 41 required it (state carried across
      frames), reusing the batch logic — no second copy.
      *(→ Item 41 decided batch-only (§5): no streaming variant; live stays
      raw for Item 43.)*
- [x] pytest against Item 41's labeled acceptance set on a real recording
      (read-only fixtures; output to `tests/out/`/scratchpad): the hand-labeled
      trajectories fuse into the expected fused tracks; adversarial "don't merge
      these two distinct vehicles" cases hold.
      *(→ `tests/fixtures/fusion_labels_86_us95_sh8.json`, verified by
      trajectory inspection, + `tests/test_fusion.py` (28 tests): labeled
      acceptance on the calibrated overlay, graceful+flagged uncalibrated,
      calibration-tightens-overlaps, synthetic don't-merge adversarial
      cases.)*
- [x] DESIGN_HISTORY entry; check off this item.

Suggested prompt:
> [Fable] In EVO/iprj_designer, do Item 42 of ROADMAP.md following Item 41's
> design: build the pure `model/` fusion engine over aligned Frames — within-
> sensor gap-bridging (stop/drop/resume) and cross-sensor dedup+handoff — gated
> by Item 41's labeled acceptance tests on a real recording. Keep it GUI-free;
> include the adversarial don't-merge cases.

---

## 43 — Fusion Overlay Wiring (Target: Opus) — DONE 2026-07-10 — needs Item 42

Wire the Item 42 engine into the overlay render: show **fused** tracks (one
marker/ID per real vehicle) with a raw↔fused toggle, on both replay and live.
New GUI seam → Opus.

Scope:
- [x] Feed the aligned frame stream through the Item 42 stitcher and render fused
      track IDs on the existing marker layer (Item 30/35), both replay and live.
      *(Two pure `model/fusion.py` render helpers — `frame_times_s` (extracted
      from `fold_tracks`, shared clock) + `fused_frame_markers` → per-frame
      `{fused_id: (x_ft, y_ft)}`, preserving the engine's overlap dedup on
      screen. `Viewer.ensure_fusion()` caches `fuse()` by (recording,
      calibrated?); `replay_marker_svg` branches on `fused_view`.)*
- [x] A raw↔fused toggle so the user can compare; consistent fused-ID labelling/
      colour (à la `evo_replay`), reusing the marker layer — no static-SVG
      re-render (Item 20/30 performance). *("fused" switch in the Replay
      transport; a shared `_marker_glyph` backs raw + fused so they read
      identically; fused hue = evo_replay palette by `fused_id % 10`. Only the
      `replay_layer` content is rewritten per tick.)*
- [x] Streaming fusion on the live path only if Item 41/42 built it; otherwise
      fused view is replay/batch and live shows raw. *(Item 41/42 decided
      batch-only, §5 — so the toggle lives only in Replay; Live is unchanged
      and always raw.)*
- [x] DESIGN_HISTORY entry; check off this item. (Model helpers pytested; GUI
      wiring by hand + a headless fused-render check.) *(test_fusion.py +5,
      new test_fusion_gui.py (4); full suite 626 pass; page builds headless.)*

Suggested prompt:
> [Opus] In EVO/iprj_designer, do Item 43 of ROADMAP.md: wire the Item 42 fusion
> engine into the overlay render — fused track IDs on the existing marker layer
> with a raw↔fused toggle, on replay (and live if 41/42 built streaming fusion),
> reusing Item 30's marker-layer-only rewrite. Land the DESIGN_HISTORY entry.

---

## 44 — Ground-Truth Stitching Round (Target: Fable) — DONE 2026-07-13 — needs Items 42/43

The owner hand-watched five captures (64_32, 2_84_xx404, 2_85, 2_86_xx107,
2_86_xx735) and labeled handoff / persistence / stray groups; this item
turns those observations into a scored fixture and improves the Item 42
engine against it.

Scope:
- [x] Resolve the owner's abbreviated ids to raw oids and encode the labels
      (with unsure/ped/fused-ref annotations) as
      `tests/fixtures/stitch_observations_2026-07-13.json`; scoring harness
      `scripts/fusion_eval.py` runs all five captures the way the GUI does.
- [x] Decode the vendor-combined id convention (slot `oid%10 >= 4` = the
      sensor's own fusion: both raw ids retired, fresh id+4 continues, zero
      overlap) and join those seams in `model/fusion.py`.
- [x] Red-light "parked resume" bridging (30-90 s drops a few feet apart)
      with an occupancy veto standing in for phase-status decoding;
      re-label bridges (brief double-tracked handover); same-sensor
      duplicate absorption; cross-sensor bridge candidacy.
- [x] Majority-class fold + behavioral pedestrian override (walking-pace
      cls-30 tracks are non-motorized); `FusedTrack.category`; stray
      flagging (`kind="stray"`: flickers + same-way shadows), never deleted.
- [x] GUI: pedestrians draw as diamonds, strays render dimmed/dashed, on
      both raw and fused marker paths.
- [x] Two old us95 labels corrected on seam evidence (421505, 420685 were
      attributed to the wrong platooning vehicle); labeled acceptance +
      observation acceptance in pytest.
- [x] Eval: handoff 21/26, persistence 14/17, anchor 3/4, stray 3/3
      (baseline 17/26, 4/17, 3/4, 2/2). Known misses + follow-ups (FIFO
      queue matching, stuck-ghost tails, shadow-vs-partner ambiguity when
      uncalibrated) recorded in DESIGN_HISTORY and the module doc.

---

## 45 — Overlay Review Round: In-GUI Labeling + Fused Display + Ghost Tails (Target: Fable) — DONE 2026-07-14 — needs Items 43/44

The owner's 2026-07-14 batch, one session: move the Item 44 ground-truth
labeling workflow into the overlay itself, make the fused display show its
underlying objects, smooth the on-screen handoff, and deliver the Item 44
stuck-ghost-tail follow-up.

Scope:
- [x] **Review labeling mode** (`model/review.py` + Replay transport): a
      `review` switch arms marker clicking — select raw tracks by click
      (halo rings; dashed once labeled), commit groups as handoff /
      persistence / anchor / stray with `ped`/`unsure`/note (`same_sensor`
      derived), save/resume `<capture>.observations.json` beside the
      recording in the Item 44 observation schema;
      `fusion_eval.py --obs <file>` scores review output directly.
- [x] **Fused-view underlay**: raw per-sensor markers at 20 % opacity under
      the fused markers (marker-layer-only), raw oid labels while reviewing.
- [x] **Handoff smoothing**: pure `smooth_seams()` — display copy eased near
      cross-source seams only; engine geometry, eval, and tests untouched.
- [x] **Stuck-ghost tail trimming** (Item 44 follow-up): freeze-onset
      kinematics (boundary + trailing-window speed ≥ 15 ft/s into a ≥ 3 s
      hold-to-death within 4 ft) split the frozen tail into a dimmed
      `kind="ghost"` track before matching, so sticks can't poison bridges
      or the occupancy veto; braking cars / parked position-hops rejected.
- [x] Eval unchanged (21/26, 14/17, 3/4, 3/3); suite 656 → 677;
      DESIGN_HISTORY entry.

---

## 46 — Self-Calibrating Fusion (Target: Fable) — DONE 2026-07-14 — needs Items 39/42

Owner observation: the fused view codes one object as several; root cause
analysis showed the pipeline seats sensors by zonefit placement only — the
Items 38–40 relational calibration never ran unless authored by hand in
Align, so cross-sensor association worked through the widened low-confidence
gate on ~20 ft inter-sensor disagreement.

Scope:
- [x] **`model.replay.autocalibrate(project, recording)`**: the Align
      Auto-calibrate gesture as a pure batch pre-pass — relational solve
      over the stream's own vehicle pairs (`reference=None`, **no slots
      filter**: the solve corrects stream geometry, not sensor configs, so
      an unmapped-but-real sensor like 32_US12&21st's slot 2 calibrates and
      junk slots are refused by the guardrails, not a list), placement refit
      over calibrated centroids, `realign`. On refusal the frames come back
      unchanged with the solve report attached.
- [x] **Consumers**: `Viewer.ensure_fusion` self-calibrates an uncalibrated
      recording before fusing (fused view only — the raw overlay and the
      Align authoring/commit workflow are untouched); `fusion_eval.py` does
      the same (`--no-autocal` reproduces the old runs) and prints the
      per-sensor solve line.
- [x] **Flicker veto**: a track with the stray shape (sub-`stray_dur_s`,
      sub-`stray_net_ft`) is refused as a bridge endpoint — one radar blip
      no longer anchors a stopped/parked bridge and poisons the fused
      sensor set (the calibrated 2_86_xx107 regression).
- [x] **Stitch↔fuse fixpoint**: `fuse` alternates gap-bridging with
      cross-sensor association until no track merges — a two-sensor
      red-light gap that is ambiguous raw (two views per endpoint) bridges
      uniquely once each side's views are one composite.
- [x] Eval: 41/50 → **44/50** self-calibrated (handoff 21→23/26,
      persistence 14/17, anchor 3→4/4, stray 3/3), 43/50 with
      `--no-autocal`; **no regressions in either mode**. Remaining misses
      are all refused-calibration captures (2_84/2_85: too few pairs) or
      same-sensor splits.
- [x] pytest: autocalibrate (synthetic recover/refuse + real-site),
      flicker veto, queue-resume fixpoint; suite 677 → 682. DESIGN_HISTORY
      entry.

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

- (Now scoped as Items 32–35 above: display objects from a **live** stream in
  the canvas, real-time, reusing the record/playback feed.)
- **Overlay rotation — RESOLVED 2026-07-09 (Fable session).** Fixed
  automatically, no human line-up needed: the stream's `Z;` GetCfg line carries
  every configured zone in the EVO frame, each project sensor is identified to
  its stream slot by an ordered zone signature, and a least-squares similarity
  over the matched zone centroids recovers rotation+scale+translation exactly
  (per-sensor fits are numerically exact — the vendor generated one side from
  the other). Banks now aligns at −34.9° / 5.6 ft mean residual; US95&SH8 fits
  ≈identity so correct sites are untouched. Lives in `model/zonefit.py`, wired
  through `parse_recording` + `LiveAligner` with the old translation as
  fallback whenever no usable `Z;` exists. Details + closure notes:
  [OVERLAY_ROTATION_INVESTIGATION.md](OVERLAY_ROTATION_INVESTIGATION.md);
  session entry in DESIGN_HISTORY.md. The manual 2-point line-up idea is
  superseded for recordings/live with `Z;`; it only remains potentially useful
  for legacy captures that never recorded one (fold into the `calibrate.py`
  item below only if that case ever matters). Robustness to a stale/edited
  iprj (partial zone matching + outlier rejection) is scoped as Item 36 above.
- (Now scoped as Items 38–40 above: the calibrate/line-up workflow — two
  composed transforms: **relational vehicle-pair calibration** (makes the
  sensors agree with each other, background-blind) plus a **group placement**
  the user seats onto the zones/background by moving/rotating the locked sensor
  cluster, with preview→commit into the iprj. Interaction reference:
  `~/pyatspm/src/atspm/video/calibrate.py`.)
- (Now scoped as Items 41–43 above: track stitching / fusion — within-sensor
  gap-bridging + cross-sensor fusion into one trajectory per vehicle.)
