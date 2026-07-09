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

> **Temporary routing note (2026-07-08):** Items 28–35 below (the record/
> playback batch 28–31, now done, and the live-overlay batch 32–35 added the
> same day) use the owner's stated per-model division — **Fable for the
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
- **Overlay rotation (reopened).** Some sites (Banks) render the recording/live
  overlay visibly rotated (~25–34°) while others (US95&SH8) are correct under the
  current pure translation. An automatic 2D-similarity fit over the `C;`-line ↔
  `.iprj` sensor positions was tried and **reverted** (commit 0a45371). The
  2026-07-09 diagnosis pass (DESIGN_HISTORY) settled it: a single
  rotation+scale+translation **does** align the whole Banks corridor (every
  detector within 0–32 ft when calibrated on the vehicle's ~600 ft path →
  −33.7°, scale 1.23), so it's not a nonlinear/data-defect problem — but the
  ~99 ft, hand-placed **2-sensor baseline is too short to recover those params**
  (it gave −26.9° / 0.91, drifting to 91 ft at the far end). **Do not retry
  sensor auto-fit.** The transform must be calibrated on a long baseline, i.e. a
  human line-up. Scope this as a per-site **2-point "line-up" alignment** (pick a
  track point, place it on the map, twice → solve rotation+scale+translation),
  identity by default so already-correct sites are untouched; fold in with the
  `calibrate.py` line-up workflow future item below. The `C;` multi-sensor decode
  from the reverted attempt is worth reusing for a suggested starting guess.
  **Full handoff brief for a Fable diagnosis session:**
  [OVERLAY_ROTATION_INVESTIGATION.md](OVERLAY_ROTATION_INVESTIGATION.md) (the
  "wrong iprj" theory was since ruled out on hardware — concurrent iprjs still
  render rotated).
- Integrate the line-up/calibrate workflow (see
  `~/pyatspm/src/atspm/video/calibrate.py`) more directly into the app.
