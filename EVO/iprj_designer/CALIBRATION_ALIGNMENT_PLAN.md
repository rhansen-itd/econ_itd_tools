# Sensor Calibration & Interactive Alignment — Architecture

**ROADMAP Item 38 (Opus). Decision document — no feature code.** The sibling of
[RECORD_PLAYBACK_PLAN.md](RECORD_PLAYBACK_PLAN.md) (RPP) and
[LIVE_OVERLAY_PLAN.md](LIVE_OVERLAY_PLAN.md) (LOP) for this batch. Every choice
here is inherited by Item 39 (the pure transform + N-sensor solver, Fable) and
Item 40 (interactive alignment mode + commit, Opus). Summary of what each
downstream item inherits is in §8.

Scope: unify **vehicle-pair calibration** (make the sensors agree with each
other) and the **move/rotate-to-align gesture** (seat the agreeing cluster onto
the background) as two *composed* transforms layered on top of the existing
EVO→world-feet pipeline, without violating the `model/`-is-pure rule (CLAUDE.md).

---

## 0. Headline finding — two transforms, different in kind, composed in order

The load-bearing distinction (owner, 2026-07-09) that drives every decision
below: **these are two different jobs, not two ways of authoring one artifact.**

1. **Calibration — relational, background-blind, per-sensor.** Uses vehicle
   tracks to make the sensors *agree with each other* about where a given
   vehicle is. Never references zones/background. Output = a locked set of
   per-sensor rigid corrections; afterward the sensors behave as **one
   internally-consistent rigid body**.
2. **Group placement — visual, background-referenced, one transform.** Seats
   that now-locked cluster onto the map so the tracks sit over the zones where
   they belong. Holds the inter-sensor relationship *fixed* — a drag repositions
   the whole group, never one sensor relative to another.

They differ **in kind**, and this is the fact the whole design protects:

| | Group placement (`Z;` zones) | Calibration (vehicle pairs) |
|---|---|---|
| Source | configured zone geometry (`Z;` GetCfg) | isolated vehicle detections |
| Nature | **exact, one-way math derivation** — vendor generated one side from the other; `zonefit` recovers it to float precision | **noisy radar approximations** — a *statistical* fit over many isolated pairs, needs volume + isolation gates |
| Scope | **one global** similarity over all sensors pooled | **per-sensor**, relative between sensors |
| Fixes | where the whole frame sits on the map | inter-sensor disagreement from independent eyeballed placement |
| Committable? | reproducible every load from `Z;` (nothing to persist) | **writes back** into per-sensor iprj azimuth/position |

Why the composition is forced: calibration alone **can't** place onto the
background (it has no notion of where the background is); a group drag alone
**can't** fix inter-sensor disagreement (a rigid move preserves relative error).
So the pipeline composes them, in this order:

```
EVO frame (m) → per-sensor calibration Cᵢ → group placement G → world-feet → viewport
              └── sensors agree ──┘        └─ cluster seated on map ─┘
```

**The reduction that guarantees zero regression:** when there are no vehicle
pairs, every `Cᵢ = identity`, so `G` is fit on the *same* zone centroids it uses
today and the whole pipeline collapses to **exactly** the current `zonefit`
behavior (or the translation fallback when there's no `Z;`). Calibration is a
strict *superset* layered on top; a site with no new vehicle data renders
byte-for-byte as it does now.

---

## 1. The two-transform representation + compose order

**Decision: one pure `AlignmentTransform` in `model/calibration.py` that holds
both layers and is threaded through `_align_frame` exactly where `zone_fit` is
threaded today.** Shape (handed to Item 39):

```python
@dataclass(frozen=True)
class RigidDelta:            # one sensor's calibration correction, EVO meters
    r: complex              # unit-modulus rotation (|r| == 1; no scale — see §2)
    d: complex              # translation, EVO meters
    def apply_m(self, x_m, y_m) -> tuple[float, float]: ...   # r*p + d, in meters

@dataclass(frozen=True)
class AlignmentTransform:
    calib: dict[int, RigidDelta]      # keyed by sensor (oid % 10); missing = identity
    placement: ZoneFit | Placement    # group G: the Z; similarity, or a manual/translation Placement
    def apply(self, sensor, x_m, y_m) -> tuple[float, float]:
        p = self.calib.get(sensor, IDENTITY).apply_m(x_m, y_m)   # 1) per-sensor, EVO meters
        return self.placement.apply_m(*p)                        # 2) group → world feet
```

- **Calibration is applied in EVO-meter space**, per-sensor, *before* the group
  placement. Rationale: the stream's points arrive in EVO meters already tagged
  by sensor (`oid % 10`); applying the per-sensor correction there is the
  natural insertion point and leaves a *single* downstream group transform. A
  rigid correction is scale-free, so meters-vs-feet is immaterial to it —
  putting it in meter space keeps it next to the raw data and keeps `G` as the
  one place the meter→feet unit multiply lives (reusing `zonefit`'s `m_to_ft`).
- **Group placement is world-feet output**, unchanged: `G` is the existing
  `ZoneFit.apply_m` (EVO-meters → world-feet similarity) when `Z;` exists, or a
  `Placement` (translation seed + manual override, §3) when it doesn't. The GUI
  render path downstream (`replay_point_to_canvas` → `world_to_canvas`) is
  untouched — markers still come out of the model in world feet.
- **One layer, both paths.** `_align_frame` today takes an optional `zone_fit`;
  it instead takes an optional `AlignmentTransform` (whose `.placement` *is* the
  zonefit), so **both** `parse_recording` (batch/Replay) and `LiveAligner`
  (streaming/Live) inherit calibration for free — the same single-copy-of-the-
  transform discipline RPP §1b / LOP §2 already enforce. `_align_frame`'s
  `to_world` gains the point's `sensor` argument (it already has the `oid`).
- **Compose consistency (the seam with zonefit).** `G` must be fit on the
  *calibrated* frame so the two layers compose cleanly. Concretely: compute
  `Cᵢ` first (background-blind, §2), push each zone centroid through its
  sensor's `Cᵢ`, then run `zonefit`'s existing least-squares over the calibrated
  centroids. There is no circularity — calibration reads only vehicles, never
  zones. When every `Cᵢ = identity`, the calibrated centroids equal the raw
  centroids and `G` is *bit-identical* to today's fit (the §0 reduction). Item
  39 reuses `zonefit`'s LS with pre-transformed centroids — **not** a second
  copy of the similarity math.

---

## 2. Relational calibration solver seam (the Fable core, Item 39)

Generalize `EVO/sensor_calibration.py`'s S1→S0 rigid fit to **N sensors** and a
joint, background-blind "make all sensors agree" solve. Two hard sub-decisions,
plus a non-negotiable dependency rule.

### 2a. Purity — re-implement, do NOT port
`EVO/sensor_calibration.py` uses `scipy.optimize.minimize` + `pandas` + `numpy`.
**None of the three is a `model/` dependency, and none may become one** (RPP §3;
grep-confirmed zero pandas/numpy/scipy in `model/`). The rigid 2D fit has a
**closed form** and needs none of them:

> The calibration solve is the **rigid sibling of `zonefit`'s similarity
> solve** — the identical pure-Python complex-number least-squares, with the
> single change that the fitted multiplier is normalized to unit modulus
> (`a / abs(a)`) so it is a pure rotation with **no scale**. Sensors are the
> same physical scale; only their eyeballed *position + azimuth* are wrong, so
> calibration is rigid (rotate + translate), never a similarity.

This is a strong reuse story and the reason the solver belongs beside `zonefit`:
one complex-LS kernel, two callers (similarity for zones, rigid for vehicles).
Powell/scipy is replaced by the exact closed form; results are more accurate and
`model/` stays dependency-light and headless-testable.

### 2b. Reference vs. joint solve
**Decision: reference-sensor-anchored pairwise for the first cut, with the joint
multi-pair least-squares documented as the upgrade.**
- Fix the reference sensor (index 0, the conventional primary host) to
  `C₀ = identity` — this *is* the gauge fix that stops the whole group drifting.
- For each non-reference sensor `i`, collect isolated same-vehicle pairs
  (sensor `i` detection ↔ reference detection of the same vehicle in the same
  frame) and solve the rigid `Cᵢ` that best maps `i`'s points onto the
  reference's (the complex-LS kernel, §2a).
- **Upgrade path (note for Item 39, not required for the first cut):** when the
  pairwise overlap graph is disconnected or weak — sensor 2 overlaps sensor 1
  but neither overlaps the reference — a *joint* least-squares over all
  simultaneous pairwise disagreements (still with `C₀ = identity` as the gauge)
  is more robust. Ship reference-anchored; leave the joint solve as a scoped
  extension behind the same `AlignmentTransform` output.

### 2c. Pairing / isolation gates
Reuse `sensor_calibration.py`'s proven gates, generalized per sensor:
- **Isolation** (`ISOLATION_RADIUS`, ~15 m): a detection counts only if no other
  detection *from the same sensor* is within the radius — kills ambiguous
  matches in dense frames.
- **Coarse match** (`COARSE_MATCH_DIST`, ~10 m): pair a sensor-`i` detection to
  the nearest reference detection within the distance; require the reference
  detection to be isolated too.
- **Volume** (`MIN_PAIRS`, ~50): below it, `Cᵢ` is untrustworthy → that sensor
  stays uncalibrated and **flagged**, not silently fit to noise (§7).

These live in `model/calibration.py` as pure functions over the aligned `Frame`
stream (Item 29's structure), so the pair-finder is unit-testable headless
against a real multi-sensor recording.

### 2d. What "locked relationship" means numerically
The solved set `{Cᵢ}` (with `C₀ = identity`) is the **frozen** inter-sensor
relationship. Group placement `G` operates entirely on top; a group drag edits
`G` only (§3), so the `{Cᵢ}` never move — that is precisely what makes the
cluster a rigid body. Re-running calibration is the *only* thing that changes
`{Cᵢ}`, and it requires an explicit unlock (§4).

---

## 3. Group-placement handle

**Decision: `G` is a `ZoneFit`-shaped similarity that is *editable*; auto value =
`zonefit` over calibrated centroids (§1), manual override edits rotation +
translation only.**

- **Auto (the common case, `Z;` present).** `G` = the calibrated `zonefit` fit.
  Nothing to persist — it recomputes from `Z;` every load. This is the "automatic
  version of placement" the owner described.
- **Manual override / refinement.** A `Placement` value the GUI drag writes:
  a translation `t` (from a group drag) and a rotation about a pivot (from a
  group rotate), composed onto the seed. Scale stays whatever the seed had
  (`1.0` when hand-placed from the translation fallback; the `zonefit` scale when
  refining an auto fit). The manual handle deliberately exposes **only
  translate + rotate** — the user is seating a rigid cluster by eye, not
  rescaling it.
- **No `Z;` at all.** `G` starts from the existing per-sensor translation
  fallback, promoted to a *single group* translation seeded from the reference
  sensor's anchor (`anchor_world_ft`), and is placed entirely by hand. (Today's
  per-recording independent anchoring remains for the single-sensor /
  uncalibrated case — calibration is what turns N anchors into one group seat.)

`Placement` and `ZoneFit` share an `apply_m` signature so `AlignmentTransform`
treats them interchangeably.

---

## 4. Interactive-authoring UX / persist-into-edit (the load-bearing GUI change, Item 40)

**Decision: relax the Item 30/35 read-only-mode invariant so a Replay/Live
overlay *persists into draw/edit*, driven by the same `replay_layer` +
`pointer-events:none` machinery — only the transform behind it changes.**

- **Overlay persists into edit.** Today the marker layer is populated only in the
  read-only `Replay`/`Live` modes (`refresh_marker_layer` clears it otherwise).
  Item 40 keeps the *separate* `replay_layer` + `pointer-events:none` layer but
  lets it stay live while draw/edit tools are active, so the user can watch the
  tracks move over the zones as they align. Item 37 was deliberately told **not**
  to touch this invariant so Item 40 has one clean surface to relax.
- **Group placement = the normal gesture (locked).** Moving/rotating a sensor
  drags the **whole calibrated cluster as a rigid body**: it edits `G` (§3), not
  one sensor's `position_x/y`. The overlay re-renders through the composed
  transform in real time (marker-layer-only rewrite — §6). Reuse the existing
  `sensor_drag` gesture and the Edit-mode 2-click rotate, retargeted to write
  `G` instead of the sensor field while the group is *locked*.
- **Auto-calibrate + unlock (the distinct step).** A separate "Auto-calibrate"
  action runs the §2 relational solver over the current live/recorded pairs,
  makes the sensors agree, and **locks** the result. An **unlock** affordance
  reveals the raw per-sensor gesture — dragging one sensor relative to the others
  (i.e. hand-adjusting calibration) or re-running the solver. Normal use =
  locked (move the group); unlock is the rare "the auto-calibration is wrong"
  path. This is the lock/unlock affordance Item 38 requires, and it cleanly
  separates the two transforms at the gesture level: **locked drag → `G`;
  unlocked drag → `Cᵢ`.**
- **Coexistence.** The static zone/centerline SVG stays beneath, untouched; the
  overlay is the top layer as before. Leaving alignment restores prior tool
  state and stops any live timer, exactly as Replay/Live do today.

---

## 5. Preview → commit

**Decision: uncommitted alignment is in-memory session state (reversible,
project untouched); commit writes only the *calibration* into per-sensor
`azimuth_angle` + `position_x/y`; group placement is not written per-sensor.**

### 5a. Uncommitted-state format
The live `AlignmentTransform` (`{Cᵢ}` + `G`) is held on the view/session, the
`Project` untouched — reversible by discarding it, matching how Replay/Live
already hold transient overlay state. **Optional, deferred:** a sidecar
`sites/<site>/<project>.align.json` keyed to the project can persist an
uncommitted alignment across sessions without mutating the iprj (the natural home
for a *manual* group placement on a no-`Z;` site). In-memory-first is the
load-bearing decision; the sidecar is a later convenience, not required for
Item 40.

### 5b. What commits, and why only calibration
Only **calibration `Cᵢ`** writes back into the iprj, because only it is a
per-sensor *mounting* correction (the thing `sensor_calibration.py` recommends
and the field technician re-applies to the device). **Group placement `G` does
not commit per-sensor:**
- When `Z;` exists, `G` is *already reproducible* — `zonefit` recomputes it every
  load from the exact zone geometry. There is nothing to persist.
- When the user hand-places (no `Z;`), that override is a whole-group rigid map,
  not a per-sensor mounting change, so it belongs in the §5a sidecar (or is kept
  purely as a designer-side layer), **not** smeared into per-sensor azimuth.

This is the exact/approximate split from §0 made operational: the *exact,
reproducible* transform stays a computed layer; only the *statistical* transform
that re-estimates genuine human eyeballing gets written into the file.

### 5c. Commit math (sign/units — the bug-prone lines for Item 39)
`Cᵢ` is a rigid map in EVO meters: `p' = r·p + d` (`|r| = 1`, rotation angle
`θᵢ = arg(r)`; translation `d` in meters). Fold it into sensor `i`'s config via
the unique **"rotate about the sensor's own position, then move the sensor"**
decomposition — for a rigid `T(p) = r·(p − c) + T(c)` with `c` = the sensor's
position, the rotation about the sensor is `r` and the new sensor position is
`T(c)`:
- **Azimuth:** `new_azimuth = old_azimuth ± θᵢ_deg`. The sign is the single
  bug-prone line (the iprj azimuth convention vs. the complex-plane / y-down
  rotation sense) — **pin it with the commit→reload round-trip test** (Item 39),
  mirroring `sensor_calibration.py`'s "ADD θ°".
- **Position:** `new_position = Cᵢ(old_position)`, i.e. apply the rigid map to
  the sensor's own location, then convert EVO-meters → world-feet
  (`m_to_ft`) → world-px (`ft_to_px` via `effective_meter_per_pixel`), respecting
  the post-`normalize_origin` (bg-offset-subtracted) world-px convention the iprj
  stores.
- **Round-trip / ≈identity claim (honest scope).** Because calibration is a
  *statistical* fit over noisy radar, "a committed project re-reads to ≈identity"
  is **approximate and validated against a re-capture**, not float-exact like the
  `Z;` derivation. Item 39's round-trip test asserts that re-solving against the
  *same* pairs after applying the committed correction yields `Cᵢ ≈ identity`
  within tolerance — the pure-function proof that the commit math and its signs
  are self-consistent.

### 5d. Commit UX
Reversible overlay state → an explicit "Commit calibration to sensors" action
with confirm + undo (Item 40). Committing does **not** discard the overlay; it
folds `Cᵢ` into the sensors and resets the in-memory calibration toward identity
so the overlay keeps rendering in place.

---

## 6. Apply to live *and* recording — one path

Both render paths already funnel through `_align_frame` (RPP §1b, LOP §2), so
threading the `AlignmentTransform` there (§1) makes **replay and live inherit
calibration from the one seam** — no second application site:
- **Replay (Item 30):** `parse_recording` builds the `AlignmentTransform` once at
  load and every frame aligns through it.
- **Live (Item 35):** `LiveAligner` holds the `AlignmentTransform` as state
  (beside its `_zone_fit` today) and applies it per `feed`.
- **Committing mid-live-session** rebuilds the transform (calibration reset
  toward identity, §5d) and the next `ui.timer` tick re-renders from the updated
  slot — natural with the drop-to-latest render model (LOP §3); no in-flight
  frame surgery needed.

---

## 7. Guardrails / degeneracy

Carry the refuse-don't-guess character (`zonefit`'s gates, Item 36's spirit) onto
the calibration path — a wrong correction is worse than none:
- **Too few pairs** for a sensor (`< MIN_PAIRS`) → that sensor stays
  **uncalibrated** (`Cᵢ` absent → identity) and is **flagged** in the status /
  fit-quality readout. Never fit `Cᵢ` to a handful of noisy pairs.
- **Collinear pairs** → rotation is under-constrained; fall back to
  translation-only for that sensor (drop `r` to identity, keep `d`) and flag it —
  the direct analogue of `zonefit`'s `MIN_SPREAD_FT` lever-arm gate.
- **Sensor with no pairs** → keep its uncorrected position, **flag** it (it
  couldn't be calibrated) rather than silently merging it as identity without
  notice.
- **No `Z;`** → group placement is the manual translation-seeded `Placement`
  (§3); calibration still runs if there are vehicle pairs. No `Z;` and no pairs →
  identity everywhere → today's per-sensor translation behavior (§0 reduction).
- **Fit-quality surfacing.** Expose per-sensor pair-count / residual and the
  group `G`'s residual on the transform so the GUI status line can report *how
  well* it calibrated (Item 40), the same way `ZoneFit` already carries
  `mean_residual_ft`.
- **Never raise on degenerate input** (the `LiveAligner.feed` / batch
  skip-on-error discipline): a solve that can't converge returns identity +
  flag, it does not throw.

---

## 8. What each downstream item inherits

| Item | Target | Inherits from this doc |
|---|---|---|
| **39** Transform + N-sensor solver | Fable | §1 `AlignmentTransform`/`RigidDelta` in **new pure `model/calibration.py`**, threaded through `_align_frame` in place of `zone_fit` (one seam, both paths); calibration in **EVO-meter space, per-sensor, before** the group placement; §2 the **rigid** relational solver as the pure-Python complex-LS *sibling of `zonefit`* (unit-modulus, **no** scipy/pandas/numpy), reference-anchored (`C₀ = identity` gauge) with the joint solve as a noted upgrade, `sensor_calibration.py`'s isolation/coarse/volume gates generalized to N sensors; §1 `G` = `zonefit` refit over **calibrated** centroids (reuse the LS, no second copy) reducing to today's fit at identity; §5c the commit math as a pure function (`azimuth ± θ`, `position = Cᵢ(pos)`, sign pinned by a **commit→reload ≈identity round-trip test**); §7 degeneracy = identity+flag, never raise. **Correctness gates (pytest, real multi-sensor site, read-only):** calibration recovery (perturb one sensor's frame, recover the delta that re-agrees it), group-placement compose-order (a group move lands markers on the background *without* changing inter-sensor agreement), commit→reload ≈identity. |
| **40** Interactive alignment mode + commit | Opus | §4 relax the read-only invariant so the overlay persists into draw/edit on the same `replay_layer`; **locked** sensor drag/rotate → `G` (whole group as a rigid body, real-time re-render), **unlock** → per-sensor `Cᵢ`; a distinct "Auto-calibrate" action running the §2 solver and locking; §5 preview (in-memory) → commit calibration into per-sensor `azimuth`/`position` with confirm+undo; §6 one path feeds both replay and live, commit mid-live re-renders via the drop-to-latest slot; §6/§7 marker-layer-only rewrite (no static-SVG re-render on drag ticks — the Item 20/30 lesson), fit-quality/degeneracy surfaced in the status line. |

### Open items explicitly handed forward
- **Azimuth-write sign.** The one convention-sensitive line (§5c); Item 39 owns
  proving it with the round-trip test, not guessing it — the analogue of RPP §7's
  y-sign open item.
- **Joint N-sensor solve.** Reference-anchored pairwise ships first (§2b); the
  joint least-squares over a weak/disconnected overlap graph is a scoped upgrade
  behind the same `AlignmentTransform` output, not this batch's minimum.
- **Uncommitted-alignment sidecar.** In-memory is the first cut (§5a); the
  `*.align.json` sidecar (for persisting a *manual* no-`Z;` placement across
  sessions) is deferred until a real workflow needs it.
- **Multi-host live calibration.** Calibration needs multiple sensors in one
  fused frame; single fused stream is the norm today. Multi-host *live* overlay
  is already LOP's later extension — calibration over a merged multi-host live
  slot inherits that same deferral.
