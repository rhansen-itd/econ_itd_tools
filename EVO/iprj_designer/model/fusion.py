"""Track stitching + cross-sensor fusion — one trajectory per real vehicle.

ROADMAP Item 42, implementing FUSION_PLAN.md (Item 41). A pure batch
transform over the aligned ``Frame`` stream (Item 29): fold the frames into
per-source raw tracks, bridge within-sensor stop/drop/resume gaps (plan §3),
then associate cross-sensor tracks that coincide in time and space (plan §4),
emitting a ``FusionResult`` the render layer consumes without re-running the
engine. Clean-room per plan §1: no pandas/scipy/shapely, no ``gates.json``,
no RBF warp, no learned path templates — only the prior art's tuned constants
survive, converted to feet/seconds and pinned by the §6 acceptance gates.

Two decisions the plan left to this item, resolved here:

* **Direction comes from displacement, not the ``heading`` field.** On the
  real ``86_US95&SH8`` fixture the stream's per-point heading spans only
  −0.2..0.7 across 82k points of traffic moving every compass direction — it
  is not a usable bearing, whatever it encodes. The §3 forward cone therefore
  uses the end-of-track *velocity vector* (displacement over the trailing
  ``velocity_window_s``), which is also what "extrapolated velocity over the
  gap" needs anyway.
* **Overlap points blend by overlap fraction** (the prior art's safe default,
  plan's open item): in the shared window the earlier track's samples are the
  spine, each paired to the later track's nearest-in-time sample and lerped
  by window fraction, so the fused polyline hands off smoothly instead of
  jumping at either sensor's edge. Later-track samples falling in an
  earlier-track dropout are kept as-is; the rest are consumed by the blend
  (dedup — one point per moment).

Refuse-don't-guess (plan §3, the zonefit/calibration discipline): a bridge
happens only when the candidate is the *unique* best for both endpoints by a
score margin — two comparably-plausible successors (the queue-area
fragmentation this fixture is full of) leave the track split, because a
fabricated merge is worse downstream than an honest fragment. Cross-sensor
association is greedy best-pair, one partner per track per pass; chains
(A→B→C, or a three-source vehicle) form through re-runs to fixpoint, each
step individually gated.

Batch only (plan §5): ``fuse`` consumes a complete ``list[Frame]``; the live
path stays raw. The streaming variant is a documented future upgrade that
must reuse this scoring, not copy it.

The 2026-07-13 observation round (owner's hand-labeled handoff/persistence/
stray groups across five captures — tests/fixtures/stitch_observations_
2026-07-13.json, scored by scripts/fusion_eval.py) added five mechanisms,
each pinned by those labels:

* **Vendor-combined seams.** Slot ``oid%10 >= 4`` is the sensor's own fusion
  output: when the vendor decides two sensors' objects are one vehicle it
  retires BOTH raw ids and continues under a freshly allocated id + 4
  (623980 -> 623984; slot 4 = sensor 0's counter, slot 5 = sensor 1's),
  cls 0, starting the frame after its members end — zero temporal overlap,
  so the §4 overlap association can never see it. ``_vendor_seam_merge``
  joins each combined track to the raw tracks that die at its birth
  (≤ ``seam_dt_s``, ≤ ``seam_d_ft``); the merged accumulator inherits its
  members' real sensor sets, which doubles as a don't-merge constraint (two
  concurrent vendor-combined vehicles both own {0,1} and can no longer
  cross-associate).
* **Parked resume.** A queued vehicle drops at a red and re-acquires 30-60 s
  later a few feet away — beyond the stopped window. When the successor
  starts within ``d_parked_ft`` of the end point, the gap may run to
  ``t_max_parked_s``, guarded by velocity agreement and an **occupancy
  veto**: if any other track parked on that spot during the gap, the queue
  flushed and refilled, so refuse. (The phase-status bits in the F; header
  could gate this more directly; the occupancy veto gets the same protection
  site-agnostically and is the documented v1 choice.)
* **Re-label bridges.** A sensor re-labels an object with a brief double-
  tracked handover (≤ ``relabel_overlap_s`` overlap): bridge candidates
  tolerate that small negative gap, gated tight (``relabel_d_ft``, velocity
  agreement). Bridging is also no longer same-sensor-only — a cross-sensor
  handoff with a blind-spot gap uses the same kinematic gates.
* **Duplicate absorption.** A same-sensor twin that lives ≥70 % of its life
  beside a longer track (sensor double-tracking: truck birth twins, the
  fragments a walking pedestrian sheds) is absorbed into it, blended by the
  §4 overlap machinery. Motorized twins need clear velocity agreement while
  moving; slow fragments need a non-motorized partner — two *stopped* queued
  cars never qualify.
Two sensor behaviors the owner described (2026-07-13) that explain the data
and bound future work: beyond ~200 ft the device is doppler radar, so slow/
stopped objects legitimately drop (why parked resume exists — and why drops
cluster at queue tails far from the sensor; close in, side-fire tracking
holds objects well). And an object can "stick": a moving object freezes at a
spot (multipath off signs/mast arms) and holds until another object drives
through it, while the real vehicle usually leaves under a new oid.

* **Stuck-ghost tail trimming (2026-07-14 round).** The follow-up delivered:
  ``_split_stuck_tails`` detects the freeze-onset kinematics — a track still
  reading ≥ ``stuck_v_fast_ft_s`` across the onset boundary *and* over the
  trailing window that then holds one spot (``stuck_hold_r_ft``) to its
  death — and splits the frozen tail off before any matching. No real
  vehicle stops from 10 mph inside one sample (a braking car decays through
  many; the rejection bound works out to ~0.9 g at the hold radius), and the
  double gate also rejects a parked car's single-sample position hop. The
  tail surfaces as a ``kind="ghost"`` fused track — dimmed on screen, never
  deleted, its ``id_of`` entry staying with the live head — and can no
  longer poison bridge candidacies, cross-sensor association, or the
  parked-resume occupancy veto (untrimmed, a stick parked on a queue spot
  absorbed the real vehicle's whole trajectory; see the pytest control
  case). FIFO queue-order matching for same-lane resumes the endpoint gates
  can't separate remains the documented follow-up.

* **Flicker veto + stitch↔fuse fixpoint (2026-07-14 calibrated-eval round).**
  Self-calibrated frames (``model.replay.autocalibrate``) surfaced two
  association-order defects the widened uncalibrated gate had been masking:
  a single-sample blip on a queue spot "reads stopped" and used to *bridge*
  onto the vehicle acquired there seconds later (poisoning its sensor set
  against the true cross-sensor partner) — now a track with the stray
  module's own non-object shape (``_Track.flicker``) is refused as either
  bridge endpoint; and a red-light gap seen by both sensors is UNbridgeable
  at the raw stage (every endpoint has two comparably-close successor
  views, so the ambiguity margin rightly refuses) yet trivially unique once
  association has merged each side's views — so ``fuse`` now alternates
  ``_stitch_to_fixpoint`` with the association passes to a joint fixpoint
  instead of stitching once. Both pinned by the observation set: 41/50 →
  43/50 uncalibrated, 44/50 self-calibrated, no regressions either mode.

Render-side helpers, separate from the engine's geometry: ``smooth_seams``
(2026-07-14) returns a display copy with each multi-member track's points
eased near its cross-source seams — the GUI feeds ``fused_frame_markers``
from it so a handoff glides on screen while the cached ``FusionResult``
stays exact — and ``fused_frame_markers`` itself (Item 43) indexes fused
points per frame. Hand-labeling of what *should* fuse now happens in the
GUI's review mode (``model/review.py``), saving the observations schema
``scripts/fusion_eval.py --obs`` scores.

* **Behavioral pedestrians + strays.** Class comes from the track's
  *majority* report (the stream flips between 30 and 10 mid-track), and a
  track that travels ≥ ``ped_net_ft`` without ever beating walking pace is
  non-motorized whatever the vendor said (the 43 s "cls 30" pedestrian).
  After all merging, ``kind="stray"`` flags what the owner called shadows:
  sub-second flickers that go nowhere, and short-lived tracks that ride
  within ``shadow_d_ft`` of a much longer concurrent companion moving the
  same way (a truck's radar ghost on both sensors). Nothing is deleted —
  the render layer dims/skips them.

Calibration (plan §4b): cross-sensor matching assumes the Items 38–40
calibrated overlay and a tight ``d_fine_ft`` gate. The caller states
``calibrated=`` explicitly; an uncalibrated stream widens the gate by
``d_fine_uncal_factor`` and any cross-sensor merge made that way flags the
whole result ``low_confidence`` rather than silently passing. Within-sensor
stitching needs no calibration and always runs. Since the 2026-07-14
calibrated-eval round the batch consumers (``Viewer.ensure_fusion``,
``scripts/fusion_eval.py``) self-calibrate an uncalibrated recording first
via ``model.replay.autocalibrate`` — the relational solve over the stream's
own vehicle pairs — so the tight gate is the common case and the widened
path is the guardrail fallback, not the default.

Everything is frozen dataclasses + plain Python, pytestable headless, like
``replay.py``/``zonefit.py``/``calibration.py``.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .replay import Frame

# --- tuned constants (plan §1, prior-art values converted to ft/s) -----------
# Starting values lifted from ../fusion_visualizer.py and re-checked against
# the calibrated 86_US95&SH8 fixture (§6 gate); d_fine_ft is opened slightly
# from the prior art's 16 ft because the real fixture's uncalibratable extra
# slots (4/5, too few pairs -> refused by design) ride ~17 ft off their
# same-vehicle sensor-0 partners.

_NON_MOTORIZED = frozenset({10, 15, 20})  # pedestrian/bike classes
_MOTORIZED_MIN = 25


@dataclass(frozen=True)
class FusionParams:
    """Every gate in one frozen bag so tests can pin/tune deliberately."""

    # §3 within-sensor bridging
    t_max_moving_s: float = 5.0
    t_max_stopped_s: float = 30.0
    d_max_moving_ft: float = 98.0
    d_max_stopped_ft: float = 66.0
    min_velocity_ft_s: float = 3.3
    cone_half_angle_deg: float = 60.0
    reach_factor: float = 1.5  # dist <= speed*gap*factor + slack, moving only
    reach_slack_ft: float = 15.0
    velocity_window_s: float = 1.0  # trailing window for the end velocity
    ambiguity_margin: float = 0.25  # min score gap to call a best "unique"
    # §4 cross-sensor association
    d_fine_ft: float = 20.0
    d_fine_uncal_factor: float = 2.0  # widened gate when calibrated=False
    min_overlap_samples: int = 3
    dt_match_s: float = 0.25  # nearest-in-time pairing tolerance (~2 frames)
    # vendor-combined seam joining (slots >= 4; observation round)
    seam_dt_s: float = 0.5
    seam_d_ft: float = 10.0        # same-frame continuation: tight
    seam_d_other_ft: float = 35.0  # a *different* sensor's member may ride
    # the inter-sensor offset plus 1-2-point acquisition noise (worst when
    # one slot is calibrated and the 4/5 slot could not be)
    # parked resume (red-light queue drop; observation round)
    t_max_parked_s: float = 90.0
    d_parked_ft: float = 20.0
    occupancy_r_ft: float = 10.0  # the occupancy veto's "that spot" radius
    occupancy_min_s: float = 1.5  # parked this long during the gap -> veto
    occupancy_min_pts: int = 5
    parked_lateral_w: float = 3.0  # lateral-offset weight in parked scoring:
    # queue-mates in the next lane sit a small *lateral* distance away, the
    # true resume sits along the lane — weigh lateral error accordingly
    # re-label bridge (brief double-tracked handover; observation round)
    relabel_overlap_s: float = 1.0
    relabel_d_ft: float = 22.0
    relabel_vagree: float = 0.6
    # same-sensor duplicate absorption (observation round)
    dup_overlap_frac: float = 0.7
    dup_max_len_s: float = 8.0
    dup_sep_ft: float = 22.0
    dup_margin_ft: float = 3.0
    dup_vagree: float = 0.6
    dup_slow_ft_s: float = 9.0  # "slow" partner cap for ped-fragment absorbs
    # behavioral pedestrian override (observation round)
    ped_pct95_ft_s: float = 9.5  # never beats walking pace ...
    ped_net_ft: float = 50.0     # ... yet actually travels ...
    ped_min_dur_s: float = 8.0   # ... for long enough to mean it
    speed_window_s: float = 0.5  # smoothing window for per-sample speeds
    # stuck-ghost tail trimming (2026-07-14 round; the Item 44 follow-up).
    # A multipath "stick" freezes a moving object instantly: speed collapses
    # from stuck_v_fast_ft_s to zero inside one sample, physically implausible
    # braking (>= ~0.9 g would still take over a second from 10 mph, sampled
    # ~10x along the way) — a real queued car decelerates through many frames
    # and never trips the gate. The frozen tail must hold one spot to the
    # track's end; the moving head must be a genuine trajectory.
    stuck_hold_r_ft: float = 4.0    # frozen-tail jitter radius
    stuck_min_hold_s: float = 3.0   # frozen at least this long
    stuck_v_fast_ft_s: float = 15.0  # window speed right before the freeze
    stuck_head_net_ft: float = 30.0  # the head must have really traveled
    stuck_head_min_s: float = 1.0
    # stray flagging (observation round; never deletes, only labels)
    stray_dur_s: float = 1.2
    stray_net_ft: float = 25.0
    shadow_dur_s: float = 8.0
    shadow_d_ft: float = 45.0
    shadow_len_ratio: float = 2.5
    shadow_cover: float = 0.6
    shadow_cover_slow: float = 0.8  # when the track's own net is too small
    shadow_net_ft: float = 15.0     # ... to test direction alignment
    shadow_valign: float = 0.7


DEFAULT_PARAMS = FusionParams()


# --- time seam (plan §2, fixes prior-art F3) ---------------------------------


def parse_time_s(t: str) -> float:
    """``"HH:MM:SS.mmm"`` → seconds since midnight, the one place the
    wall-clock string becomes a number. Raises ValueError on garbage — the
    frame fold skips such frames instead of guessing."""
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


# --- raw-track fold (plan §2's internal working unit) ------------------------


@dataclass(frozen=True)
class RawTrack:
    """One source object's whole trajectory: the ``(sensor, oid)``-keyed fold
    of the frame stream, in world feet and numeric seconds."""

    sensor: int
    oid: int
    cls: int | None  # majority classified (non-None) report over the track
    points: tuple[tuple[float, float, float], ...]  # (t_s, x_ft, y_ft)

    @property
    def key(self) -> tuple[int, int]:
        return (self.sensor, self.oid)


def frame_times_s(frames: Sequence[Frame]) -> list[float]:
    """Per-frame numeric seconds, aligned 1:1 with *frames* (``nan`` where the
    stamp won't parse), unwrapping across midnight the same way ``fold_tracks``
    reads the stream (a stamp dropping >12 h from the previous frame is the next
    day). This is the shared time seam the batch fold and the render-side
    per-frame marker index (Item 43) both build on, so a fused point and its
    frame agree on the clock."""
    out: list[float] = []
    offset, prev = 0.0, None
    for f in frames:
        try:
            t = parse_time_s(f.t) + offset
        except ValueError:
            out.append(math.nan)
            continue
        if prev is not None and t < prev - 12 * 3600:
            offset += 24 * 3600
            t += 24 * 3600
        prev = t
        out.append(t)
    return out


def fold_tracks(frames: Iterable[Frame]) -> tuple[RawTrack, ...]:
    """Fold aligned frames into per-``(sensor, oid)`` raw tracks.

    Times unwrap across midnight (see ``frame_times_s``); frames with an
    unparseable stamp are skipped. Ordered by (first time, key) so everything
    downstream is deterministic."""
    frames = list(frames)
    times = frame_times_s(frames)
    pts: dict[tuple[int, int], list[tuple[float, float, float]]] = {}
    cls: dict[tuple[int, int], dict[int, int]] = {}
    for f, t in zip(frames, times):
        if math.isnan(t):
            continue
        for p in f.points:
            k = (p.sensor, p.oid)
            pts.setdefault(k, []).append((t, p.x_ft, p.y_ft))
            if p.cls is not None:
                c = cls.setdefault(k, {})
                c[p.cls] = c.get(p.cls, 0) + 1
    # majority class, not first-seen: the stream flips a pedestrian between
    # 30 and 10 mid-track (632500 opens as 30 for 23 points, then 10 for 78)
    tracks = [
        RawTrack(
            sensor=k[0], oid=k[1],
            cls=max(cls[k], key=cls[k].__getitem__) if k in cls else None,
            points=tuple(v))
        for k, v in pts.items()
    ]
    tracks.sort(key=lambda tr: (tr.points[0][0], tr.key))
    return tuple(tracks)


def _class_category(cls: int | None) -> str | None:
    """The §3 compatibility divide: non-motorized (10/15/20) never bridges or
    fuses to motorized (≥25). Anything else — None, and the real stream's
    cls 0 on its extra slots — is unknown and compatible with both."""
    if cls is None:
        return None
    if cls in _NON_MOTORIZED:
        return "non_motor"
    if cls >= _MOTORIZED_MIN:
        return "motor"
    return None


# --- results (plan §2's output contract) --------------------------------------


@dataclass(frozen=True)
class FusedPoint:
    """One fused-trajectory sample; ``src`` names the raw track(s) it came
    from (two when the point is a cross-sensor overlap blend)."""

    t_s: float
    x_ft: float
    y_ft: float
    src: tuple[tuple[int, int], ...]  # contributing (sensor, oid) keys


@dataclass(frozen=True)
class FusedTrack:
    fused_id: int
    members: tuple[tuple[int, int], ...]  # (sensor, oid), in join order
    points: tuple[FusedPoint, ...]  # time-ordered, overlap-deduped
    # "ghost" = a trimmed stuck-tail (2026-07-14): its raw track's live head
    # is a separate track and owns the id_of entry for the shared member key
    kind: str  # "single" | "stitched" | "fused" | "stray" | "ghost"
    # majority-class + behavioral category ("motor" | "non_motor" | None):
    # the render layer symbolizes non-motorized tracks differently
    category: str | None = None


@dataclass(frozen=True)
class FusionResult:
    tracks: tuple[FusedTrack, ...]
    id_of: Mapping[tuple[int, int], int]  # raw (sensor, oid) → fused id
    calibrated: bool  # what the caller declared
    # True when a cross-sensor merge was accepted through the widened
    # uncalibrated gate (§4b): usable, but flagged — never silent.
    low_confidence: bool


# --- internal working track ---------------------------------------------------

# a working point: (t_s, x_ft, y_ft, src)
_P = tuple[float, float, float, tuple[tuple[int, int], ...]]


class _Track:
    """Mutable merge accumulator; everything public is frozen."""

    __slots__ = ("members", "sensors", "cat", "points", "cls_n",
                 "pct95_v", "median_v", "net_ft", "_params")

    def __init__(self, raw: RawTrack, params: FusionParams | None = None) -> None:
        self.members: list[tuple[int, int]] = [raw.key]
        self.sensors: set[int] = {raw.sensor}
        self.points: list[_P] = [
            (t, x, y, (raw.key,)) for t, x, y in raw.points]
        # point-weighted class votes; merged accumulators sum them
        self.cls_n: dict[int | None, int] = {raw.cls: len(raw.points)}
        self._params = params or DEFAULT_PARAMS
        self.reclassify()

    @property
    def t0(self) -> float:
        return self.points[0][0]

    @property
    def t1(self) -> float:
        return self.points[-1][0]

    @property
    def dur(self) -> float:
        return self.t1 - self.t0

    def reclassify(self) -> None:
        """Recompute speed stats + category from the current points/votes.

        Category is the majority class pushed through ``_class_category``,
        with the behavioral pedestrian override: a track that travels
        ``ped_net_ft`` without its (smoothed) speed ever reaching the 95th-
        percentile walking cap is non-motorized whatever the vendor labeled
        it (the 2_85 capture reports a pedestrian as cls 30 for 43 s)."""
        p = self._params
        pts = self.points
        spds: list[float] = []
        j = 0
        for i in range(len(pts)):
            while pts[i][0] - pts[j][0] > p.speed_window_s:
                j += 1
            dt = pts[i][0] - pts[j][0]
            if dt > 0:
                spds.append(math.hypot(
                    pts[i][1] - pts[j][1], pts[i][2] - pts[j][2]) / dt)
        spds.sort()
        self.pct95_v = spds[int(0.95 * (len(spds) - 1))] if spds else 0.0
        self.median_v = spds[len(spds) // 2] if spds else 0.0
        self.net_ft = math.hypot(
            pts[-1][1] - pts[0][1], pts[-1][2] - pts[0][2])
        votes = {c: n for c, n in self.cls_n.items() if c is not None}
        cat = _class_category(
            max(votes, key=votes.__getitem__) if votes else None)
        if cat == "motor" and self.ped_like:
            cat = "non_motor"
        self.cat = cat

    @property
    def ped_like(self) -> bool:
        p = self._params
        return (self.pct95_v <= p.ped_pct95_ft_s
                and self.net_ft >= p.ped_net_ft
                and self.dur >= p.ped_min_dur_s)

    @property
    def flicker(self) -> bool:
        """The stray-flagging module's own non-object shape (sub-second and
        going nowhere), reused as a bridge-candidacy veto (2026-07-14,
        calibrated-eval round): one or two radar blips carry no identity, so
        letting one *anchor* a stopped/parked bridge fabricates a merge — the
        observed case is a single-sample blip on a queue spot bridging onto
        the next vehicle acquired there 14 s later, poisoning its sensor set
        against the true cross-sensor partner. Refused as either endpoint;
        the blip stands alone and the stray pass flags it as usual."""
        p = self._params
        return self.dur < p.stray_dur_s and self.net_ft < p.stray_net_ft

    def compatible(self, other: _Track) -> bool:
        a, b = self.cat, other.cat
        return a is None or b is None or a == b

    def absorb_stats(self, other: _Track) -> None:
        """Fold *other*'s class votes in and re-derive stats/category from
        the (already merged) points — call after every points merge.

        ``non_motor`` is sticky: blending an absorbed fragment's jitter into
        the points can push the recomputed speed stats past the walking cap,
        but absorbing a fragment must not turn a pedestrian into a car."""
        keep = "non_motor" if "non_motor" in (self.cat, other.cat) else None
        for c, n in other.cls_n.items():
            self.cls_n[c] = self.cls_n.get(c, 0) + n
        self.reclassify()
        self.cat = keep or self.cat

    def end_velocity(self, window_s: float) -> tuple[float, float, float]:
        """(vx, vy, speed) over the trailing *window_s* — the displacement
        direction the §3 cone uses (the stream's heading field is unusable;
        see module doc). Degenerate tails (one sample, zero dt) read as
        stopped, which routes them to the safe circular search."""
        tail_t0 = self.t1 - window_s
        i = bisect_left([p[0] for p in self.points], tail_t0)
        return _velocity(self.points[min(i, len(self.points) - 1):])

    def start_velocity(self, window_s: float) -> tuple[float, float, float]:
        """Leading-window twin of ``end_velocity``, for the successor side of
        the §3 direction gate."""
        head_t1 = self.t0 + window_s
        i = bisect_right([p[0] for p in self.points], head_t1)
        return _velocity(self.points[:max(i, 2)])


def _velocity(pts: list[_P]) -> tuple[float, float, float]:
    dt = pts[-1][0] - pts[0][0]
    if len(pts) < 2 or dt <= 0:
        return 0.0, 0.0, 0.0
    vx = (pts[-1][1] - pts[0][1]) / dt
    vy = (pts[-1][2] - pts[0][2]) / dt
    return vx, vy, math.hypot(vx, vy)


# --- stuck-ghost tail trimming (2026-07-14 round; Item 44 follow-up) -----------


def _stuck_onset(
    points: Sequence[tuple[float, float, float]], p: FusionParams,
) -> int | None:
    """Index where a moving track froze into a stuck-ghost tail, else None.

    The tail is the maximal suffix holding within ``stuck_hold_r_ft`` of the
    track's final point; it must run ``stuck_min_hold_s`` to the track's end
    (a stick holds until the track dies — a car that resumes was parked, not
    stuck). The freeze must be *physically implausible*: the instantaneous
    speed across the onset boundary AND the net displacement speed over the
    trailing ``velocity_window_s`` both still read ≥ ``stuck_v_fast_ft_s``
    at the moment the object is suddenly holding still. A braking car decays
    through many samples first — even emergency braking arrives at the
    4-ft hold radius under ~13 ft/s (v² = 2·a·r puts the rejection bound at
    a ≈ 28 ft/s², ~0.9 g) — while a multipath stick freezes from full speed
    inside one sample. The double gate also rejects single-sample position
    spikes (big boundary step, near-zero net window displacement). The head
    must be a genuine trajectory (net + duration floors), so a stationary
    object is never split."""
    n = len(points)
    if n < 4:
        return None
    tx, ty = points[-1][1], points[-1][2]
    k = n - 1
    while k > 0 and math.hypot(
            points[k - 1][1] - tx, points[k - 1][2] - ty) <= p.stuck_hold_r_ft:
        k -= 1
    if k < 2 or k > n - 2:
        return None  # frozen from birth (stationary object) or no real tail
    if points[-1][0] - points[k][0] < p.stuck_min_hold_s:
        return None
    head = points[:k]
    if head[-1][0] - head[0][0] < p.stuck_head_min_s:
        return None
    if math.hypot(head[-1][1] - head[0][1],
                  head[-1][2] - head[0][2]) < p.stuck_head_net_ft:
        return None
    # instantaneous speed across the onset boundary
    dt = points[k][0] - points[k - 1][0]
    if dt <= 0 or math.hypot(points[k][1] - points[k - 1][1],
                             points[k][2] - points[k - 1][2]) / dt \
            < p.stuck_v_fast_ft_s:
        return None
    # net displacement speed over the trailing window into the freeze
    w0 = points[k][0] - p.velocity_window_s
    i = bisect_left([q[0] for q in head], w0)
    i = min(i, k - 1)
    wdt = points[k][0] - points[i][0]
    if wdt <= 0 or math.hypot(points[k][1] - points[i][1],
                              points[k][2] - points[i][2]) / wdt \
            < p.stuck_v_fast_ft_s:
        return None
    return k


def _split_stuck_tails(
    raws: Sequence[RawTrack], p: FusionParams,
) -> tuple[list[RawTrack], list[RawTrack]]:
    """Split every stuck-ghost tail off its raw track before any matching.

    Returns ``(live, ghost_tails)``: the live tracks (frozen tails trimmed)
    enter the pipeline as usual; the tails are kept aside and surface as
    ``kind="ghost"`` fused tracks — visible but dimmed, never deleted — and,
    critically, they can no longer poison bridge candidacies, cross-sensor
    association, or the parked-resume occupancy veto (the real vehicle
    usually leaves the stick under a new oid; module doc)."""
    live: list[RawTrack] = []
    ghosts: list[RawTrack] = []
    for r in raws:
        k = _stuck_onset(r.points, p)
        if k is None:
            live.append(r)
        else:
            live.append(RawTrack(r.sensor, r.oid, r.cls, r.points[:k]))
            ghosts.append(RawTrack(r.sensor, r.oid, r.cls, r.points[k:]))
    return live, ghosts


# --- vendor-combined seams (observation round) ---------------------------------


def _vendor_seam_merge(tracks: list[_Track], p: FusionParams) -> list[_Track]:
    """Join each vendor-combined track (slot ``oid % 10 >= 4``) to the raw
    tracks that die at its birth.

    The vendor's own fusion retires both raw ids and continues the object
    under the fresh ``+4`` id the very next frame (module doc), so the
    members are exactly the tracks whose last point falls within
    ``seam_dt_s`` before and ``seam_d_ft`` of the combined track's first
    point.  The accumulator inherits its members' real sensor sets — which
    both lets it keep fusing correctly downstream and *blocks* association
    with any concurrent vehicle that also owns both sensors."""
    combined = sorted(
        (t for t in tracks if t.members[0][0] % 10 >= 4),
        key=lambda t: t.t0)
    dead: set[int] = set()
    for c in combined:
        t0 = c.t0
        _, x0, y0, _ = c.points[0]
        cvx, cvy, cspeed = c.start_velocity(p.velocity_window_s)

        def moves_with(t: _Track) -> bool:
            """The retired member's end motion may not oppose the combined
            track's start motion (a pedestrian coincidentally dying 8 ft
            from a vehicle-combined birth is the observed false seam)."""
            vx, vy, speed = t.end_velocity(p.velocity_window_s)
            if speed < p.min_velocity_ft_s or cspeed < p.min_velocity_ft_s:
                return True  # unreadable: don't invent a veto
            return (vx * cvx + vy * cvy) / (speed * cspeed) >= -0.2

        ending = [
            (math.hypot(t.points[-1][1] - x0, t.points[-1][2] - y0), t)
            for t in tracks
            if id(t) not in dead and t is not c
            and t0 - p.seam_dt_s <= t.t1 < t0 and moves_with(t)]
        # tight radius for the direct continuation; a member from a sensor
        # not already seen at the seam may ride the inter-sensor offset
        members = [t for d, t in ending if d <= p.seam_d_ft]
        seen = {s for t in members for s in t.sensors}
        for d, t in sorted(ending, key=lambda e: e[0]):
            if p.seam_d_ft < d <= p.seam_d_other_ft \
                    and not (t.sensors & seen):
                members.append(t)
                seen |= t.sensors
        if not members:
            continue
        merged: list[_P] = []
        for m in members:
            merged.extend(m.points)
            c.members = m.members + c.members
            c.sensors |= m.sensors
            dead.add(id(m))
        merged.sort(key=lambda q: (q[0], q[3]))
        c.points = merged + c.points
        for m in members:
            c.absorb_stats(m)
    return [t for t in tracks if id(t) not in dead]


# --- same-sensor duplicate absorption (observation round) -----------------------


def _absorb_duplicates(tracks: list[_Track], p: FusionParams) -> list[_Track]:
    """Absorb same-sensor concurrent twins into the longer track they shadow.

    A sensor sometimes double-tracks one object: a second id that lives
    ``dup_overlap_frac`` of its life inside a longer track's span, riding
    within ``dup_sep_ft`` of it.  Two flavors, both unique-best gated:

    * moving twins — both clearly moving with agreeing velocities (a truck's
      birth twin, a re-acquisition that converged);
    * slow fragments — a non-motorized partner plus a slow companion (the
      short ids a walking pedestrian sheds).  Two *stopped* queued cars never
      qualify: neither is non-motorized and their velocities are unreadable.

    Points blend through the §4 overlap machinery, so the absorbed twin
    dedups instead of zigzagging."""
    while True:
        cands: list[tuple[float, int, int]] = []
        by_t0 = sorted(range(len(tracks)), key=lambda i: tracks[i].t0)
        for pos, si in enumerate(by_t0):
            s = tracks[si]
            for li in by_t0:
                l = tracks[li]  # noqa: E741 - longer partner
                if li == si or l.dur <= s.dur or s.sensors != l.sensors:
                    continue
                ovl = min(s.t1, l.t1) - max(s.t0, l.t0)
                if ovl < p.dup_overlap_frac * s.dur or ovl <= 0:
                    continue
                ped_frag = (
                    (s.cat == "non_motor" or l.cat == "non_motor")
                    and s.median_v <= p.dup_slow_ft_s
                    and l.median_v <= p.dup_slow_ft_s)
                if s.dur > p.dup_max_len_s and not ped_frag:
                    continue
                n, meansep = _overlap_stats(s, l, p.dt_match_s)
                if n < p.min_overlap_samples or meansep > p.dup_sep_ft:
                    continue
                # velocity condition over the shared window; the slow-
                # fragment flavor skips the class gate deliberately — the
                # vendor labels the fragments a pedestrian sheds cls 30
                w0, w1 = max(s.t0, l.t0), min(s.t1, l.t1)
                sv = _window_velocity(s, w0, w1)
                lv = _window_velocity(l, w0, w1)
                if ped_frag:
                    pass  # slow fragment beside a pedestrian-like track
                elif (s.compatible(l)
                      and sv[2] >= p.min_velocity_ft_s
                      and lv[2] >= p.min_velocity_ft_s
                      and (sv[0] * lv[0] + sv[1] * lv[1])
                      / (sv[2] * lv[2]) >= p.dup_vagree):
                    pass  # moving twin with agreeing velocity
                else:
                    continue
                cands.append((meansep, si, li))
        if not cands:
            return tracks
        # unique-best per shorter track, margin-gated; disjoint per pass
        best: dict[int, list[tuple[float, int]]] = {}
        for meansep, si, li in cands:
            best.setdefault(si, []).append((meansep, li))
        used: set[int] = set()
        dead: set[int] = set()
        for si, opts in best.items():
            opts.sort()
            if len(opts) > 1 and opts[1][0] - opts[0][0] < p.dup_margin_ft:
                continue  # two plausible hosts: refuse, don't guess
            li = opts[0][1]
            if si in used or li in used:
                continue
            _merge_overlapping(tracks[li], tracks[si], p.dt_match_s)
            used.update((si, li))
            dead.add(si)
        if not dead:
            return tracks
        tracks = [t for i, t in enumerate(tracks) if i not in dead]


def _window_velocity(t: _Track, w0: float, w1: float) -> tuple[float, float, float]:
    """Displacement velocity of *t* over the [w0, w1] time window."""
    pts = [q for q in t.points if w0 <= q[0] <= w1]
    return _velocity(pts) if len(pts) >= 2 else (0.0, 0.0, 0.0)


# --- §3 within-sensor gap-bridging --------------------------------------------


def _spot_occupied(
    tracks: list[_Track], a: _Track, b: _Track,
    x: float, y: float, t_lo: float, t_hi: float, p: FusionParams,
) -> bool:
    """The parked-resume occupancy veto: did any *other* track park within
    ``occupancy_r_ft`` of (x, y) during (t_lo, t_hi)?  If so the queue
    flushed and refilled — the resume candidate is a different vehicle."""
    for t in tracks:
        if t is a or t is b or t.t1 <= t_lo or t.t0 >= t_hi:
            continue
        times = [q[0] for q in t.points]
        near = [q[0] for q in t.points[
            bisect_right(times, t_lo):bisect_left(times, t_hi)]
            if math.hypot(q[1] - x, q[2] - y) <= p.occupancy_r_ft]
        if (len(near) >= p.occupancy_min_pts
                and near[-1] - near[0] >= p.occupancy_min_s):
            return True
    return False


def _stitch_candidates(
    tracks: list[_Track], p: FusionParams,
) -> list[tuple[float, int, int]]:
    """All individually-plausible (score, end_track, start_track) bridges.

    Since the observation round, candidates are no longer same-sensor-only
    (a cross-sensor handoff with a blind-spot gap passes the same kinematic
    gates), and two regimes join the moving/stopped pair:

    * **re-label** (gap in (-relabel_overlap_s, 0]): the sensor re-labeled
      the object with a brief double-tracked handover; gate on the distance
      between A's end and B's concurrent sample plus velocity agreement.
    * **parked resume** (dist <= d_parked_ft): a queued vehicle re-acquired
      on the same spot may bridge up to t_max_parked_s, with the occupancy
      veto and velocity agreement instead of the (meaningless) cone.
    """
    order = sorted(range(len(tracks)), key=lambda i: tracks[i].t0)
    starts = [tracks[i].t0 for i in order]
    cos_cone = math.cos(math.radians(p.cone_half_angle_deg))
    out: list[tuple[float, int, int]] = []
    for ai, a in enumerate(tracks):
        if a.flicker:
            continue
        vx, vy, speed = a.end_velocity(p.velocity_window_s)
        stopped = speed < p.min_velocity_ft_s
        t_max = p.t_max_stopped_s if stopped else p.t_max_moving_s
        d_max = p.d_max_stopped_ft if stopped else p.d_max_moving_ft
        _, ax, ay, _ = a.points[-1]
        lo = bisect_right(starts, a.t1 - p.relabel_overlap_s)
        hi = bisect_right(starts, a.t1 + max(t_max, p.t_max_parked_s))
        for oi in order[lo:hi]:
            b = tracks[oi]
            if oi == ai or b.flicker or not a.compatible(b):
                continue
            gap = b.t0 - a.t1
            if gap <= -p.relabel_overlap_s or b.t1 <= a.t1:
                continue
            bvx, bvy, bspeed = b.start_velocity(p.velocity_window_s)
            vagree = ((vx * bvx + vy * bvy) / (speed * bspeed)
                      if speed > 0 and bspeed > 0 else math.nan)
            if gap <= 0:
                # re-label handover: B was born in A's final moments; judge
                # by where B sat when A died, not by B's (earlier) start
                bi = bisect_left([q[0] for q in b.points], a.t1)
                bt, bx, by, _ = b.points[min(bi, len(b.points) - 1)]
                dist = math.hypot(bx - ax, by - ay)
                if (dist > p.relabel_d_ft
                        or speed < p.min_velocity_ft_s
                        or bspeed < p.min_velocity_ft_s
                        or not vagree >= p.relabel_vagree):
                    continue
                out.append((-gap / p.relabel_overlap_s
                            + dist / p.relabel_d_ft, ai, oi))
                continue
            bt, bx, by, _ = b.points[0]
            dist = math.hypot(bx - ax, by - ay)
            if dist <= p.d_parked_ft and gap <= p.t_max_parked_s:
                # parked resume: same spot, so direction/reach are noise —
                # require non-opposing velocities when both are readable,
                # and that nobody else parked here in the meantime
                if speed >= p.min_velocity_ft_s \
                        and bspeed >= p.min_velocity_ft_s and vagree < 0.0:
                    continue
                if gap > p.t_max_moving_s and _spot_occupied(
                        tracks, a, b, ax, ay, a.t1, b.t0, p):
                    continue
                # score with the lateral offset (w.r.t. B's resume
                # direction) weighted up: the true resume is along the
                # lane, the next lane's queue-mate is beside it
                d_eff = dist
                if bspeed >= p.min_velocity_ft_s:
                    along = abs((bx - ax) * bvx + (by - ay) * bvy) / bspeed
                    lat = abs(-(bx - ax) * bvy + (by - ay) * bvx) / bspeed
                    d_eff = along + p.parked_lateral_w * lat
                out.append((gap / p.t_max_parked_s
                            + d_eff / p.d_parked_ft, ai, oi))
                continue
            if gap > t_max or dist > d_max:
                continue
            if not stopped:
                # forward cone + extrapolated reach (plan §3, moving only)
                if dist > 1.0:  # same-spot resume: direction is meaningless
                    cos = ((bx - ax) * vx + (by - ay) * vy) / (dist * speed)
                    if cos < cos_cone:
                        continue
                if dist > speed * gap * p.reach_factor + p.reach_slack_ft:
                    continue
                # direction consistency: the successor's own initial motion
                # must also lie in the cone — the real fixture showed a
                # position-only cone happily bridging onto an oncoming
                # vehicle whose start point sat ahead of A (module doc).
                if bspeed >= p.min_velocity_ft_s and vagree < cos_cone:
                    continue
            out.append((gap / t_max + dist / d_max, ai, oi))
    return out


def _unique_best_pairs(
    cands: list[tuple[float, int, int]], margin: float,
) -> list[tuple[int, int]]:
    """The refuse-don't-guess filter: keep (a, b) only when it is the best
    bridge for *a*'s end AND for *b*'s start, each by at least *margin* over
    the runner-up. Accepted pairs are disjoint by construction (a second pair
    sharing an endpoint would contradict that endpoint's unique best)."""
    by_a: dict[int, list[float]] = {}
    by_b: dict[int, list[float]] = {}
    for s, a, b in cands:
        by_a.setdefault(a, []).append(s)
        by_b.setdefault(b, []).append(s)

    def unique(scores: list[float], s: float) -> bool:
        others = sorted(scores)
        return s == others[0] and (len(others) == 1 or others[1] - s >= margin)

    return [(a, b) for s, a, b in sorted(cands)
            if unique(by_a[a], s) and unique(by_b[b], s)]


def _stitch_to_fixpoint(tracks: list[_Track], p: FusionParams) -> list[_Track]:
    """Bridge unique-best gaps, re-running so chains (A→B→C) form one
    individually-gated step at a time (plan §3)."""
    while True:
        pairs = _unique_best_pairs(
            _stitch_candidates(tracks, p), p.ambiguity_margin)
        if not pairs:
            return tracks
        # accepted pairs share no endpoint, but they may chain (A→B and B→C
        # in one pass, distinct endpoints): walk each chain from its head so
        # every fragment lands in the surviving track
        succ = dict(pairs)
        dead = set()
        for head in [a for a in succ if a not in set(succ.values())]:
            h, cur = tracks[head], head
            while cur in succ:
                cur = succ[cur]
                b = tracks[cur]
                h.points.extend(b.points)
                h.members.extend(b.members)
                h.sensors |= b.sensors
                h.absorb_stats(b)
                dead.add(cur)
            # a re-label bridge overlaps by <= relabel_overlap_s, so the
            # concatenation isn't sorted there; restore time order
            h.points.sort(key=lambda q: (q[0], q[3]))
        tracks = [t for i, t in enumerate(tracks) if i not in dead]


# --- §4 cross-sensor association ----------------------------------------------


def _overlap_stats(
    a: _Track, b: _Track, dt_match: float,
) -> tuple[int, float]:
    """(n_matched, mean_separation_ft) over the tracks' shared time window,
    pairing each sample of the sparser-in-window track to the other's
    nearest-in-time sample — tolerant windows, never exact equality (the
    prior art's F3)."""
    t0, t1 = max(a.t0, b.t0), min(a.t1, b.t1)
    if t1 < t0:
        return 0, math.inf
    aw = [q for q in a.points if t0 <= q[0] <= t1]
    bw = [q for q in b.points if t0 <= q[0] <= t1]
    if len(bw) < len(aw):
        aw, bw = bw, aw
    if not aw or not bw:
        return 0, math.inf
    bt = [q[0] for q in bw]
    dists = []
    for t, x, y, _ in aw:
        i = bisect_left(bt, t)
        best = min(
            (abs(bt[j] - t), j) for j in (i - 1, i) if 0 <= j < len(bw))
        if best[0] <= dt_match:
            q = bw[best[1]]
            dists.append(math.hypot(x - q[1], y - q[2]))
    if not dists:
        return 0, math.inf
    return len(dists), sum(dists) / len(dists)


def _merge_overlapping(a: _Track, b: _Track, dt_match: float) -> None:
    """Fuse *b* into *a*: blend-by-overlap-fraction dedup in the shared
    window, pass-through outside it (plan §4a; policy in module doc)."""
    e, l = (a, b) if (a.t0, a.points[0][3]) <= (b.t0, b.points[0][3]) else (b, a)
    t0, t1 = l.t0, min(a.t1, b.t1)
    span = t1 - t0
    ew = [q for q in e.points if t0 <= q[0] <= t1]
    lw = [q for q in l.points if t0 <= q[0] <= t1]
    lt = [q[0] for q in lw]

    merged: list[_P] = [q for q in e.points if q[0] < t0]
    used = set()
    for t, x, y, src in ew:
        i = bisect_left(lt, t)
        near = [(abs(lt[j] - t), j) for j in (i - 1, i, i + 1)
                if 0 <= j < len(lw) and j not in used]
        j = min(near)[1] if near and min(near)[0] <= dt_match else None
        if j is None:
            merged.append((t, x, y, src))
            continue
        used.add(j)
        _, lx, ly, lsrc = lw[j]
        w = (t - t0) / span if span > 0 else 0.5
        merged.append((t, x * (1 - w) + lx * w, y * (1 - w) + ly * w,
                       src + lsrc))
    # later-track samples in an earlier-track dropout survive; the rest were
    # the blend's partners or near-duplicates of a spine sample (deduped)
    et = [q[0] for q in ew]
    for j, (t, x, y, src) in enumerate(lw):
        if j in used:
            continue
        i = bisect_left(et, t)
        near = min((abs(et[k] - t) for k in (i - 1, i) if 0 <= k < len(et)),
                   default=math.inf)
        if near > dt_match:
            merged.append((t, x, y, src))
    tail = a if a.t1 >= b.t1 else b
    merged.extend(q for q in tail.points if q[0] > t1)
    merged.sort(key=lambda q: (q[0], q[3]))

    a.members.extend(b.members)
    a.sensors |= b.sensors
    a.points = merged
    a.absorb_stats(b)


def _fuse_pass(
    tracks: list[_Track], p: FusionParams, d_fine: float,
) -> tuple[list[_Track], int]:
    """One greedy association pass: best (smallest mean distance, longest
    overlap) pairs first, each track at most one partner per pass (plan §4a).
    Returns the surviving tracks and how many merges happened."""
    cands: list[tuple[float, int, int, int]] = []
    order = sorted(range(len(tracks)), key=lambda i: tracks[i].t0)
    starts = [tracks[i].t0 for i in order]
    for pos, ai in enumerate(order):
        a = tracks[ai]
        for bi in order[pos + 1: bisect_right(starts, a.t1)]:
            b = tracks[bi]
            if a.sensors & b.sensors or not a.compatible(b):
                continue
            n, mean = _overlap_stats(a, b, p.dt_match_s)
            if n >= p.min_overlap_samples and mean < d_fine:
                cands.append((mean, -n, ai, bi))
    used: set[int] = set()
    survivors: list[_Track | None] = list(tracks)
    merges = 0
    for mean, negn, ai, bi in sorted(
            cands, key=lambda c: (c[0], c[1], tracks[c[2]].members[0],
                                  tracks[c[3]].members[0])):
        if ai in used or bi in used:
            continue
        _merge_overlapping(tracks[ai], tracks[bi], p.dt_match_s)
        used.update((ai, bi))  # one partner per track per pass
        survivors[bi] = None  # b now lives inside a
        merges += 1
    return [t for t in survivors if t is not None], merges


# --- stray flagging (observation round) ----------------------------------------


def _is_stray(t: _Track, tracks: list[_Track], p: FusionParams) -> bool:
    """After all merging: is this leftover track a non-object?

    Two owner-named shapes: a flicker (sub-``stray_dur_s`` and going
    nowhere), and a radar shadow — a short-lived track riding within
    ``shadow_d_ft`` of a much longer concurrent companion moving the same
    way (trucks cast them, especially through the corner).  Real short
    tracks survive because they merged into something long before this
    runs."""
    if t.dur < p.stray_dur_s and t.net_ft < p.stray_net_ft:
        return True
    if t.dur > p.shadow_dur_s:
        return False
    for c in tracks:
        if c is t or c.dur < p.shadow_len_ratio * max(t.dur, 1e-9):
            continue
        if c.t1 <= t.t0 or c.t0 >= t.t1:
            continue
        ct = [q[0] for q in c.points]
        matched = 0
        for q in t.points:
            i = bisect_left(ct, q[0])
            near = [j for j in (i - 1, i) if 0 <= j < len(ct)
                    and abs(ct[j] - q[0]) <= 0.5]
            if near and min(
                    math.hypot(q[1] - c.points[j][1], q[2] - c.points[j][2])
                    for j in near) <= p.shadow_d_ft:
                matched += 1
        cover = matched / len(t.points)
        if t.net_ft >= p.shadow_net_ft:
            if cover < p.shadow_cover:
                continue
            cv = _window_velocity(c, t.t0, t.t1)
            tv = _velocity(t.points)
            if cv[2] > 0 and tv[2] > 0 and (
                    cv[0] * tv[0] + cv[1] * tv[1]) / (cv[2] * tv[2]) \
                    >= p.shadow_valign:
                return True
        elif cover >= p.shadow_cover_slow:
            return True
    return False


# --- the engine ---------------------------------------------------------------


def fuse(
    frames: Iterable[Frame],
    *,
    calibrated: bool,
    params: FusionParams = DEFAULT_PARAMS,
) -> FusionResult:
    """Batch-fuse a complete aligned frame stream (plan §5).

    ``calibrated`` is the caller's statement about the overlay the frames
    came through (Items 38–40): when False the cross-sensor gate widens by
    ``d_fine_uncal_factor`` and any merge accepted that way marks the result
    ``low_confidence`` (plan §4b) — within-sensor stitching is unaffected.
    Pure and deterministic; never raises on degenerate content (an empty or
    single-sensor stream simply yields no cross-sensor merges)."""
    p = params
    raws, ghost_tails = _split_stuck_tails(fold_tracks(frames), p)
    tracks = [_Track(r, p) for r in raws]
    tracks = _vendor_seam_merge(tracks, p)
    # absorb before stitching so loose duplicate fragments can't win (or
    # ambiguity-poison) bridge candidacies meant for their hosts; the
    # sticky non_motor rule in absorb_stats keeps the hosts' behavioral
    # category intact through the blend
    tracks = _absorb_duplicates(tracks, p)

    # stitch <-> associate to a joint fixpoint (2026-07-14, calibrated-eval
    # round): a queue gap can be UNbridgeable at the raw stage — each side of
    # a red light is seen by both sensors, so every endpoint has two
    # comparably-close successor views and the ambiguity margin (rightly)
    # refuses — yet trivially unique once cross-sensor association has merged
    # each side's views into one composite track. One stitch pass before the
    # first association keeps plan §3's behavior; re-running after each
    # association round lets composites bridge. Merges strictly shrink the
    # track list, so the loop terminates.
    d_fine = p.d_fine_ft * (1.0 if calibrated else p.d_fine_uncal_factor)
    cross_merges = 0
    while True:
        n0 = len(tracks)
        tracks = _stitch_to_fixpoint(tracks, p)
        while True:
            tracks, merges = _fuse_pass(tracks, p, d_fine)
            cross_merges += merges
            if merges == 0:
                break
        if len(tracks) == n0:
            break

    tracks.sort(key=lambda t: (t.t0, t.members[0]))
    fused: list[FusedTrack] = []
    id_of: dict[tuple[int, int], int] = {}
    for i, t in enumerate(tracks, start=1):
        kind = ("stray" if _is_stray(t, tracks, p)
                else "single" if len(t.members) == 1
                else "fused" if len(t.sensors - {4, 5, 6, 7}) > 1
                else "stitched")
        fused.append(FusedTrack(
            fused_id=i,
            members=tuple(t.members),
            points=tuple(FusedPoint(*q) for q in t.points),
            kind=kind,
            category=t.cat,
        ))
        for m in t.members:
            id_of[m] = i
    # trimmed stuck-ghost tails: rendered (dimmed) but outside the pipeline;
    # the member key's id_of entry stays with its live head, set above
    for g in sorted(ghost_tails, key=lambda r: (r.points[0][0], r.key)):
        fused.append(FusedTrack(
            fused_id=len(fused) + 1,
            members=(g.key,),
            points=tuple(FusedPoint(t, x, y, (g.key,))
                         for t, x, y in g.points),
            kind="ghost",
            category=None,
        ))
        id_of.setdefault(g.key, fused[-1].fused_id)
    return FusionResult(
        tracks=tuple(fused),
        id_of=id_of,
        calibrated=calibrated,
        low_confidence=(not calibrated and cross_merges > 0),
    )


# --- render-side seam smoothing (2026-07-14 round) -----------------------------

SEAM_SMOOTH_S = 1.0  # default centered-average window at a handoff seam


def smooth_seams(
    result: FusionResult, window_s: float = SEAM_SMOOTH_S,
) -> FusionResult:
    """A render-side copy of *result* with each multi-member track's points
    smoothed near its **seams** — the cross-sensor overlap blends (points with
    more than one ``src``) and the joints where consecutive points switch
    source (a bridge / handoff boundary). Points within *window_s* of a seam
    are replaced by the centered average of the samples inside ±window_s/2;
    everything else — and every single-member/stray/ghost track — passes
    through untouched, so the engine's geometry stays the source of truth and
    only the on-screen handoff is eased. Times, sources, ids, and membership
    are preserved exactly; pure and deterministic."""
    if window_s <= 0:
        return result
    half = window_s / 2.0
    out: list[FusedTrack] = []
    for tr in result.tracks:
        if len(tr.members) < 2 or len(tr.points) < 3:
            out.append(tr)
            continue
        pts = tr.points
        times = [q.t_s for q in pts]
        seams: list[float] = [q.t_s for q in pts if len(q.src) > 1]
        seams.extend(
            t for a, b in zip(pts, pts[1:]) if a.src != b.src
            for t in (a.t_s, b.t_s))
        if not seams:
            out.append(tr)
            continue
        seams.sort()
        new_pts = list(pts)
        lo = hi = 0
        for i, q in enumerate(pts):
            j = bisect_left(seams, q.t_s)
            near = min((abs(seams[k] - q.t_s) for k in (j - 1, j)
                        if 0 <= k < len(seams)), default=math.inf)
            if near > window_s:
                continue
            while times[lo] < q.t_s - half:
                lo += 1
            hi = max(hi, i)
            while hi + 1 < len(times) and times[hi + 1] <= q.t_s + half:
                hi += 1
            n = hi - lo + 1
            new_pts[i] = FusedPoint(
                q.t_s,
                sum(p.x_ft for p in pts[lo:hi + 1]) / n,
                sum(p.y_ft for p in pts[lo:hi + 1]) / n,
                q.src)
        out.append(FusedTrack(tr.fused_id, tr.members, tuple(new_pts),
                              tr.kind, tr.category))
    return FusionResult(tuple(out), result.id_of, result.calibrated,
                        result.low_confidence)


# --- render-side per-frame index (Item 43) ------------------------------------


def fused_frame_markers(
    result: FusionResult,
    frame_times: Sequence[float],
) -> tuple[dict[int, tuple[float, float]], ...]:
    """Per-frame ``{fused_id: (x_ft, y_ft)}`` — the overlay's index for showing
    *fused* tracks (Item 43): **one marker per real vehicle per frame**, the
    fused counterpart to a raw frame's per-sensor points.

    Each fused-track point is assigned to the frame whose time is nearest
    (``frame_times`` is ``frame_times_s(frames)``, so a fused point and its
    origin frame share one clock). A track contributing two points to one frame
    keeps the time-nearest, so the cross-sensor dedup the engine already did in
    the overlap window is preserved on screen rather than re-splitting into two
    markers. The result is a tuple aligned 1:1 with *frame_times* (an empty dict
    for a frame with no stamp or no active fused track). Pure and deterministic,
    like the rest of the engine — the render layer reads it without re-fusing."""
    n = len(frame_times)
    valid_t: list[float] = []
    valid_i: list[int] = []
    for i, t in enumerate(frame_times):
        if not math.isnan(t):
            valid_t.append(t)
            valid_i.append(i)
    out: tuple[dict[int, tuple[float, float]], ...] = tuple({} for _ in range(n))
    best: list[dict[int, float]] = [{} for _ in range(n)]
    for tr in result.tracks:
        for pt in tr.points:
            j = bisect_left(valid_t, pt.t_s)
            cand = [k for k in (j - 1, j) if 0 <= k < len(valid_t)]
            if not cand:
                continue
            k = min(cand, key=lambda c: abs(valid_t[c] - pt.t_s))
            fi = valid_i[k]
            d = abs(valid_t[k] - pt.t_s)
            if tr.fused_id not in best[fi] or d < best[fi][tr.fused_id]:
                best[fi][tr.fused_id] = d
                out[fi][tr.fused_id] = (pt.x_ft, pt.y_ft)
    return out
