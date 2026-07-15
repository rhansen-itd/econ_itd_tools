# Roadmap — iprj Designer

All numbered work through Item 46 is complete and archived in
[[DESIGN_HISTORY.md]], not listed here anymore: the Phase 1 MVP (Sessions 1–7 —
data model, drawing core, attributes, templates, centerline placement), a
second "Phase 1–4" round (quick wins/file management, domain accuracy, the
toolbar/multi-select overhaul, and the advanced template engine), a third
numbered-items round (Items 1–9 and 11 — background-tool rework, per-zone-type
conditions, sensor management, edit-mode/vertex tools, terminology renames,
free-draw polygons, centerline re-stationing, canonical origin, and the
multi-sensor 2-file split), a fourth "owner batch" round (Items 12–20 — quick
UI fixes, the template-editor taxonomy rename + even spacing + side-by-side
adjacency table, centerline placement snap/naming, and the large-file
zoom-freeze fix), a fifth "annotation-ownership" round (Items 21–22 —
sensor-scoped lineals/centerlines/labels via vendor index bands, plus the
text-label GUI entity + centerline-name labels), a sixth "Draw-hub
consolidation" round (Items 23–27 — the unified owner/sensor dropdown, the
oversized off-image canvas, bulk-edit + persisted centerline membership, and
folding Template into Draw › Event Zone), the record/playback batch (Items
28–31 — the coordinate/units plan, the pure `model/replay.py` playback engine,
the Replay timeline + animated overlay, and live recording integration), the
live-overlay batch (Items 32–35 — the feed-tap plan, the streaming
`LiveAligner`, the recorder subscription seam, and the real-time Live overlay
mode), the Overlay-tab consolidation + calibration/interactive-alignment batch
(Items 37–40 — one Overlay surface, then the two-transform
calibration/group-placement plan, the N-sensor relational solver in
`model/calibration.py`, and the interactive Align mode with commit-to-iprj),
and the track-stitching/fusion + ground-truth rounds (Items 41–46 — the fusion
plan + pure `model/fusion.py` engine + overlay wiring, the ground-truth
stitching fixture and engine improvements, the in-GUI review-labeling + fused
underlay + ghost-tail round, and self-calibrating fusion). Reusing "Phase 1"
for two unrelated rounds is exactly the confusion this file is now organized to
avoid.

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

---

## 47 — Fused Overlay & Review Refinements: Bad-Pair Label, Traceable IDs, Persistence Interpolation (Target: Fable) — needs Items 43/45

The owner's 2026-07-14 fused-overlay batch, one session — three changes to the
fused display + review-labeling surface (Items 43/45), grouped because they all
touch the Replay transport, `model/review.py`, and the `model/fusion.py` render
helpers (`fused_frame_markers` / the marker glyph). Routing note: matches the
active fusion workflow (Items 44–46 all Fable); under CLAUDE.md's standing rule
this would default to Opus if Fable access lapses.

Scope (done 2026-07-14 — see [[DESIGN_HISTORY.md]]):
- [x] **"Bad pair" review kind** — a new observation kind meaning *these
      members must **not** all share one fused id* (the inverse of
      handoff/persistence). Per the owner it is **only offered while the fused
      view is showing**: the user clicks a fused marker they judge over-merged
      and its constituent members (`FusedTrack.members`) become the selected
      group, committed as `bad_pair` (needs ≥2 distinct members; reuse the
      `ped`/`unsure`/`note` flags). Add it to `review.py`'s `KINDS`, the
      `<capture>.observations.json` schema, and `fusion_eval.py` scoring —
      **pass = the flagged members end up in ≥2 distinct fused ids**, fail if
      the engine still fuses them into one. This complements the synthetic
      don't-merge cases (Item 42) with owner-observed ones.
- [x] **Traceable fused IDs** — replace the fused view's plain integer label
      with one built from the constituent original oids' **last three digits,
      sensor number omitted**, e.g. two members with oids …505 and …685 →
      `505-685`, so a fused marker is traceable to what raw view shows. Keep
      `FusedTrack.fused_id: int` as the internal identity (eval / `id_of` /
      `fused_frame_markers` keys stay integer-keyed) and add a **separate
      display label** (a pure helper, e.g. `fused_label(track)` beside
      `short_id`) so nothing downstream depends on the label text.
      *(Open decision — RESOLVED with the owner 2026-07-14: the site oids
      encode the sensor as the **trailing** digit (`oid % 10`, the Item 44
      convention — confirmed against the observation fixtures; the leading-digit
      example did not match the data). Rule: take each member's last three oid
      digits, **drop the trailing sensor digit → two digits** (`881520` → `520`
      → `52`), and **join all members in join order** (`52-77-54`), duplicates
      kept.)*
- [x] **Persistence-gap interpolation** — for a persistence/anchor track that
      dropped and re-acquired, **interpolate the intermediate frames** across
      the gap (linear between the last-before and first-after fused points) and
      emit them on the marker layer **visually distinguished as filled-in**
      (different symbology / color / reduced opacity) so it is clear they are
      synthesized, not observed. Tag the synthetic points so the render can
      style them (mirror the `kind="ghost"`/stray styling pattern); keep the
      engine's stored geometry, eval, and tests exact (display-only fill, like
      `smooth_seams` in Item 45 — do **not** feed interpolated points back into
      bridging/occupancy logic).
- [x] pytest for the model-side helpers (bad_pair scoring in a `fusion_eval`
      case, `fused_label` formatting incl. the >2-member and collision cases,
      the interpolation helper's point count/positions + synthetic flag); GUI
      wiring (fused-marker click → group select; filled-in styling) exercised
      by hand + a headless render check. Eval buckets unchanged except the new
      bad_pair line. DESIGN_HISTORY entry; check off this item.

Suggested prompt:
> [Fable] In EVO/iprj_designer, do Item 47 of ROADMAP.md: three fused-overlay
> refinements on the Item 43/45 surface — (1) a `bad_pair` review kind offered
> only in fused view (click an over-merged fused id → its members must land in
> ≥2 fused ids; wire review.py + observations schema + fusion_eval scoring),
> (2) a traceable fused display label from the members' last-three oid digits
> (sensor omitted) kept separate from the integer `fused_id`, and (3)
> display-only interpolation of persistence/anchor drop gaps rendered as
> visibly filled-in points. Confirm the ID-format open decision first. pytest
> the model helpers; land the DESIGN_HISTORY entry.

---

## 48 — Physical-Plausibility Stitching Heuristics (Target: Fable) — needs Item 42

Two stitching constraints the owner flagged as **future improvements** to the
fusion engine (2026-07-14) — captured now as a concrete item, lower urgency
than Item 47. Both are physical priors that should tighten bridging/association
decisions in `model/fusion.py` without breaking the refuse-don't-guess
character. Correctness-critical engine work → Fable, per the fusion-engine
precedent (Items 42/46).

Scope:
- [ ] **No pass-through.** Two distinct objects cannot cross the same point at
      the same time along opposing/converging paths — encode this as a veto so
      a bridge/association that would require one tracked object to pass
      *through* another (their interpolated paths intersect at coincident time)
      is refused. Decide the geometric test (segment-crossing within a time
      window) and where it sits relative to the existing gap/spatial gates.
- [ ] **No co-occupancy / minimum separation ⇒ same object.** Two objects
      cannot occupy the same space; enforce a minimum separation — **especially
      in the direction of travel** (a following-headway gap, so the test is
      anisotropic: tighter along-track than cross-track). Two tracks closer than
      that separation over a sustained window are the **same object** and should
      merge; genuinely distinct vehicles keeping lawful headway must not.
      Decide the separation thresholds (along-track vs. cross-track, in feet)
      and the sustained-overlap window.
- [ ] Wire both as `FusionParams`-tunable gates (named constants with the
      owner's physical rationale in the module doc), composing with — not
      bypassing — the existing bridge/association and fixpoint logic (Item 46's
      stitch↔fuse fixpoint). Keep every gate refuse-on-ambiguity.
- [ ] pytest: adversarial cases for each — a would-be bridge that requires a
      pass-through is refused; two lane-adjacent vehicles at lawful headway stay
      distinct while two co-located fragments merge — plus a full-suite +
      `fusion_eval.py` regression run (no eval regressions vs. the 44/50
      baseline; report any bucket movement). DESIGN_HISTORY entry; check off
      this item.

Suggested prompt:
> [Fable] In EVO/iprj_designer, do Item 48 of ROADMAP.md: add two
> physical-plausibility gates to `model/fusion.py` — (1) no pass-through (refuse
> a bridge/association whose paths would cross a second object at coincident
> time) and (2) an anisotropic minimum-separation rule (tighter along the
> direction of travel) where sustained co-occupancy means *same object* → merge,
> while lawful-headway neighbors stay distinct. Wire both as FusionParams gates
> composing with Item 46's fixpoint, keep refuse-on-ambiguity, and pytest the
> adversarial cases with no fusion_eval regression against 44/50.

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
  for legacy captures that never recorded one. Robustness to a stale/edited
  iprj (partial zone matching + outlier rejection) is scoped as Item 36 above.
