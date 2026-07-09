# Live Overlay — Architecture & Feed-Tap Seam

**ROADMAP Item 32 (Opus). Decision document — no feature code.** Extends
[RECORD_PLAYBACK_PLAN.md](RECORD_PLAYBACK_PLAN.md) (RPP); read that first. Every
choice here is inherited by Items 33 (streaming engine), 34 (recorder feed-tap),
and 35 (Live mode + render). Summary of what each downstream item inherits is in
§7.

Scope: display EVO track objects on the canvas from a **live** websocket stream,
in real time — reusing the record/playback machinery (28–31) rather than
rebuilding it — without violating the `model/`-is-pure rule (CLAUDE.md).

---

## 0. Headline finding — the hard parts are already done; the one new thing is a stateful stream

The live overlay is a small delta on top of 28–31, not a new subsystem:

- **Coordinate reconciliation** — reused verbatim. The EVO-meters → world-feet
  transform (RPP §1b) is already implemented and tested in `model/replay.py`
  (`anchor_world_ft` + the `m_to_ft`-on-offset / `emp`-on-anchor split). Live
  data goes through the *same* transform; there is no second coordinate path.
- **The marker layer** — reused verbatim. Item 30 already built a separate
  `pointer-events:none` SVG layer (`replay_layer`) rewritten per `ui.timer` tick
  by `replay_marker_svg()`, plus the `replay_point_to_canvas` → `world_to_canvas`
  render path. Live markers render through the identical path.
- **The websocket capture controller** — reused. `capture/recorder.py`'s
  `RecordingSession` already authenticates and streams on NiceGUI's own loop
  (Item 31). Live just needs to *watch* that stream.

**What is genuinely new — and the only thing that needs designing — is the
real-time seam:** getting each frame from the live socket onto the canvas *as it
arrives*, not from a file after the fact. Two sub-problems: (a) a **stateful,
one-message-at-a-time** parser (the batch parser needs the whole file), and (b)
the **async → GUI** hand-off with backpressure so a fast socket can't flood the
redraw. Everything below serves those two.

**The load-bearing distinction that drives every decision below:** parsing is
**stateful and must be lossless** — the aligner has to see *every* message to
hold the `C;` reference and current timestamp across calls — while rendering is
**stateless and lossy** — the canvas only ever needs the *latest* aligned frame.
So drop-to-latest belongs **after** the aligner (at the aligned-frame slot),
**never** at the raw-message tap. Tapping "latest raw message" would drop the
one-time `C;` reference or whole `F;` frames and corrupt the parse. This is why
the feed-tap is lossless and the render slot is drop-to-latest.

---

## 1. Feed-tap seam

`RecordingSession._run`'s per-message loop today does exactly one thing with each
message: `f.write(...)` to disk (recorder.py:131-135). Live needs a *second*
consumer of that same stream.

**Decision: a synchronous subscriber-callback list on `RecordingSession`.** Add
`subscribe(cb)` / `unsubscribe(cb)` and a `self._subscribers: list[Callable[[str],
None]]`; in the `async for message` loop, after (or instead of, per below) the
disk write, call each subscriber with the raw message. Rejected alternatives and
why:

- **`asyncio.Queue`** — overkill and adds a *failure mode*. It needs a second
  consumer task that can lag; if it lags, the queue grows unbounded (a live feed
  never ends). The consumer here (a pure, microsecond aligner + a slot write)
  has no reason to run on its own task. A queue would reintroduce the very
  backpressure problem we solve more simply at the render slot (§3).
- **Shared "latest raw message" slot** — **wrong for a stateful parser** (§0):
  it drops messages, so the aligner would miss the `C;` ref or `F;` frames.

Because `_run` runs on the server event loop and subscriber callbacks are invoked
synchronously between `await`s, the callback runs on the **same thread** as the
`ui.timer` that later reads the frame slot (§3) — so no locking is needed between
them. Two safety rules for Item 34:

- **Subscribers must be non-blocking and non-raising by contract**, and the loop
  still wraps each call in `try/except` so a subscriber bug can never kill
  capture or the socket. The aligner + slot-write satisfy "non-blocking" (pure,
  no I/O, no `await`).
- **The socket is `capture/`'s alone.** Subscribers receive strings; they never
  touch the websocket. `capture/` stays the one place the socket lives (RPP §2).

**Recording-to-disk is optional for overlay.** Decision: add `save: bool = True`
to `RecordingSession`; when `False`, `_run` skips the `open()`/`write()`/`flush()`
but still fans out to subscribers. This gives three compositions from one
controller: capture-only (today, no subscribers), **overlay-while-recording**
(`save=True` + a subscriber — the §4 superset behavior), and overlay-only
(`save=False` + a subscriber). Default stays `True` so you always get a free
capture unless a caller opts out.

---

## 2. Incremental parse placement

The batch parser (`model/replay._parse_lines`) scans a *whole* `text` in one
pass; live has no "whole file" — messages arrive one at a time and the `C;`
reference typically arrives **once at the start and never again**.

**Decision: a streaming `LiveAligner` class *inside* `model/replay.py`, beside the
batch parser — not a new module — reusing the existing transform and dataclasses.**
Rationale:

- It shares `TrackPoint` / `Frame`, `anchor_world_ft`, and the `m_to_ft`-offset /
  `emp`-anchor transform with the batch path. Reuse, not a second copy of the
  coordinate math, is an explicit Item 33/RPP §1b requirement (the offset-scaling
  bug must exist in exactly one place).
- It stays **pure**: no GUI, no network, no global state — same as the rest of
  `model/`. Testable headless by feeding it strings.

**Refactor to guarantee one copy of the grammar:** extract the per-line body of
`_parse_lines` into small shared helpers — e.g. `_parse_ref(line) -> (x, y) |
None` and `_parse_frame_entities(line) -> list[_RawEntity]` — that *both*
`_parse_lines` (batch) and `LiveAligner.feed` (streaming) call. The `F;`/`C;`/
timestamp grammar then lives in one place; the batch and streaming paths differ
only in *who holds the state* (a local scan vs. instance attributes).

**`LiveAligner` shape (handed to Item 33):**

```
class LiveAligner:
    def __init__(self, project, sensor_index=0, *, max_points_per_frame=…):
        # precompute anchor_ft = anchor_world_ft(project, sensor_index)
        # state: self._ref, self._ref_seen, self._t
    def feed(self, message: str, t: str | None = None) -> Frame | None:
        # split message into lines; update _ref (first C; wins) / _t;
        # on an F; line, align its entities via the shared transform and
        # return a Frame. Non-frame messages (C;, timestamp, GetCfg) -> None.
```

- **Timestamp source.** The recorded *file* has a wall-clock line the recorder
  prepends (`ts\n{message}\n`); the *live* websocket message does **not**. So
  `feed` takes an optional `t`: the GUI passes `datetime.now()`-stamped time (the
  timestamping moves to the caller, keeping `model/` pure and deterministic); the
  Item 33 equivalence test passes the file's recorded `t` so streamed and batch
  frames match on time too, not just coordinates.
- **One-time `C;`.** State persists across `feed` calls, so a stream that sends
  `C;` once at the top and only `F;` afterward stays correctly anchored — the
  streaming counterpart of the batch parser's "whole file scanned so a late `C;`
  still anchors."
- **Robustness (Item 33):** malformed/partial messages never raise (reuse the
  batch parser's skip-on-`ValueError` discipline); unknown line types return
  `None`; an `F;` arriving before any `C;` uses the documented `(0,0)` fallback
  (`ref_seen=False`), identical to the batch default.

---

## 3. Async → GUI push + backpressure

NiceGUI runs on asyncio (uvicorn); the capture task can emit frames faster than
the canvas should redraw, and a live feed never stops.

**Decision: a single shared "latest aligned frame" slot the capture side writes
and a fixed-cadence `ui.timer` reads — drop-to-latest.** Concretely:

- The §1 subscriber callback runs `LiveAligner.feed(message)` on **every** message
  (lossless, on the capture task) and, when it returns a `Frame`, overwrites a
  single slot: `v.live_frame = (frame, monotonic_now)`. No queue, no list — the
  slot just holds the most recent frame; older frames are harmlessly overwritten.
- A `ui.timer` at **Item 30's 10 fps cadence** reads `v.live_frame` and rewrites
  **only the marker layer** (reuse `replay_layer` + a `live_marker_svg()` built
  the same way as `replay_marker_svg()`). Socket rate is fully decoupled from
  redraw: between two ticks the slot may be written many times or not at all —
  the timer always renders whatever is current.
- **No backpressure can build up.** The lossy consumer is a single overwritten
  slot (O(1), bounded), and the lossless consumer (the aligner) is pure and
  runs inline in microseconds, so it can't stall the socket read. This is
  strictly simpler than a queue and cannot leak memory on a long feed.
- **Stale-frame expiry.** Because each rendered frame *replaces all markers*, a
  track that drops out of a frame disappears automatically. The remaining case is
  the **whole stream** stalling (no new frame): the last frame's markers would
  otherwise sit forever. Guard it in the timer — if `monotonic_now -
  slot_time > STALE_TIMEOUT` (e.g. ~2 s), clear the marker layer. That covers
  both dead markers and a silently dropped connection.

---

## 4. Live-vs-Record UX

**Decision: "Live" is a new read-only canvas *mode*, sibling to Replay (RPP §4's
mode model), that *shares* the Record panel's auth/host form and can optionally
record to disk at the same time (the superset behavior).** Reasoning:

- **Why a mode, not a checkbox in the Record dialog.** The overlay renders on the
  *canvas* (`replay_layer`), and Item 30 established the invariant "the marker
  layer is populated only in a read-only canvas mode" (`v.mode == "Replay"`).
  Live is that same kind of thing — a read-only marker overlay — so it belongs as
  a canvas mode, reusing the marker-layer + teardown machinery, not buried inside
  a modal dialog that sits *over* the canvas it's trying to draw on.
- **Why not overload Replay.** Replay is *file scrubbing*: a timeline, a scrubber
  bound to `frame index`, play/pause/speed over a fixed `list[Frame]`. Live has
  **no timeline and no scrubber** — it's a live tail with only connect / stop and
  a status readout. Folding them would make both muddier. They *share* the render
  layer and transform; they don't share transport.
- **Shared connection form.** Live reuses the Record panel's host/credentials
  form and `RecordingSession` (§1) for the connection — no second auth UI. Entering
  Live opens/uses that form to connect; the difference from Record is that Live
  also `subscribe()`s the aligner and drives the marker layer.
- **Coexistence with draw/edit:** exactly as Replay (RPP §4) — read-only, draw/
  edit tools inactive while in Live, markers on the separate layer, leaving Live
  restores the prior tool/overlay and stops the timer + connection.
- **Superset of Record:** because a `RecordingSession` with `save=True` both
  writes to disk *and* fans out (§1), Live mode can optionally keep the capture
  (a "record while overlaying" toggle) — and a finished Live capture hands to the
  Item 30 loader through the exact `load_replay_recording(preset_path=…)` seam the
  Record panel already uses.

---

## 5. Live guardrails

Carry RPP §6 and the Item 20 zoom-freeze lesson onto the live path:

- **Marker-per-frame cap** — reuse `LiveAligner`'s `max_points_per_frame`
  (the batch parser's backstop) so a pathological frame can't emit thousands of
  markers.
- **Stale-marker timeout** — the §3 `STALE_TIMEOUT`: clear the overlay when no
  frame arrives within the window (a track/stream that stops reporting fades
  rather than freezing on screen).
- **Fixed 10 fps cadence, marker-layer-only rewrite** — never re-render the
  static zone/centerline `svg()`; the timer is inactive off-Live. This is the
  direct Item 20 carry-over (the freeze came from re-rendering huge SVG on every
  change).
- **Connection/error surfacing** — `RecordingSession.status` already carries
  `error` / `connected`; Live's status line reads it (like the Record panel's
  `refresh_record_status`) and, on error/disconnect, stops the timer and clears
  markers. Reconnect is user-initiated (re-enter/reconnect) for the first cut;
  auto-reconnect is a deliberate non-goal here.
- **Bounded memory** — the live path keeps only the latest frame (§3), never a
  growing `list[Frame]`, so an all-day feed uses constant memory. (Optional
  disk recording via `save=True` is the same bounded append the recorder already
  does.)

---

## 6. Live status readout (Item 34's second half)

Item 34 also extends `RecordingStatus` with a small live readout the GUI polls:
**frames/sec**, **connection state** (already `connected`/`error`), and
**last-frame time**. Compute fps from a short rolling window or a
frame-count/elapsed delta in the session (cheap, no new deps). This drives both
the Record panel's existing status label and Live mode's status line, so "is data
actually flowing?" is answerable without watching the canvas.

---

## 7. What each downstream item inherits

| Item | Target | Inherits from this doc |
|---|---|---|
| **33** Streaming align engine | Fable | §2 `LiveAligner` **inside** `model/replay.py`, built on shared `_parse_ref`/`_parse_frame_entities` helpers (one copy of the grammar) and the existing `TrackPoint`/`Frame`/`anchor_world_ft` transform (**no** second copy of the coordinate math); `feed(message, t=None) -> Frame | None` holding `C;` ref + timestamp as state; §5 `max_points_per_frame` cap; robustness = the batch parser's skip-on-error discipline. **Correctness gate:** feed a recording's messages one-by-one and assert the streamed frames match the batch `Recording` **frame-for-frame** (same aligned coords) — re-checking RPP §7's y-sign / no-rotation open items on the incremental path. |
| **34** Recorder feed-tap + status | Sonnet | §1 `subscribe`/`unsubscribe` + synchronous fan-out in `_run`, `try/except`-guarded, subscribers non-blocking/non-raising by contract; `save: bool = True` to allow overlay-without-disk; §6 frames/sec + connection + last-frame-time on `RecordingStatus`. Don't otherwise change auth/socket/file behavior. pytest the fan-out with a fake message source (no real socket; nothing under `sites/`). |
| **35** Live mode + render | Opus | §4 read-only "Live" canvas mode sharing the Record panel's auth/`RecordingSession`; §3 single "latest aligned frame" slot written by the §1 subscriber (running the §2 aligner) and read by a fixed-cadence `ui.timer` that rewrites only the marker layer (reuse Item 30's `replay_layer` + `replay_point_to_canvas`); §5 guardrails (stale timeout, per-frame cap, error surfacing, timer inactive off-Live); optional `save=True` record-while-overlaying handing to the Item 30 loader. |

### Open items explicitly handed forward
- **y-sign / no-rotation, on live data.** RPP §7 flagged that no real recording
  survives on disk, so the batch engine (Item 29) proved alignment only against a
  *synthetic* recording + an equivalence test to `evo_replay.align`. The first
  **live** connection (Item 35) is the first time real EVO data flows end-to-end —
  it is the real confirmation of the y-down sign and the axis-aligned (no per-sensor
  `azimuth` rotation) assumption. If a live track is visibly mirrored or rotated
  against the map, the fix is a one-place sign/orientation change in the shared
  transform (which Item 33's equivalence test then re-pins), **not** a live-path
  hack.
- **Auto-reconnect** is out of scope for the first cut (§5) — user re-initiates.
- **Multi-host live overlay.** §1's per-session subscriber generalizes (one
  `LiveAligner` per host/sensor, each writing its own slot or a merged slot), but
  Item 35's minimum is **single-host live**, mirroring Item 31's single-host
  recording minimum. Multi-host live is a later extension, not this batch.
