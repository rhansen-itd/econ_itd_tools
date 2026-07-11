# Track Stitching / Fusion — Architecture & Prior-Art Post-Mortem

**ROADMAP Item 41 (Opus). Decision document — no feature code.** Every choice
here is inherited by Item 42 (fusion engine in `model/`) and Item 43 (fusion
overlay wiring). Read this before starting either. What each downstream item
inherits is summarized in §7.

Scope: turn the raw aligned track stream into **one trajectory per real
vehicle** — two distinct stitching problems the owner named, both in scope:

- **Within-sensor stitching** — an object tracked into e.g. the intersection
  that *stops, drops, and re-appears as a new object id* when it moves again
  must be re-joined into one continuous track (temporal-gap + spatial-
  plausibility bridging).
- **Cross-sensor fusion** — the same real vehicle seen by two sensors in their
  overlap region becomes **one** fused trajectory (dedup in overlap + continuous
  id across the sensor-to-sensor handoff).

Prior fusion attempts (`../fusion_visualizer.py` ~2.6k lines,
`../fusion_strict_logic.html`) failed under non-Opus models, so the owner asked
Opus to **review the prior art *and* the raw data first**, then decide salvage-
vs-clean-room before Fable builds the engine (Item 42). This doc does that.

---

## 0. Headline findings

Three findings drive every decision below.

1. **The prior art failed structurally, not in tuning.** `fusion_visualizer.py`
   conflated *four* different jobs in one 2.6k-line script (inter-sensor bias
   correction, within-sensor stitching, cross-sensor fusion, and learned
   path-template classification), with **no tests and no acceptance gate**, on a
   heavy dependency stack (`pandas`, `numpy`, `scipy.Rbf`, `shapely`, `cv2`,
   `plotly`) that `model/` forbids. It is a **clean-room rebuild**, not a
   salvage — but a handful of its *parameters and sub-heuristics* are worth
   lifting (§1).

2. **Its central mechanism is now obsolete.** Cross-sensor matching in the prior
   art depended on an **RBF spatial warp** (`train_spatial_bias_model` /
   `apply_spatial_correction`) trained on the *same* noisy vehicle pairs it was
   then trying to fuse — a circular, unstable dependency that papered over
   inter-sensor disagreement. **Items 38–40 now remove that disagreement
   cleanly and separately** with the rigid per-sensor calibration
   (`model/calibration.py`). So fusion **depends on a calibrated overlay and
   drops the RBF entirely** (§1, §4). This is the single biggest reason a fresh
   attempt should succeed where the prior one thrashed.

3. **Real recordings now exist as fixtures — the missing correctness gate is
   available.** `tests/fixtures/10_37_2_86_EVO_1770311735.txt` (site
   `86_US95&SH8`, **3485 `F;` frames, two sensors** `oid%10 ∈ {0,1}`, ~6 min at
   ~0.1 s) and `tests/fixtures/10_37_23_201_EVO_1783582697.txt` (Banks, 560
   lines) are real captures. The Item 29/33 caveat that "no real EVO recording
   survives on disk" is **stale** — Item 42 gets a real-recording acceptance
   gate, the exact thing the prior attempts lacked (§6).

---

## 1. Prior-art post-mortem — salvage vs. clean-room

Read of `fusion_visualizer.py` (the `.html` files are its ~11 MB rendered
plotly output, not additional logic — nothing to salvage there).

### What it did

A single linear pipeline: `parse_and_align_data` (regex re-parse of the iprj +
raw translation) → `stitch_same_sensor_tracks` (velocity-aware within-sensor
bridging) → `train_spatial_bias_model` + `apply_spatial_correction` (RBF warp to
force sensors to agree) → `classify_tracks_by_gates` (label each track
`valid_internal` / `transition` / `fragment` from hand-drawn `gates.json`
crossings) → `fuse_tracks_with_gates` (cross-sensor merge of `transition`
tracks) → `build_path_templates` / `stitch_with_path_templates` (learn and reuse
per-movement trajectory templates, persisted to `path_templates.json` /
`spatial_models.json`) → plotly animation.

### Why it failed (root causes, not symptoms)

| # | Failure | Consequence |
|---|---|---|
| F1 | **RBF-warp calibration coupled to fusion** — sensor agreement was *learned from the same noisy pairs being fused*, per-run, with mode flags (`use_only`/`augment`/`new`/`replace`) and JSON persistence. | Circular and non-deterministic; drifted across runs; the thing most likely to "work once then break." Superseded by Items 38–40. |
| F2 | **Gate-dependent classification** — the whole fuse/discard decision hinged on hand-drawn `gates.json` lines per site and `oid%10 == gate.sensor` bookkeeping. | A brittle external artifact that must be authored + maintained per site; wrong/missing gates silently mis-class every track. The wrong primitive. |
| F3 | **Fragile time handling** — `HH:MM:SS.mmm` parsed to float seconds and matched by **exact equality** (`df['Time'] == t`, `np.intersect1d` on raw time values). | Any frame-time jitter breaks overlap detection; fusion depended on it. |
| F4 | **Learned path templates as core, not option** — a stateful template store (resample-to-length, weighted-average points, confidence tiers) was load-bearing for stitching orphans. | Large hidden state surface, drift, and tuning with no ground truth to validate against. |
| F5 | **No acceptance gate, forbidden deps, monolith.** No tests; `pandas`/`scipy`/`shapely`/`cv2`; 2.6k lines mixing model + render. | Impossible to certify a change; can't live in `model/` at all. |

### Verdict: clean-room in `model/`, lifting parameters only

**Decision: clean-room rebuild in a new pure `model/fusion.py`.** Salvage the
*ideas and constants*, not the code:

- **Salvage (as tuned starting values, converted to feet):** velocity-aware
  stitch windows (moving vs. stopped/slow), the forward directional cone
  (±60°), the isolation idea, and class-compatibility gating (don't merge
  pedestrian↔motor-vehicle). Prior-art values: `MAX_TIME_GAP` 5 s moving / 30 s
  stopped; `MAX_SPATIAL_GAP` 30 m (~98 ft) moving / 20 m (~66 ft) stopped;
  `MIN_VELOCITY` 1 m/s (~3.3 ft/s); cross-sensor `FINE_MATCH_DIST` 5 m (~16 ft),
  min 3 overlapping samples.
- **Drop entirely:** the RBF spatial model (→ Items 38–40 calibration), the
  `gates.json` dependency (fusion works off geometry + time directly), the
  learned path-template store (not in the first cut; a documented future
  upgrade), all `pandas`/`scipy`/`shapely`/`cv2` usage, and the per-run JSON
  persistence.

---

## 2. Data model & seam — a pure transform over aligned `Frame`s

**Decision: a new pure `model/fusion.py`, a transform from the aligned frame
stream to fused track ids. No new coordinate math, no pandas, no network.**

Fusion sits **after** alignment, in canonical **world feet**:

```
EVO frame (m) → calibration Cᵢ → group placement G → world feet  →  FUSION  → render
                └────────── model/replay.py + model/calibration.py ──┘   (this doc)
```

It consumes the exact structures Item 29 already produces — no re-parse, no
second copy of the transform:

- Input: an aligned `list[Frame]` (from `Recording.frames`, or several
  recordings merged onto one timeline — see §4c). Each `TrackPoint` already
  carries `oid`, `sensor` (`oid%10`), `cls`, `x_ft`, `y_ft`, `heading`, and its
  `Frame` carries the wall-clock `t`.
- **Numeric time seam (fixes F3):** `Frame.t` is a string `"HH:MM:SS.mmm"`.
  Fusion parses it once into seconds via a small pure helper and works in
  tolerant time *windows*, never exact-equality matching. (Frame **index** is
  not a substitute — downsampling/frame-cap changes indices, so the wall-clock
  string is the source of truth for `dt`.)
- Internal working unit: fusion first folds the frame stream into per-source
  **raw tracks** keyed by `(sensor, oid)` — an ordered
  `RawTrack(points=[(t_s, x_ft, y_ft, heading, cls), …])`. Stitching and fusion
  then reason over whole tracks (endpoints, overlap windows), which is where the
  prior art's per-frame `groupby` churn came from.
- Output: a pure result the render layer can consume without re-running the
  engine —
  ```
  @dataclass FusedTrack:  fused_id:int   members:tuple[(sensor,oid), …]
                          points:tuple[FusedPoint, …]   # time-ordered, deduped
                          kind: "single" | "stitched" | "fused"
  @dataclass FusionResult: tracks:tuple[FusedTrack, …]
                           id_of: Mapping[(sensor,oid), int]   # raw → fused id
  ```
  `id_of` lets Item 43 recolour existing raw markers by fused id **without**
  restructuring its render loop; `tracks` gives the deduped fused polylines for
  the fused view.

Everything stays frozen dataclasses + plain Python, pytestable headless, exactly
like `replay.py`/`zonefit.py`/`calibration.py`.

---

## 3. Within-sensor gap-bridging policy (stop / drop / resume)

Operates per sensor, on raw tracks, **needs no calibration** (a single sensor is
internally consistent). For an ending track A (last point) and a candidate
successor B (first point) of the **same** sensor:

- **Gate on time:** `0 < t_start(B) − t_end(A) ≤ T_max`, where `T_max` is
  velocity-selected: use the **stopped** window (≈30 s) when A's end velocity is
  below `MIN_VELOCITY`, the **moving** window (≈5 s) otherwise. This is what
  captures the *stop/drop/resume in the intersection* case — a stopped vehicle
  legitimately disappears for many seconds.
- **Gate on space:** Euclidean gap ≤ `D_max` (velocity-selected, ~66 ft stopped
  / ~98 ft moving, in feet).
- **Kinematic plausibility (moving only):** B's start must lie within a forward
  **±60° cone** of A's end heading *and* within reach of A's extrapolated
  velocity over the gap. Stopped vehicles skip the cone (they may resume in any
  direction) and use a circular search.
- **Class compatibility:** never bridge across the non-motorized/motorized
  divide (`cls` 10/15/20 vs. ≥25), lifted from the prior art.

**Refuse-don't-guess (the load-bearing discipline, matching zonefit/
calibration):** score candidates by `time_gap + spatial_gap`; bridge only the
unique best. **If two successors are both plausible (ambiguous), leave the track
split rather than merge** — a wrong merge fabricates a trajectory that never
happened, which is worse for downstream counting than an honest fragment. Cap
one bridge per endpoint; a chain (A→B→C) forms by transitive re-runs, each step
individually gated.

---

## 4. Cross-sensor association policy (overlap dedup + handoff)

Operates across sensors, on raw tracks, **assumes a calibrated overlay** (§4b).

### 4a. Matching

Two tracks from **different** sensors are the same vehicle when they **coincide
in time and space**: temporal overlap of ≥ `MIN_OVERLAP` samples (≈3) with
**mean separation over the overlap < `D_fine`** (≈16 ft, tightened *because*
calibration has removed the systematic inter-sensor offset). Match greedily by
best (smallest mean-distance, longest-overlap) pair; each raw track joins at most
one cross-sensor partner per pass, transitive chains via re-runs. Class
compatibility gates here too.

- **Dedup in overlap:** where both sensors report the vehicle, collapse to one
  fused point (blend by overlap fraction, as the prior art did, or prefer the
  higher-quality sensor — Item 42 picks; blend is the safe default).
- **Handoff continuity:** outside the overlap, take whichever sensor has the
  point, so the fused id is continuous from entry (sensor A) through overlap to
  exit (sensor B).

### 4b. Dependence on calibration — **yes, and graceful without**

**Decision: cross-sensor fusion depends on the Items 38–40 calibrated overlay.**
That batch exists precisely to make the two sensors agree about where a vehicle
is; with it, "same vehicle" reduces to a tight spatial coincidence (F1 gone).
Degradation path when a project is *uncalibrated* (no vehicle-pair calibration
run, no usable `Z;` fit): widen `D_fine`, and **flag the result as
low-confidence** rather than silently merging on a loose threshold. Within-sensor
stitching (§3) is unaffected and always runs.

### 4c. Multi-source input

A single EVO stream already carries multiple sensors (the 86 fixture has
`oid%10 ∈ {0,1}`), so fusion reads `point.sensor` within one aligned frame and
needs no special multi-file handling in the common case. For the multi-file /
one-recording-per-host split (Item 9), the **caller** merges the per-host
recordings' frames onto a common timeline before calling fusion; fusion stays
source-agnostic (it only sees `(sensor, oid)` keys and world-feet points).

---

## 5. Batch vs. streaming

**Decision: batch / replay-first. Item 42 builds the batch engine only; the live
path shows raw (unfused) markers for now.**

Fusion is inherently whole-track: a within-sensor bridge needs a track's end
*and* a later track's start; cross-sensor fusion needs a full overlap window. A
streaming stitcher must carry open-track state and commit merges under bounded
look-back — materially harder and exactly the kind of all-at-once ambition that
sank the prior attempt. Keeping the first cut batch-only makes the correctness
gate (§6) tractable.

`model/fusion.py` will therefore expose a `fuse(frames, *, calibrated: bool)`
over a complete `list[Frame]`. A streaming variant (state carried across
`LiveAligner.feed` calls, reusing the batch scoring — no second copy) is a
**documented future upgrade**, not this batch. Item 43 accordingly wires the
raw↔fused toggle on **replay**; **live stays raw**.

---

## 6. Success criteria & test strategy (the missing gate)

The prior art had none; this is the decision that most changes the outcome.

**Decision: a labeled acceptance set on the real `86_US95&SH8` fixture, plus
deterministic synthetic adversarial cases. Item 42 does not pass until both
hold.**

- **Ground-truth label format** — a small fixture (`tests/fixtures/…json` or a
  py literal) that Item 41 seeds and Item 42 extends, mapping intended real
  vehicles to their raw ids:
  ```
  [ {"expect": "fused",    "members": [[0, 715220], [1, 420461]]},   # crosses the S0↔S1 overlap → 1 track
    {"expect": "stitched", "members": [[0, 714680], [0, 714970]]},   # stops in intersection, resumes → 1 track
    … ]
  ```
  Members are read off the replay/align overlay by eye (the overlay is exactly
  the tool for this). Keep the set **small but real** (a handful of unambiguous
  trajectories) — a few certain labels beat many shaky ones.
- **Positive gate:** each labeled group fuses into **exactly one** `FusedTrack`
  whose members match; the labeled stop/drop/resume case stitches into one.
- **Adversarial (don't-merge) gate — deterministic, no eyeballing:** hand-built
  synthetic tracks that are *close but distinct* — two vehicles crossing the same
  point at different times; opposing headings through one location; a
  pedestrian beside a car — must **stay separate**. These pin the refuse-don't-
  guess behavior and never regress on real-data noise.
- **Calibration sensitivity:** assert fusion **improves** with the calibrated
  overlay and **degrades gracefully / never raises** without it (§4b), using the
  real recording with and without a calibration applied.
- Read-only fixtures under `sites/**` / `tests/fixtures`; any generated output
  to `tests/out/` or scratchpad (CLAUDE.md testing rule).

---

## 7. What each downstream item inherits

| Item | Target | Inherits from this doc |
|---|---|---|
| **42** Fusion engine | Fable | §1 clean-room in pure `model/fusion.py` (no pandas/scipy/shapely/gates.json/RBF/path-templates; lift only the tuned constants); §2 transform over aligned `Frame`s → `FusionResult`/`id_of`, parse `t`→seconds, work in world-feet whole-track form; §3 within-sensor bridging with velocity-selected windows + cone + refuse-on-ambiguity; §4 cross-sensor overlap dedup + handoff, **assumes calibration**, graceful+flagged without; §5 **batch only**; §6 labeled real-fixture acceptance + synthetic don't-merge gate (must pass to land). |
| **43** Fusion overlay wiring | Opus | §2 `id_of` recolours existing raw markers by fused id (reuse Item 30/35 marker-layer-only rewrite — no static-SVG re-render); a raw↔fused toggle; §5 fused view on **replay** (live stays raw unless a streaming variant was built). |

### Open items handed to Item 42 (not resolved here without building it)

- **Final parameter tuning** against the real recording — the §1 values are
  starting points from a *different* (raw-translation, RBF) pipeline; re-tune on
  the calibrated world-feet stream and pin the chosen values with the §6 gate.
- **Overlap-region point policy** — blend by overlap fraction (prior-art
  default, safe) vs. prefer-higher-quality-sensor. Item 42 picks against the
  labeled set.
- **Chain-stitch ordering** — confirm transitive A→B→C bridging via re-runs is
  stable and order-independent on the real data.
