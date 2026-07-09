# Record / Playback — Architecture & Coordinate Reconciliation

**ROADMAP Item 28 (Opus). Decision document — no feature code.** Every choice
here is inherited by Items 29 (playback engine), 30 (playback UI), and 31 (live
recording). Read this before starting any of them. Summary of what each
downstream item inherits is in §7.

Scope: bring the EVO record/replay capability (`../evo_recorder.py`,
`../evo_recorder_multi.py`, `../evo_replay.py`) *into* the designer as
first-class Record and Replay features, without violating the `model/`-is-pure
rule (see CLAUDE.md).

---

## 0. Headline finding — there is no coordinate-space conflict

The apparent "meters (evo_replay) vs. feet (designer)" gap is **not** two
irreconcilable frames. It is a **units conversion**, exactly as Item 28
hypothesized. Proof, run against the real `86_US95&SH8` site:

- `evo_replay.parse_xml_config` computes sensor-0 in map meters as
  `s0_m = (s0_px − Background_PosX) · MeterPerPixel`.
- The designer's `coords.normalize_origin` (applied by `load_iprj` to every
  project) subtracts `Background_PosX/PosY` from every coordinate, so the loaded
  `sensor[0].position` is *already* `(s0_px − bg_off)` in world pixels.
- Numerically: designer normalized `sensor[0]` = **(855.95, 313.82) px** ==
  evo_replay's `(1520.06 − 664.11, 927.70 − 613.88)`. Identical.

So both tools use **one frame**: origin = background top-left, y-down, no
rotation. evo_replay expresses it in *meters* (`px · MeterPerPixel`); the
designer expresses it in *world pixels*, and feet via `units.px_to_ft`. The only
work is a unit multiply + the right anchor. This is why the batch is "mostly
plumbing," as Item 28 called it.

---

## 1. Coordinate / units reconciliation

### 1a. units.py audit — verdict: correct, and *more accurate* than evo_replay

The owner flagged `model/units.py` as a possible latent bug. **It is not a
bug.** Audited against all 29 `sites/**/*.iprj` files:

| Site (representative) | stored `MeterPerPixel` | reference-pair implied | used | divergence |
|---|---|---|---|---|
| 86_US95&SH8 | 0.20 | 0.20467 | implied | 2.33% |
| Banks (native) | 0.08 | 0.07620 | implied | **4.75%** |
| ex27 | 0.22 | 0.21594 | implied | 1.85% |
| Banks (converter) | 0.25 | — (no pair) | stored | 0.00% |
| ex27bg2 (stale pair) | 0.22 | 0.06586 | **stored** | 0.00% |

`effective_meter_per_pixel` re-derives the scale from the full-precision
`MeterReference0/1 + ReferenceLength` pair and only falls back to the stored
(2-decimal-rounded) `MeterPerPixel` when the pair is stale/absent — and the one
stale case (ex27bg2) correctly rejects the pair. `px_to_ft → ft_to_px`
round-trips are exact. This confirms the existing 2026-07-02 decision-log entry;
the module works as designed.

**The consequence that matters:** `evo_replay` uses the *rounded* stored value
(0.20, 0.08, 0.22…), which is up to **4.75% off** the calibrated scale. If we
naively reused evo_replay's `MapConfig.scale` we would inherit that error and it
would grow with distance from the anchor. **Decision: playback reuses the loaded
`Project` + `units.effective_meter_per_pixel`, never a second regex parse of the
iprj or evo_replay's `parse_xml_config`.** Designer playback will therefore be
*more* accurate than the standalone evo_replay it descends from.

### 1b. The single transform: EVO frame → designer world-feet

The EVO stream reports track points and its `C;` reference line in **true
real-world meters**, in a frame axis-aligned with the map (evo_replay aligns by
pure translation and it works in practice; see the caveat handed to Item 29
below). Given a loaded `Project`, `bg = project.background`,
`emp = effective_meter_per_pixel(bg)`, a recording tagged with sensor index `n`,
its EVO reference `ref_m = (rx, ry)` (from the `C;` line), and a track point
`p_m = (x_m, y_m)` (EVO meters):

```
anchor_ft = ( px_to_ft(sensor[n].position_x, emp),
              px_to_ft(sensor[n].position_y, emp) )      # pixel → feet: uses emp

world_ft  = ( anchor_ft.x + m_to_ft(x_m − rx),
              anchor_ft.y + m_to_ft(y_m − ry) )          # metric offset → feet: NO emp
```

**Correctness pivot (the bug-prone line for Item 29):** the offset `(p_m − ref_m)`
is already in *true meters*, so it converts to feet with `m_to_ft` **alone** — it
must NOT be scaled by `emp`/`MeterPerPixel`. Only the *pixel* anchor
(`sensor[n].position`) passes through `emp`. This is the same structure as
evo_replay's `X = X_raw + (s0_m − evo_s0)`, but re-expressed for a px-anchored,
feet-canonical world instead of evo_replay's all-meters space. Scaling the offset
by mpp would reintroduce (and amplify with distance) the very 2% error §1a
avoids.

The engine emits **world-feet** (the canonical model unit per CLAUDE.md). The
GUI then renders markers through the *same* feet → world-px → image-px → viewport
path it already uses for zones/centerlines (`units.ft_to_px` +
`viewport.image_to_viewport`). No new coordinate path is introduced in the GUI.

### 1c. Alignment anchor: per-sensor, not global sensor-0

**Decision: per-sensor anchor.** Each EVO recording is a single-host stream
(`evo_recorder.py` = one host; `evo_recorder_multi.py` = one file *per* host), so
a stream's tracks and `C;` reference belong to exactly one sensor. A recording is
tagged with its owning sensor index `n` and aligns to `sensor[n]` on both sides
of the transform. For a single-sensor site `n = 0`, reducing to evo_replay's
current behavior. For the 2-file / multi-sensor split, each recording anchors to
its own sensor; playing several overlays them, each on its own anchor. This makes
the transform per-recording (keyed by sensor index), never a hard-wired
sensor-0.

---

## 2. Module placement — keep `model/` pure

Three layers, matching the "model pure / gui thin shell" rule and the fact that
*live capture is inherently side-effectful* (websocket, asyncio, credentials) and
so cannot sit in `model/`:

| Concern | Home | Why |
|---|---|---|
| Parse an EVO recording + align to world-feet | **`model/replay.py`** (new, pure) | No GUI, no global state, no network. Takes a `Project` + recording path/text, returns a plain structure (§3). Headless-pytestable. |
| Live websocket capture (auth, stream → raw file) | **`capture/recorder.py`** (new package) | Side-effectful: asyncio + websockets + credentials. Belongs in neither pure `model/` nor render-only `gui/`. Isolating it here lets the socket/credential lifecycle be mocked/tested apart from NiceGUI. |
| Replay mode, timeline, marker overlay, Record panel | **`gui/`** | Thin shell over the two above. |

**Decision: new sibling package `capture/`** (peer of `model/` and `gui/`) rather
than folding the recorder into `gui/`. The recorder is I/O against an external
device, not view code; a dedicated package keeps the async/websocket lifecycle
out of both the pure model and the render layer. `model/replay.py` reading a
recording file off disk is fine — it is pure parsing, the same as `iprj_io`
reading an `.iprj`.

---

## 3. Data-structure seam — plain frame-indexed structure, no pandas

`evo_replay.load_replay` returns a pandas `DataFrame`; `model/` has **zero**
pandas/numpy dependency (grep-confirmed) and its whole test suite is plain
dataclass assertions.

**Decision: a plain, frame-indexed dataclass structure in `model/replay.py` — no
pandas in the model layer.** Shape:

```
@dataclass TrackPoint:  oid:int  sensor:int  cls:int|None  x_ft:float  y_ft:float
                        heading:float|None  x_raw_m:float  y_raw_m:float   # raw kept for hover/debug
@dataclass Frame:       t:str (timestamp)   points:list[TrackPoint]
@dataclass Recording:   sensor_index:int    ref_m:tuple[float,float]    frames:list[Frame]
                        # frames[i] is frame i — O(1) scrub by index
```

Rationale:
- **Minimal dependency surface.** pandas is a heavy dependency to bolt onto a
  pure-geometry module whose entire value is being headless and light.
- **Testability.** A coordinate-alignment assertion (Item 29) is a one-liner on
  a `TrackPoint`; on a DataFrame it is groupby/iloc ceremony.
- **The UI needs random access by frame index** (timeline scrubber, `ui.timer`
  tick → jump to frame `i`). A `list[Frame]` gives that directly; a DataFrame
  needs a per-tick `groupby`/filter.

We do **not** share the DataFrame with evo_replay — we re-implement the parse in
pure form (`parse_evo_data` is ~50 lines). `evo_replay.py` keeps its pandas path
for its standalone HTML/MP4 rendering; the two coexist. *Optional* convenience:
`Recording.to_dataframe()` that imports pandas lazily *inside the method* for
notebook use, so the core module stays import-clean.

---

## 4. Playback ↔ draw/edit interaction

**Decision: a new read-only "Replay" mode, no editing during playback, markers on
a separate SVG layer.**

- Replay is a mode entered like a tool (reuse the existing `_enter_mode`
  teardown, so entering it drops the ruler/active draw tool). While in Replay,
  draw/edit tools are inactive.
- **Read-only:** editing is disabled during playback. This is the simplest safe
  choice and removes any question of markers corrupting draw/edit overlay state
  or of edits racing the timer. Loading a recording never mutates the `Project`.
- **Separate marker layer:** the animated markers are their own SVG group,
  rebuilt as a string each `ui.timer` tick and written only to that layer. The
  existing zone/centerline/label overlay renders beneath, static and untouched.
  Markers use the same feet → image-px → viewport transform as everything else,
  so they register against the background at any zoom/pan.
- Leaving Replay restores the prior tool and overlay.

---

## 5. Recording model

**Decision: a Record panel that drives the existing `evo_recorder` logic as an
asyncio task on NiceGUI's own loop; recordings written next to the loaded
project; credentials entered/held locally, never committed.**

- **Host / credentials:** a form (host IP, username, password), seeded from a
  small local, gitignored config defaulting to the `evo_recorder_multi` host list
  (`evo`/`root` device defaults). Do **not** commit new credentials; the device
  defaults already live in the existing scripts, but the in-app config file stays
  out of git.
- **File placement:** write recordings under the active project's site directory
  in a `recordings/` subfolder (e.g. `sites/<site>/recordings/`), filename
  `{host_underscored}_EVO_{epoch}.txt` to match `evo_recorder`. This follows the
  `sites/` convention while respecting the fixture rule — the read-only rule is
  about the `.iprj` fixtures; new recordings are new data. **Tests must never
  write under `sites/`:** any recording produced by a test goes to `tests/out/`
  or the scratchpad.
- **Lifecycle inside NiceGUI's event loop:** NiceGUI runs on asyncio (uvicorn).
  The recorder is already `async`/`websockets`, so **start** = `asyncio.create_task(...)`
  on the *running* loop — **never** `asyncio.run` (which would collide with the
  server loop). **Stop** = cancel the task and close the socket cleanly. Live
  status (frames captured) is shared state updated by the task and surfaced via a
  `ui.timer`/label. Guard against double-start.
- **Multi-host:** `evo_recorder_multi` already `gather`s N per-host tasks; map
  each host → sensor index at record time so playback (§1c) can anchor each
  recording. Item 28 scopes **single-host as the minimum** for Item 31;
  multi-host is optional there.
- **Safety:** all I/O is awaited (never blocks the loop); flush-on-write is
  retained; the Windows `SetThreadExecutionState` prevent-sleep hack stays out of
  the server path (desktop-only concern).

---

## 6. Performance guardrails

Carry forward the Item 20 large-file zoom-freeze lesson (the freeze came from
re-rendering huge SVG on every viewport change):

- **Precompute at load.** Parse + align *all* frames once into the `list[Frame]`
  structure; each `ui.timer` tick is then O(markers in that frame) — no re-parse,
  no re-align, no re-transform of static geometry.
- **Update only the marker layer** per tick (a small SVG string), never the full
  zone/centerline overlay.
- **Downsample + frame-cap at load**, reusing evo_replay's knobs
  (`downsample_rate`, `max_frames`) with sane defaults so a long recording can't
  animate 50k frames.
- **Fixed animation cadence** (e.g. a 10 fps `ui.timer`) decoupled from frame
  count; the scrubber jumps by index.
- **Cap markers per frame** as a backstop against pathological frames.

---

## 7. What each downstream item inherits

| Item | Target | Inherits from this doc |
|---|---|---|
| **29** Playback engine | Fable | §1b transform (emit **world-feet**, `m_to_ft` on the offset, `emp` only on the anchor); §1c per-sensor anchor via loaded `Project`; §3 plain frame-indexed `Recording`/`Frame`/`TrackPoint`, **no pandas**; §2 lives in pure `model/replay.py`; §6 downsample/cap. **Must verify** against a real recording: the y-down sign and the axis-aligned (no-rotation) assumption behind evo_replay's pure translation, and that `C;` reference == sensor anchor — with a coordinate-alignment pytest assertion (a known point lands where expected). |
| **30** Playback UI | Opus | §4 read-only Replay mode + separate marker layer via `ui.timer`, reusing the existing feet→viewport transform; §6 guardrails; consumes the Item 29 `Recording`. |
| **31** Live recording | Sonnet | §5 Record panel, `asyncio.create_task` on NiceGUI's loop, `sites/<site>/recordings/` placement, local (uncommitted) credentials, single-host minimum; hands the finished file to the Item 30 loader. §2 lives in the new `capture/` package. |

### Open items explicitly handed to Item 29 (not resolved here without a recording)
- Confirm the EVO frame is axis-aligned with the map (no per-sensor `azimuth`
  rotation applied to the stream) — evo_replay assumes pure translation and works
  in practice, but Item 29 owns proving it on a real recording, since it is the
  most likely place a sign/orientation bug hides.
- Confirm y-down orientation matches (EVO `y` grows the same direction as world
  px) and pick the sign in one place.

### Note for maintainers of units.py
The absolute 0.005 tolerance in `effective_meter_per_pixel` is scale-dependent
(≈2.5% at mpp 0.2, ≈6% at 0.08). It classifies every current site correctly, so
this is **not** an action item — just a known smell to revisit only if a future
site's genuine-but-slightly-off pair ever lands on the wrong side of it.
