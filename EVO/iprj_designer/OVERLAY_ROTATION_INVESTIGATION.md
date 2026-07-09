# Overlay Rotation — Investigation Brief (for a Fable diagnosis session)

**Status: RESOLVED 2026-07-09 (Fable session) — see §10 for the outcome.**
The `Z;`-zone similarity fit (§2b / §6 Q0) panned out and is implemented in
`model/zonefit.py`, wired through `parse_recording` and `LiveAligner` with
the old translation as fallback. Sections below are kept as the historical
handoff record.

*(Original status:)* open bug, escalated to Fable after an Opus fix attempt
failed and the leading "wrong iprj" theory was ruled out on real hardware.
This file is the complete handoff: the symptom, everything checked, the
numbers, the code paths, the resources to read, and the specific questions
to answer. Read it top to bottom before touching code.

> Routing note: this is a legitimate Fable escalation per
> [CLAUDE.md](CLAUDE.md) — a *specific, narrowed* bug (find the correct EVO→image
> transform / where the rotation comes from) that Opus investigated but did not
> solve. Stay scoped to the diagnosis + fix; record the outcome back here and in
> [DESIGN_HISTORY.md](DESIGN_HISTORY.md).

---

## 1. Symptom

When the EVO recording/live overlay is drawn on the site background image, some
sites are **visibly rotated ~25–34°**; others are correct.

- **US95&SH8 (`sites/86_US95&SH8/`): correct** under the current pure-translation
  alignment.
- **Banks (`sites/Banks/`): rotated ~30°.** A southbound vehicle that should
  thread the **Ph 6** detectors and then run along the **left** of the **Ph 2**
  detector string instead renders as a top-right→bottom-left diagonal.

**Ruled out on hardware (2026-07-xx):** the owner re-pulled the *concurrent* iprjs
(the ones live when the recording/feed was captured) and **the ~30° rotation
persists.** So this is **not** a stale/wrong-file pairing and **not** user error —
it is a real transform gap.

---

## 2. One-paragraph root-cause picture (best current understanding)

The EVO stream's fused track frame is **rotated by a real, site-specific angle**
relative to the background image. For a site whose image happens to be oriented
the same as the EVO frame (US95&SH8, offset ≈ 0°) pure translation looks correct;
for Banks the offset is ≈ **−27° to −34°** so translation alone leaves it skewed.
**Every** current EVO tool aligns by *translation only* — the rotation step was
never implemented (see §5). The correct transform is a 2D **similarity**
(rotation + uniform scale + translation); the hard part is recovering its
parameters robustly (see §4 for why the obvious source fails).

---

## 2b. ★ Strongest lead (added later): the `Z;` line is the alignment reference

The recording contains a **`Z;` line** — the sensor's event-loop / detector-zone
polygons **in the EVO frame (metres)**, the same loops the iprj stores in map
pixels. This is the long-baseline, in-frame correspondence set the 2-sensor
baseline lacked: in the Banks capture it is **36 zones spanning the whole
intersection**. It arrives once as part of the `GetCfg` response (alongside `C;`).

Example (first two zones): `Z;0,0,6,33,43.577991,-11.129528,40.338005,-13.190846,
48.925793,-26.690271,52.165779,-24.628952;0,0,0,0,66.253685,-1.890499,...` —
i.e. `Z;` then `;`-separated zones, each `= 4 header ints + 4 (x,y) vertices`.
The 4 header ints are **not yet decoded** (likely sensor index / zone id / type /
enable) — decoding them is the key to matching a `Z;` zone to its iprj
`EventZone`.

Status: **promising but not yet solved.** A naïve fit assuming `Z;`-order ==
iprj-order fails (36 `Z;` zones vs 20 iprj `event_zones`, different order, and the
`Z;` set likely spans a different sensor subset — this capture's fused stream
carries sensors 0/1/3 while `sensors_1&2_w_fail.iprj` has only 0/1). **Once the
`Z;` header is decoded and zones are matched to the iprj by id, a similarity fit
over 20+ well-spread zone centroids should pin rotation+scale precisely** — no
human line-up needed, and it works for live too (the same `Z;` comes over the
wire). This likely supersedes the manual-line-up fallback if it pans out.

Tooling added: [../evo_recorder_full.py](../evo_recorder_full.py) records the full
raw stream **and** mirrors every `C;`/`Z;` config line into a labelled
`<host>_EVO_<epoch>.config.txt` sidecar, re-requesting `GetCfg` until a `Z;` is
captured — so the alignment geometry is never missed or buried. (The existing
recorders already write `Z;` if they catch the one `GetCfg` reply; this just makes
it robust and obvious.) The designer's replay parser currently **ignores `Z;`** —
`model/replay._parse_lines` only handles `F;`/`C;`/timestamps.

---

## 3. Hypotheses — status

| # | Hypothesis | Status | Evidence |
|---|---|---|---|
| H1 | Missing rotation in the transform (EVO frame ≠ image orientation) | **CONFIRMED as the mechanism** | Banks rotated ~27–34°, US95 ~0°; a similarity fit aligns Banks (§4) |
| H2 | Wrong / non-concurrent iprj paired with the recording | **RULED OUT** | Owner re-pulled concurrent iprjs; rotation persists |
| H3 | Auto-fit the rotation from `C;`-line sensor positions ↔ iprj sensor positions | **DEAD END** | 2-sensor, ~99 ft, hand-placed baseline too noisy: gave −26.9°/scale 0.91 vs true −33.7°/1.23; broke US95 (spurious −4.5°). Reverted (commit `0a45371`→`5f847e4`). **Do not retry.** |
| H4 | It's a nonlinear / unfixable data mismatch | **RULED OUT** | A *single* similarity transform fits the whole Banks corridor to 0–32 ft when calibrated on a long baseline (§4) |
| H5 | Rotation is derivable from sensor `AzimuthAngle` | **OPEN — unexplored rigorously** | No constant maps az to the needed rotation (US95 az0 −170.56→0°; Banks az0 −54.17→~−30°), but the *EVO-frame convention* was never worked out. See §6 Q3 |
| H6 | Rotation is recoverable via GPS (ENU) | **BLOCKED** | Sensor `Gps_lat/lng` are all `0.00`; only a single site lat/long is in the `C;` line |
| H7 | The original code had a rotation step that got dropped | **OPEN — likely** | `fusion_visualizer.py` calls its translation "Global Offset (**Rough** Alignment)" — a fine/rotation step was implied but never found. See §5 |

---

## 4. Key quantitative findings (all reproducible — see §7)

**Sites tested:** `sites/86_US95&SH8/us95&sh8.iprj` (correct) and
`sites/Banks/sensors_1&2_w_fail.iprj` (rotated), plus all 13 Banks `.iprj`
variants.

**Recordings:**
- Banks: `10_37_23_201_EVO_1783582697.txt` (repo root; trailing digits are a Unix
  epoch ≈ July 2026).
- US95: `sites/86_US95&SH8/10_37_2_86_EVO_1770311735.txt` (≈ Feb 2026).

**Rotation between EVO frame and map (from `C;`↔sensor positions):**
- US95&SH8: **−4.5°** (i.e. ~0 + noise — translation correct)
- Banks: **−26.9°**, and **−22° to −27° consistently across all 13 Banks `.iprj`
  files** → the offset is a real, stable property of the Banks site, not a
  wrong-file artifact.

**The transform is a similarity, and it works when calibrated on a long baseline.**
Grounded on the Banks detector layout (world feet):
- `1: Ph 6 SB` (279, 535)
- `1: Ph 2 SB` (291, 687) → `2: Ph 2 Adv1` (257, 880) → `3: Ph 2 Adv2` (216, 1003)
  → `4: Ph 2 Adv3` (162, 1121)

The SB vehicle is two joined tracks: **oid 550553** (sensor 3, upper approach) +
**oid 110001** (sensor 1, lower approach).

| Calibration source | rotation | scale | residual to the 5 detectors |
|---|---|---|---|
| Short (99 ft sensor pair) — what the reverted fix used | −26.9° | 0.91 | 16 ft → **91 ft** (grows with distance) |
| **Long (vehicle's ~600 ft path: Ph6-pass & Ph2Adv3-pass)** | **−33.7°** | **1.23** | **0–32 ft everywhere**, track sits just left of Ph 2 — matches the owner's description |

**Takeaway:** the recording and map ARE consistent under one rotation+scale
(H1/H4). The reverted auto-fit failed purely because a ~99 ft, hand-placed
2-sensor baseline can't resolve rotation to <~1° or scale to <~2% — the precision
the far end of a 600 ft corridor needs. The correct params must come from a **long
baseline** (in practice, a human lining the overlay up), not the sensors.

**Other config facts (both sites):** `BackgroundImageRotation = 0`; sensor
`Gps_lat/lng = 0` (unpopulated); `MeterPerPixel` Banks 0.08 (effective 0.0762),
US95 0.20; sensor azimuths — US95 S0 −170.56 / S1 31.84, Banks S0 −54.17 / S1 134.00.

**`C;`-line decode (important, and correct):** groups of three `x, y, confidence`
per sensor slot 0–3 (absent sensors `?`), then a trailing `longitude, latitude,
apikey`. Banks: slot0 (23.3751, 4.6958), slot1 (49.2315, −10.8922), slot3
(52.8679, −6.93397), lon/lat (−116.115, 44.0846). US95: slot0 (−1.52023,
−25.3302), slot1 (6.77023, 24.3302), lon/lat (−117.0, 46.7261). The current
parsers read only the first pair.

---

## 5. Where alignment lives in code (all translation-only today)

- **Designer overlay:** [model/replay.py](model/replay.py) — `_align_frame` +
  `anchor_world_ft`. Formula: `world_ft = anchor_ft + m_to_ft(p_m − ref_m)`. Pure
  translation, no rotation/scale. Both the batch `parse_recording` and the live
  `LiveAligner` go through `_align_frame`, so a fix lands in one place.
- **Canonical plotter:** [../evo_replay.py](../evo_replay.py) `align()` (~line 195)
  — `trans = map_s0 − evo_s0`, translation only. Default site is US95&SH8, which
  is why it always "looked reliable."
- **Parent / smoking gun:** [../fusion_visualizer.py](../fusion_visualizer.py)
  `parse_and_align_data` (~line 449) — comment literally reads **"Global Offset
  (Rough Alignment)"**, `trans_x = s0_x − evo_s0['x']`. The word *Rough* implies a
  fine (rotation) step that was intended but never found. Default site US95&SH8.
- **`EVO_plotter.ipynb`** — the notebook the above were distilled from; grep shows
  only `Radarsensor_0_Position` + `MeterPerPixel`, no rotation. Also translation.
- **Sensor-to-sensor calibration (different problem, but relevant math):**
  [../sensor_calibration.py](../sensor_calibration.py) — `apply_rigid_transform` +
  an optimizer that finds a rotation ("Azimuth adjustment, degrees") aligning
  sensor 1's points onto sensor 0's. This is the vendor's *inter-sensor fusion*
  calibration, NOT the EVO→image transform — but it proves the EVO frames carry
  real rotational content and shows the rigid-fit approach the codebase already uses.

**Conclusion:** no current tool ever rotated the overlay. The "rough alignment"
was always the whole story, and it only ever worked because US95&SH8 needs no
rotation.

---

## 6. Questions for Fable to answer (in priority order)

0. **★ Decode the `Z;` line and align by zones (§2b) — try this first.** Work out
   the 4 header ints per zone (sensor / zone-id / type / enable?), match each `Z;`
   zone to its iprj `EventZone`, and fit a similarity over the matched zone
   centroids (20+ points spanning the intersection = the long baseline H3 lacked).
   If it lands the corridor within ~15 ft, this is the fix — automatic, and it
   works live (same `Z;` on the wire). Cross-check against the manual long-baseline
   number (−33.7°, scale 1.23).
1. **Where does the Banks rotation come from, and is it derivable from stored
   data at the precision needed (<~1°)?** The 2-sensor baseline is out (H3); `Z;`
   zones (Q0) are the best candidate. Any *other* long-baseline reference — the two
   `MeterReference0/1` calibration points, the `C;` lat/long + per-track GPS — is a
   fallback.
2. **Was there ever a rotation/fine-alignment step?** Chase the "Rough Alignment"
   thread (§5): read `fusion_visualizer.py` fully, `EVO_plotter.ipynb`'s alignment
   cells, and especially **`~/pyatspm/src/atspm/video/calibrate.py`** (the
   line-up/calibrate workflow CLAUDE.md earmarks). The owner recalls the *original*
   transform "used the iprj file (and an element within it) to rotate and/or
   scale" — find that element/step if it exists.
3. **What frame are the `F;` track coordinates actually in?** Is the EVO fused
   frame north-aligned (ENU), sensor-0-boresight-aligned, or configured per site?
   Resolve the `AzimuthAngle` convention (H5): does `azimuth − (EVO-frame boresight
   of sensor 0)` recover the map rotation? If the EVO frame is ENU, the map's
   rotation-from-north *is* the offset — can it be gotten from anything precise?
4. **If no robust automatic source exists, confirm the fallback:** a per-site
   **2-point "line-up"** (pick a track point, place it on the map, twice over a
   long baseline → solve rotation+scale+translation), identity by default so
   correct sites are untouched. Does `calibrate.py` already implement exactly this?

---

## 7. Reproduction — the diagnostic script

Run from the repo root with the project venv (`.venv/bin/python`). This prints the
rotation-from-sensors, the long-baseline corridor fit, and the per-detector
residuals — the numbers in §4.

```python
import sys, math; sys.path.insert(0, "EVO/iprj_designer")
from model.iprj_io import load_iprj
from model.replay import _parse_lines
from model import units
from pathlib import Path
from collections import defaultdict

proj = load_iprj(Path("sites/Banks/sensors_1&2_w_fail.iprj"))
emp = units.effective_meter_per_pixel(proj.background)
ref, seen, raw, _z = _parse_lines(Path("10_37_23_201_EVO_1783582697.txt").read_text(errors="ignore"))  # 4-tuple since the fix
tracks = defaultdict(list)
for t, ents in raw:
    for oid, cls, x, y, h in ents:
        tracks[oid].append((x, y))

# EVO-frame sensor slots (from the C; line) and iprj map positions (world feet)
EVO = {0: (23.3751, 4.6958), 1: (49.2315, -10.8922)}
e0 = (units.m_to_ft(EVO[0][0]), units.m_to_ft(EVO[0][1]))
e1 = (units.m_to_ft(EVO[1][0]), units.m_to_ft(EVO[1][1]))
m0 = (units.px_to_ft(proj.sensors[0].position_x, emp), units.px_to_ft(proj.sensors[0].position_y, emp))
m1 = (units.px_to_ft(proj.sensors[1].position_x, emp), units.px_to_ft(proj.sensors[1].position_y, emp))
def bearing(p, q): return math.degrees(math.atan2(q[1]-p[1], q[0]-p[0]))
print("rotation from 99ft sensor pair:", round(bearing(m0, m1) - bearing(e0, e1), 1), "deg  (unreliable)")

# Long-baseline fit: map the SB track's Ph6-pass & Ph2Adv3-pass points onto those
# detectors, then check residual at every detector.
DET = [('Ph6',(279,535)),('Ph2SB',(291,687)),('Ph2Adv1',(257,880)),('Ph2Adv2',(216,1003)),('Ph2Adv3',(162,1121))]
rawpts = [(units.m_to_ft(x), units.m_to_ft(y)) for x, y in tracks[550553] + tracks[110001]]
def tr(p): return (m0[0] + (p[0]-units.m_to_ft(ref[0])), m0[1] + (p[1]-units.m_to_ft(ref[1])))
nearest = lambda det: min(rawpts, key=lambda r: math.dist(tr(r), det))
rA, rB, mA, mB = nearest(DET[0][1]), nearest(DET[-1][1]), DET[0][1], DET[-1][1]
ev = (rB[0]-rA[0], rB[1]-rA[1]); mv = (mB[0]-mA[0], mB[1]-mA[1])
th = math.atan2(mv[1], mv[0]) - math.atan2(ev[1], ev[0]); s = math.hypot(*mv)/math.hypot(*ev)
a, b = s*math.cos(th), s*math.sin(th); tx = mA[0]-(a*rA[0]-b*rA[1]); ty = mA[1]-(a*rA[1]+b*rA[0])
fit = lambda p: (a*p[0]-b*p[1]+tx, b*p[0]+a*p[1]+ty)
print(f"long-baseline corridor fit: rotation {math.degrees(th):.1f} deg, scale {s:.3f}")
for name, d in DET:
    print(f"  {name:<8} min dist: {min(math.dist(fit(p), d) for p in rawpts):>5.0f} ft")
```

To dump the Banks detector layout (names + world-feet centroids) and re-derive the
ground-truth corridor, load the same project and iterate
`proj.sensors[i].event_zones` (each zone's `.zone_name` + `.points`, convert px→ft
with `units.px_to_ft(·, emp)`).

---

## 8. Resources to read (checklist)

- [ ] `~/pyatspm/src/atspm/video/calibrate.py` — the line-up/calibrate workflow
      (most likely home of the "rotate/scale from an iprj element" step). **Start here.**
- [ ] [../fusion_visualizer.py](../fusion_visualizer.py) — full alignment path +
      the "Rough Alignment" comment; any downstream fine-align.
- [ ] [../EVO_plotter.ipynb](../EVO_plotter.ipynb) — original alignment cells.
- [ ] [../evo_replay.py](../evo_replay.py) `align()` — the distilled translation.
- [ ] [../sensor_calibration.py](../sensor_calibration.py) — rigid-fit + azimuth
      adjustment (inter-sensor; convention clues).
- [ ] [model/replay.py](model/replay.py) — where the designer overlay transform lives.
- [ ] [DESIGN_HISTORY.md](DESIGN_HISTORY.md) 2026-07-09 entries — the reverted
      attempt and the diagnosis pass, with rationale.
- [ ] [RECORD_PLAYBACK_PLAN.md](RECORD_PLAYBACK_PLAN.md) §1b and
      [LIVE_OVERLAY_PLAN.md](LIVE_OVERLAY_PLAN.md) §7 — the original (wrong)
      "no-rotation" assumption and its resolution note.
- [ ] Site data: `sites/86_US95&SH8/` (correct baseline) and `sites/Banks/`
      (13 `.iprj` variants + the recording at repo root).

---

## 9. Candidate fix directions (for after diagnosis)

1. **Port the original rotate/scale step** if §6 Q2 finds it (calibrate.py or the
   notebooks) — the cleanest outcome.
2. **Per-site 2-point line-up** (§6 Q4) — robust, no noisy inference, identity by
   default so US95 and every correct site are untouched. Fits the `calibrate.py`
   integration already on the roadmap.
3. **Georeferenced fit** — only viable if precise, long-baseline correspondences
   exist (they don't today: sensor GPS is zeroed, the 2-sensor baseline is too
   short). Lowest priority.

**Do not** re-attempt the sensor-position auto-fit (H3) — it is proven noise-limited.

---

## 10. OUTCOME (2026-07-09, Fable session) — resolved via §2b / Q0

Q0 landed; direction 1 of §9 (find the original transform) and direction 3
(georeferenced fit) turned out to be the *same thing* as the zone fit, and the
manual line-up (direction 2) is unnecessary for any capture that carries `Z;`.

**`Z;` header decoded** — the 4 ints are `sensor_slot, is_ignore_zone,
phase_number, output_number`, and zones arrive per slot in the iprj's slot
order, event zones before ignore zones. The Banks capture's 36 zones equal
exactly the nonempty EventZone/IgnoreZone counts (8+3 / 12+7 / 4+2) of stream
slots 0/1/3 across the concurrent `banks_1_2.iprj` + `banks_3_4.iprj`.

**Slot matching** — a project sensor is identified to its stream slot by its
ordered zone *signature*, the (kind, phase, output, vertex-count) sequence of
its nonempty zones. Unique, self-validating (banks_3_4's lone sensor matches
slot 3 only); ambiguity or non-match simply contributes no correspondences.

**Q2 answered — the "element within the iprj" found.** Per-sensor similarity
fits over matched zone centroids are **numerically exact (0.0 ft residual)**:
the vendor tool converts between drawn map zones and the sensor's EVO-frame
zones with exactly a per-sensor rotation+translation, using the *stored*
MeterPerPixel — the fitted scale is exactly `effective_mpp / stored_mpp`
(0.9525 = 0.0762/0.08 at Banks; the §1a rounding, recovered). The iprj zones
*are* the transform record. §4's manual estimate (−33.7°, scale 1.23) was
directionally right but biased by its track-point anchors and the older
`sensors_1&2_w_fail.iprj` geometry; the zone fit supersedes those numbers.

**Fit quality** — Banks (slots 0+1, 30 zones): **−34.9°, mean/max residual
5.6/7.4 ft** (inter-sensor map placement inconsistency); the SB vehicle
threads Ph 6 at 8.5 ft and runs 10–17 ft left of the entire Ph 2 string —
the owner's ground truth. US95&SH8 (13 zones): **+1.5°, scale 1.017** —
≈ identity, so the previously-correct site is untouched (the H3 regression
cannot recur; a real least-squares optimum over 13 spread zones, not a 2-point
noise fit). Q3 (what frame is the EVO fused frame) is thereby moot for
alignment: whatever its convention, the `Z;` zones pin it per capture.

**Implementation** — `model/zonefit.py` (pure: `parse_zline`, signature
`match_slots`, complex least-squares `fit` — cannot express a reflection;
fallback gates ≥3 zones, ≥50 ft spread, ≤30 ft mean residual). Wired into the
single `_align_frame` transform: `parse_recording` fits from the file's `Z;`
(`Recording.zone_fit`), `LiveAligner` adopts the fit when the GetCfg `Z;`
arrives (first usable wins, like `C;`). No usable `Z;` → the plan-§1b
translation, unchanged. Tests: `tests/test_zonefit.py` (exact synthetic
recovery, signatures, fallback gates, batch+live wiring, Banks/US95
integration pins). Remaining loose end: the standalone `../evo_replay.py`
is still translation-only; port the same fit there if it keeps being used
for rotated sites.
