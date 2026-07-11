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

Calibration (plan §4b): cross-sensor matching assumes the Items 38–40
calibrated overlay and a tight ``d_fine_ft`` gate. The caller states
``calibrated=`` explicitly; an uncalibrated stream widens the gate by
``d_fine_uncal_factor`` and any cross-sensor merge made that way flags the
whole result ``low_confidence`` rather than silently passing. Within-sensor
stitching needs no calibration and always runs.

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
    cls: int | None  # first classified (non-None) report
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
    cls: dict[tuple[int, int], int | None] = {}
    for f, t in zip(frames, times):
        if math.isnan(t):
            continue
        for p in f.points:
            k = (p.sensor, p.oid)
            pts.setdefault(k, []).append((t, p.x_ft, p.y_ft))
            if cls.get(k) is None:
                cls[k] = p.cls
    tracks = [
        RawTrack(sensor=k[0], oid=k[1], cls=cls[k], points=tuple(v))
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
    kind: str  # "single" | "stitched" | "fused"


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

    __slots__ = ("members", "sensors", "cat", "points")

    def __init__(self, raw: RawTrack) -> None:
        self.members: list[tuple[int, int]] = [raw.key]
        self.sensors: set[int] = {raw.sensor}
        self.cat = _class_category(raw.cls)
        self.points: list[_P] = [
            (t, x, y, (raw.key,)) for t, x, y in raw.points]

    @property
    def t0(self) -> float:
        return self.points[0][0]

    @property
    def t1(self) -> float:
        return self.points[-1][0]

    def compatible(self, other: _Track) -> bool:
        a, b = self.cat, other.cat
        return a is None or b is None or a == b

    def absorb_cat(self, other: _Track) -> None:
        self.cat = self.cat or other.cat

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


# --- §3 within-sensor gap-bridging --------------------------------------------


def _stitch_candidates(
    tracks: list[_Track], p: FusionParams,
) -> list[tuple[float, int, int]]:
    """All individually-plausible (score, end_track, start_track) bridges."""
    order = sorted(range(len(tracks)), key=lambda i: tracks[i].t0)
    starts = [tracks[i].t0 for i in order]
    cos_cone = math.cos(math.radians(p.cone_half_angle_deg))
    out: list[tuple[float, int, int]] = []
    for ai, a in enumerate(tracks):
        vx, vy, speed = a.end_velocity(p.velocity_window_s)
        stopped = speed < p.min_velocity_ft_s
        t_max = p.t_max_stopped_s if stopped else p.t_max_moving_s
        d_max = p.d_max_stopped_ft if stopped else p.d_max_moving_ft
        _, ax, ay, _ = a.points[-1]
        lo = bisect_right(starts, a.t1)
        hi = bisect_right(starts, a.t1 + t_max)
        for oi in order[lo:hi]:
            b = tracks[oi]
            if oi == ai or b.sensors != a.sensors or not a.compatible(b):
                continue
            gap = b.t0 - a.t1
            if gap <= 0:
                continue
            bt, bx, by, _ = b.points[0]
            dist = math.hypot(bx - ax, by - ay)
            if dist > d_max:
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
                bvx, bvy, bspeed = b.start_velocity(p.velocity_window_s)
                if bspeed >= p.min_velocity_ft_s:
                    cos = (bvx * vx + bvy * vy) / (bspeed * speed)
                    if cos < cos_cone:
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
                h.points.extend(b.points)  # each starts after the last ends
                h.members.extend(b.members)
                h.absorb_cat(b)
                dead.add(cur)
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
    a.absorb_cat(b)
    a.points = merged


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
    tracks = [_Track(r) for r in fold_tracks(frames)]
    tracks = _stitch_to_fixpoint(tracks, p)

    d_fine = p.d_fine_ft * (1.0 if calibrated else p.d_fine_uncal_factor)
    cross_merges = 0
    while True:
        tracks, merges = _fuse_pass(tracks, p, d_fine)
        cross_merges += merges
        if merges == 0:
            break

    tracks.sort(key=lambda t: (t.t0, t.members[0]))
    fused: list[FusedTrack] = []
    id_of: dict[tuple[int, int], int] = {}
    for i, t in enumerate(tracks, start=1):
        kind = ("single" if len(t.members) == 1
                else "fused" if len(t.sensors) > 1 else "stitched")
        fused.append(FusedTrack(
            fused_id=i,
            members=tuple(t.members),
            points=tuple(FusedPoint(*q) for q in t.points),
            kind=kind,
        ))
        for m in t.members:
            id_of[m] = i
    return FusionResult(
        tracks=tuple(fused),
        id_of=id_of,
        calibrated=calibrated,
        low_confidence=(not calibrated and cross_merges > 0),
    )


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
