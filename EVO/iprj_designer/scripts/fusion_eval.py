"""Score the fusion engine against the owner's manual stitching observations.

Reads tests/fixtures/stitch_observations_2026-07-13.json (five real captures
under sites/, hand-watched in the designer replay), runs ``model.fusion.fuse``
on each capture exactly the way the GUI does (parse_recording -> auto ``Z;``
zonefit alignment -> ``autocalibrate`` self-calibration, 2026-07-14 round ->
calibrated=True when the solve trusted a sensor), and reports per-group
verdicts:

  handoff/persistence  all members must share ONE fused id (recall), and that
                       fused track must not contain members of a *different*
                       labeled group (contamination = precision failure).
  unsure               not gated; the engine's verdict is printed so the owner
                       can confirm or reject it.
  anchor               a track that correctly persisted through a stop; it
                       must not absorb any same-sensor raw id beyond itself
                       (cross-sensor fusion of the same vehicle is fine).
  stray                must not merge with anything.

``fused_refs`` (small integers the owner wrote that match no raw oid; believed
to be fused-view ids) are resolved against this run and printed for manual
validation only.

Run from the repo root:  .venv/bin/python EVO/iprj_designer/scripts/fusion_eval.py

``--obs <file>`` scores an alternate observations JSON in the same schema —
in particular one saved by the designer's in-GUI review labeling
(Overlay › Replay › review, 2026-07-14 round), so new hand-labeled sessions
feed straight into this harness. ``--no-autocal`` skips the self-calibration
pre-pass and reproduces the earlier uncalibrated (widened-gate) runs.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

DESIGNER = Path(__file__).resolve().parents[1]
ROOT = DESIGNER.parents[1]
sys.path.insert(0, str(DESIGNER))

from model.fusion import DEFAULT_PARAMS, fuse  # noqa: E402
from model.iprj_io import load_iprj  # noqa: E402
from model.replay import autocalibrate, parse_recording  # noqa: E402
from model.units import m_to_ft  # noqa: E402

OBS = DESIGNER / "tests/fixtures/stitch_observations_2026-07-13.json"


def read_text(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", errors="replace") as f:
            return f.read()
    return path.read_text(errors="replace")


def load_capture(entry: dict):
    """Parse the capture through the best-fitting candidate iprj (the one
    whose ``Z;`` zonefit matches the most stream slots, ties by residual)."""
    text = read_text(ROOT / entry["recording"])
    best = None
    for cand in entry["iprj_candidates"]:
        try:
            project = load_iprj(ROOT / cand)
            rec = parse_recording(project, text, max_frames=None)
        except Exception as e:  # noqa: BLE001 - report and try the next iprj
            print(f"    [iprj {cand}: {type(e).__name__}: {e}]")
            continue
        fit = rec.zone_fit
        score = (len(fit.slot_to_sensor), -fit.mean_residual_ft) if fit \
            else (0, 0.0)
        if best is None or score > best[0]:
            best = (score, cand, project, rec)
    if best is None:
        raise RuntimeError("no candidate iprj parsed")
    return best[1], best[2], best[3]


def calibration_note(rec) -> str:
    """One-line per-sensor summary of an ``autocalibrate`` solve, for the
    capture header (empty when the pre-pass didn't run or trusted nothing)."""
    cal = rec.alignment.calibration if rec.alignment is not None else None
    if cal is None:
        return ""
    parts = []
    for s in cal.sensors:
        if s.status == "reference":
            parts.append(f"s{s.sensor}=ref")
        elif s.status in ("ok", "translation_only"):
            d_ft = m_to_ft(math.hypot(s.delta.d_x, s.delta.d_y))
            parts.append(f"s{s.sensor}={s.delta.theta_deg:+.2f}deg/"
                         f"{d_ft:.1f}ft({s.n_pairs}p,"
                         f"res{m_to_ft(s.mean_residual_m):.0f}ft)")
        else:
            parts.append(f"s{s.sensor}={s.status}({s.n_pairs}p"
                         + (f",res{m_to_ft(s.mean_residual_m):.0f}ft)"
                            if s.mean_residual_m is not None else ")"))
    return ", autocal " + " ".join(parts)


def evaluate(params=DEFAULT_PARAMS, verbose: bool = True,
             obs_path: Path = OBS, autocal: bool = True) -> dict:
    obs = json.loads(Path(obs_path).read_text())
    totals = defaultdict(int)
    results: dict[str, list[dict]] = {}
    for name, entry in obs["captures"].items():
        iprj, project, rec = load_capture(entry)
        if autocal:
            rec = autocalibrate(project, rec)
        # the GUI's own "did calibration happen" test (Viewer.ensure_fusion)
        calibrated = bool(rec.alignment is not None and rec.alignment.calib)
        result = fuse(rec.frames, calibrated=calibrated, params=params)
        id_of = result.id_of
        by_fid = {tr.fused_id: tr for tr in result.tracks}
        # every labeled member -> its group index, for contamination checks
        owner_of: dict[tuple[int, int], int] = {}
        stray_members: set[tuple[int, int]] = set()
        for gi, g in enumerate(entry["groups"]):
            for m in g["members"]:
                owner_of[tuple(m)] = gi
                if g["kind"] == "stray":
                    stray_members.add(tuple(m))
        if verbose:
            fitnote = ""
            if rec.zone_fit:
                fitnote = (f", zonefit {len(rec.zone_fit.slot_to_sensor)} "
                           f"slots / {rec.zone_fit.mean_residual_ft:.1f} ft")
            fitnote += calibration_note(rec)
            print(f"\n== {name}  ({iprj}{fitnote}; "
                  f"{len(result.tracks)} fused tracks"
                  f"{', LOW CONFIDENCE' if result.low_confidence else ''})")
        cap_results = []
        for gi, g in enumerate(entry["groups"]):
            members = [tuple(m) for m in g["members"]]
            kind = g["kind"]
            missing = [m for m in members if m not in id_of]
            fids = sorted({id_of[m] for m in members if m in id_of})
            # raw ids sharing those fused tracks but labeled to another group
            # an absorbed labeled-stray inside a real group is dedup, not
            # contamination (it shadowed that vehicle to begin with)
            contamination = sorted(
                m for f in fids for m in by_fid[f].members
                if owner_of.get(m, gi) != gi
                and not (kind != "stray" and m in stray_members))
            extras = sorted(
                m for f in fids for m in by_fid[f].members
                if m not in members)
            unsure = g.get("unsure", False)
            if kind in ("handoff", "persistence"):
                ok = not missing and len(fids) == 1 and not contamination
                bucket = "unsure" if unsure else kind
                if not unsure:
                    totals[f"{bucket}_total"] += 1
                    totals[f"{bucket}_ok"] += ok
            elif kind == "anchor":
                same_sensor_extras = [
                    m for m in extras if m[0] == members[0][0]]
                ok = not missing and not same_sensor_extras
                totals["anchor_total"] += 1
                totals["anchor_ok"] += ok
            else:  # stray: "flagged" and "absorbed into a host" are both
                # acceptable (no phantom object survives either way);
                # standing as its own non-stray track is the failure
                kinds = {by_fid[f].kind for f in fids}
                if missing:
                    ok = False
                elif kinds == {"stray"}:
                    ok = True
                    totals["stray_flagged"] += 1
                elif extras:
                    ok = True
                    totals["stray_absorbed"] += 1
                else:
                    ok = False  # standalone phantom
                totals["stray_total"] += 1
                totals["stray_ok"] += ok
            status = "OK  " if ok else "MISS"
            if unsure:
                status = "?   "
            if verbose:
                mem = " ".join(f"{s}/{o}" for s, o in members)
                line = f"  {status} {kind:<11} [{mem}] -> fused {fids}"
                if missing:
                    line += f"  MISSING {missing}"
                if len(fids) > 1:
                    line += "  SPLIT"
                if contamination:
                    line += f"  CONTAMINATED by {contamination}"
                elif extras and kind in ("stray", "anchor"):
                    line += f"  extras {extras}"
                if g.get("note") and (not ok or unsure):
                    line += f"\n        ({g['note']})"
                print(line)
            cap_results.append(dict(
                group=gi, kind=kind, unsure=unsure, ok=ok, fids=fids,
                missing=missing, extras=extras, contamination=contamination))
        # resolve the owner's fused_refs against this run
        if verbose:
            for g in entry["groups"]:
                for ref in g.get("fused_refs", []):
                    tr = by_fid.get(ref)
                    if tr is None:
                        print(f"  fused_ref {ref}: no such fused id this run")
                        continue
                    mem = " ".join(f"{s}/{o}" for s, o in tr.members)
                    print(f"  fused_ref {ref}: kind={tr.kind} members [{mem}] "
                          f"t {tr.points[0].t_s:.1f}..{tr.points[-1].t_s:.1f}")
        results[name] = cap_results
    if verbose:
        print("\n== totals")
        for bucket in ("handoff", "persistence", "anchor", "stray"):
            t = totals[f"{bucket}_total"]
            if t:
                print(f"  {bucket:<11} {totals[f'{bucket}_ok']}/{t}")
    return dict(totals=dict(totals), results=results)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--obs", type=Path, default=OBS,
                    help="observations JSON to score (default: the 2026-07-13 "
                         "fixture; also accepts files saved by the in-GUI "
                         "review labeling)")
    ap.add_argument("--no-autocal", action="store_true",
                    help="skip the self-calibration pre-pass (reproduces the "
                         "uncalibrated widened-gate runs)")
    args = ap.parse_args()
    evaluate(obs_path=args.obs, autocal=not args.no_autocal)
