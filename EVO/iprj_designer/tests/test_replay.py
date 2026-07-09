"""Playback engine tests (ROADMAP Item 29).

Alignment is asserted against the real 86_US95&SH8 site fixture (read-only,
as always). The recording itself is synthetic but format-faithful — built
line-for-line to evo_recorder.py's output grammar — because no real EVO
capture survives on disk or in git history (evo_replay.py's DEFAULT_DATA is
gone). The cross-check test pins our transform to legacy evo_replay's
semantics on identical input, so when a real capture is next taken the two
renderers must agree by construction.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from model import units
from model.iprj_io import Background, Project, Sensor, load_iprj
from model.replay import (
    SENSOR_COLORS,
    LiveAligner,
    anchor_world_ft,
    load_recording,
    marker_color,
    parse_recording,
    short_id,
)

SITES = Path(__file__).resolve().parents[3] / "sites"
EVO_REPLAY_PY = Path(__file__).resolve().parents[2] / "evo_replay.py"

# EVO-frame reference (the C; line) and two track points at known metric
# offsets from it: point 101 sits exactly on the reference, point 42 sits
# +10 m east / +5 m south of it.
REF = (12.5, -3.75)
RECORDING = f"""\
09:15:02.100
C;{REF[0]},{REF[1]},0.0,extra-fields-ignored
09:15:02.200
F;0;1;2;3;101,7,{REF[0]},{REF[1]},90.0;42,2,{REF[0] + 10.0},{REF[1] + 5.0},180.0
09:15:02.300
F;0;1;2;3;101,7,{REF[0] + 1.0},{REF[1] + 1.0},91.5
09:15:02.400
F;0;1;2;3
"""


@pytest.fixture(scope="module")
def site():
    return load_iprj(SITES / "86_US95&SH8" / "us95&sh8.iprj")


# --- coordinate alignment (the Item 29 correctness pivot) -------------------

def test_ref_point_lands_on_sensor_anchor(site):
    """A track point exactly at the C; reference must land exactly on the
    anchoring sensor's world-feet position."""
    rec = parse_recording(site, RECORDING, sensor_index=0)
    anchor = anchor_world_ft(site, 0)

    emp = units.effective_meter_per_pixel(site.background)
    s = site.sensors[0]
    assert anchor[0] == pytest.approx(units.px_to_ft(s.position_x, emp))
    assert anchor[1] == pytest.approx(units.px_to_ft(s.position_y, emp))

    p101 = rec.frames[0].points[0]
    assert p101.oid == 101
    assert p101.x_ft == pytest.approx(anchor[0], abs=1e-9)
    assert p101.y_ft == pytest.approx(anchor[1], abs=1e-9)


def test_known_metric_offset_converts_via_m_to_ft_only(site):
    """+10 m / +5 m from the reference is +32.8084 ft / +16.4042 ft from the
    anchor — m_to_ft alone, never scaled by meter-per-pixel (plan §1b)."""
    rec = parse_recording(site, RECORDING, sensor_index=0)
    anchor = rec.anchor_ft

    p42 = rec.frames[0].points[1]
    assert p42.x_ft - anchor[0] == pytest.approx(units.m_to_ft(10.0), abs=1e-9)
    assert p42.y_ft - anchor[1] == pytest.approx(units.m_to_ft(5.0), abs=1e-9)

    # Guard that the wrong formula (offset routed through the pixel scale)
    # is actually distinguishable on this site.
    emp = units.effective_meter_per_pixel(site.background)
    assert units.m_to_ft(10.0) != pytest.approx(units.px_to_ft(10.0, emp))


def test_y_is_down_translation_only(site):
    """South (+y in EVO meters) stays +y in world feet: pure translation,
    no sign flip, matching the y-down world frame."""
    rec = parse_recording(site, RECORDING, sensor_index=0)
    p101_f0 = rec.frames[0].points[0]
    p101_f1 = rec.frames[1].points[0]
    assert p101_f1.x_ft > p101_f0.x_ft
    assert p101_f1.y_ft > p101_f0.y_ft


def test_per_sensor_anchor(site):
    """The same stream anchored to sensor 1 shifts rigidly by the anchor
    delta — the transform is per-recording, not hard-wired sensor 0
    (plan §1c)."""
    rec0 = parse_recording(site, RECORDING, sensor_index=0)
    rec1 = parse_recording(site, RECORDING, sensor_index=1)
    a0, a1 = rec0.anchor_ft, rec1.anchor_ft
    assert a0 != a1
    for f0, f1 in zip(rec0.frames, rec1.frames):
        for p0, p1 in zip(f0.points, f1.points):
            assert p1.x_ft - p0.x_ft == pytest.approx(a1[0] - a0[0], abs=1e-9)
            assert p1.y_ft - p0.y_ft == pytest.approx(a1[1] - a0[1], abs=1e-9)


def test_sensor_index_out_of_range(site):
    with pytest.raises(ValueError):
        parse_recording(site, RECORDING, sensor_index=len(site.sensors))
    with pytest.raises(ValueError):
        anchor_world_ft(site, -1)


# --- parsing ----------------------------------------------------------------

def test_parse_structure(site):
    rec = parse_recording(site, RECORDING, sensor_index=0)
    assert rec.sensor_index == 0
    assert rec.ref_m == REF
    assert rec.ref_seen is True
    assert len(rec.frames) == 3

    f0 = rec.frames[0]
    assert f0.t == "09:15:02.200"
    assert [p.oid for p in f0.points] == [101, 42]
    p101, p42 = f0.points
    assert p101.cls == 7 and p42.cls == 2
    assert p101.heading == 90.0
    assert p101.sensor == 101 % 10 and p42.sensor == 42 % 10
    assert (p101.x_raw_m, p101.y_raw_m) == REF

    # An F; line with no entities is a real (empty) playback moment.
    assert rec.frames[2].t == "09:15:02.400"
    assert rec.frames[2].points == ()


def test_first_c_line_wins_and_late_c_still_anchors(site):
    late_c = (
        "09:00:00.000\n"
        "F;0;1;2;3;7,1,5.0,5.0,0.0\n"
        "09:00:00.100\n"
        f"C;{REF[0]},{REF[1]}\n"
        "C;999.0,999.0\n"
    )
    rec = parse_recording(site, late_c, sensor_index=0)
    assert rec.ref_m == REF  # second C; ignored, order-independent anchoring
    p = rec.frames[0].points[0]
    assert p.x_ft - rec.anchor_ft[0] == pytest.approx(units.m_to_ft(5.0 - REF[0]), abs=1e-9)


def test_missing_c_falls_back_to_identity(site):
    """No C; reference -> raw meters treated as anchor-relative, the same
    fallback legacy evo_replay uses."""
    rec = parse_recording(site, "10:00:00.000\nF;0;1;2;3;7,1,3.0,-2.0,0.0\n",
                          sensor_index=0)
    assert rec.ref_seen is False
    assert rec.ref_m == (0.0, 0.0)
    p = rec.frames[0].points[0]
    assert p.x_ft - rec.anchor_ft[0] == pytest.approx(units.m_to_ft(3.0), abs=1e-9)
    assert p.y_ft - rec.anchor_ft[1] == pytest.approx(units.m_to_ft(-2.0), abs=1e-9)


def test_malformed_lines_and_entities_ignored(site):
    noisy = (
        "GetCfg-response-gibberish\n"
        "C;not,numeric\n"
        f"C;{REF[0]},{REF[1]}\n"
        "10:00:00.000\n"
        "F;0;1;2;3;bad,entity;1,2\n"          # unparseable + too-short entities
        "F;0;1;2;3;8,x,1.0,2.0,notafloat\n"   # cls/heading unparseable -> None
    )
    rec = parse_recording(site, noisy, sensor_index=0)
    assert rec.ref_m == REF
    assert len(rec.frames) == 2
    assert rec.frames[0].points == ()
    p = rec.frames[1].points[0]
    assert p.oid == 8 and p.cls is None and p.heading is None


def test_no_track_frames_raises(site):
    with pytest.raises(ValueError):
        parse_recording(site, "10:00:00.000\nC;1.0,2.0\n", sensor_index=0)


def test_load_recording_reads_file(site, tmp_path):
    path = tmp_path / "10_37_2_86_EVO_1770000000.txt"
    path.write_text(RECORDING)
    rec = load_recording(site, path, sensor_index=0)
    assert len(rec.frames) == 3


# --- guardrails (plan §6) ----------------------------------------------------

def _many_frames(n: int, points_per_frame: int = 3) -> str:
    lines = [f"C;{REF[0]},{REF[1]}"]
    for i in range(n):
        ents = ";".join(f"{100 + j},1,{float(i)},{float(j)},0.0"
                        for j in range(points_per_frame))
        lines.append(f"10:00:{i % 60:02d}.000")
        lines.append(f"F;0;1;2;3;{ents}")
    return "\n".join(lines) + "\n"


def test_downsample_and_frame_cap(site):
    text = _many_frames(10)
    rec = parse_recording(site, text, sensor_index=0, downsample_rate=3)
    assert [p.x_raw_m for f in rec.frames for p in f.points[:1]] == [0.0, 3.0, 6.0, 9.0]
    rec = parse_recording(site, text, sensor_index=0, downsample_rate=3, max_frames=2)
    assert len(rec.frames) == 2


def test_points_per_frame_cap(site):
    rec = parse_recording(site, _many_frames(2, points_per_frame=5),
                          sensor_index=0, max_points_per_frame=2)
    assert all(len(f.points) == 2 for f in rec.frames)


def test_default_caps_applied(site):
    from model.replay import DEFAULT_MAX_FRAMES
    assert DEFAULT_MAX_FRAMES is not None
    rec = parse_recording(site, _many_frames(30), sensor_index=0)
    assert len(rec.frames) == 30  # under the cap, untouched


# --- equivalence with legacy evo_replay --------------------------------------

def test_matches_legacy_evo_replay_translation(site, tmp_path):
    """Same synthetic input through legacy evo_replay: both tools must agree
    on every point's metric offset from the sensor anchor. (Absolute
    positions differ by design — evo_replay uses the 2-decimal stored
    MeterPerPixel for its anchor, we use the calibrated scale; plan §1a.)"""
    pytest.importorskip("pandas")
    pytest.importorskip("PIL")
    spec = importlib.util.spec_from_file_location("evo_replay", EVO_REPLAY_PY)
    evo_replay = importlib.util.module_from_spec(spec)
    sys.modules["evo_replay"] = evo_replay  # dataclasses resolve via sys.modules
    spec.loader.exec_module(evo_replay)

    data = tmp_path / "synthetic_EVO.txt"
    data.write_text(RECORDING)
    df, evo_s0 = evo_replay.parse_evo_data(str(data))

    s = site.sensors[0]
    stored = site.background.meter_per_pixel
    cfg = evo_replay.MapConfig(scale=stored,
                               s0_x=s.position_x * stored,
                               s0_y=s.position_y * stored)
    df = evo_replay.align(df, cfg, evo_s0)

    rec = parse_recording(site, RECORDING, sensor_index=0)
    ours = {(p.oid, p.x_raw_m, p.y_raw_m): p
            for f in rec.frames for p in f.points}
    assert len(df) == len(ours)
    for row in df.itertuples(index=False):
        p = ours[(row.ID, row.X_raw, row.Y_raw)]
        assert p.x_ft - rec.anchor_ft[0] == pytest.approx(
            units.m_to_ft(row.X - cfg.s0_x), abs=1e-9)
        assert p.y_ft - rec.anchor_ft[1] == pytest.approx(
            units.m_to_ft(row.Y - cfg.s0_y), abs=1e-9)


# --- streaming LiveAligner (ROADMAP Item 33) ---------------------------------

def _stream(aligner: LiveAligner, text: str) -> list:
    """Feed recorded text one line per feed() call — messages arriving live —
    and collect the emitted frames."""
    frames = []
    for line in text.splitlines():
        f = aligner.feed(line)
        if f is not None:
            frames.append(f)
    return frames


def test_streamed_frames_match_batch_frame_for_frame(site):
    """The Item 33 correctness gate: message-at-a-time streaming must equal
    the batch Recording frame-for-frame — identical aligned coordinates and
    timestamps (frozen dataclasses compare exactly, so this re-pins the §7
    y-sign / no-rotation semantics on the incremental path)."""
    batch = parse_recording(site, RECORDING, sensor_index=0)
    streamed = _stream(LiveAligner(site, sensor_index=0), RECORDING)
    assert streamed == batch.frames


def test_streamed_equivalence_long_stream_other_sensor(site):
    """Same gate on a long C;-once-at-the-top stream, anchored to sensor 1 —
    the one-time reference must keep anchoring for the stream's whole life,
    and the aligner's public state must match the batch Recording's."""
    text = _many_frames(50, points_per_frame=4)
    batch = parse_recording(site, text, sensor_index=1, max_frames=None)
    aligner = LiveAligner(site, sensor_index=1)
    assert _stream(aligner, text) == batch.frames
    assert aligner.ref_m == batch.ref_m
    assert aligner.ref_seen is batch.ref_seen
    assert aligner.anchor_ft == batch.anchor_ft


def test_streamed_noisy_text_matches_batch(site):
    """Garbage, malformed C;, and partial entities stream through with the
    batch parser's exact skip-on-error semantics."""
    noisy = (
        "GetCfg-response-gibberish\n"
        "C;not,numeric\n"
        f"C;{REF[0]},{REF[1]}\n"
        "10:00:00.000\n"
        "F;0;1;2;3;bad,entity;1,2\n"
        "F;0;1;2;3;8,x,1.0,2.0,notafloat\n"
    )
    batch = parse_recording(site, noisy, sensor_index=0)
    aligner = LiveAligner(site, sensor_index=0)
    assert _stream(aligner, noisy) == batch.frames
    assert aligner.ref_m == REF  # malformed C; didn't burn first-one-wins


def test_feed_explicit_t_matches_recorded_time(site):
    """Live messages carry no wall-clock line, so the caller passes t (plan
    §2). Feeding the recorder's ts/message pairs via t= matches the batch on
    time as well as coordinates."""
    batch = parse_recording(site, RECORDING, sensor_index=0)
    aligner = LiveAligner(site, sensor_index=0)
    lines = RECORDING.splitlines()
    streamed = []
    for ts, msg in zip(lines[::2], lines[1::2]):  # recorder: ts line, message
        f = aligner.feed(msg, t=ts)
        if f is not None:
            streamed.append(f)
    assert streamed == batch.frames


def test_feed_non_frame_messages_return_none(site):
    aligner = LiveAligner(site, sensor_index=0)
    assert aligner.feed(f"C;{REF[0]},{REF[1]}") is None
    assert aligner.feed("09:15:02.100") is None
    assert aligner.feed("GetCfg-response-gibberish") is None
    assert aligner.feed("") is None


def test_feed_malformed_never_raises(site):
    """Robustness contract: no message content may raise; state survives."""
    aligner = LiveAligner(site, sensor_index=0)
    garbage = ["", "   ", "C;", "C;not,numeric", "F;", "F;0;1",
               "F;0;1;2;3;bad,entity;1,2", "{\"json\": \"nope\"}", ";;;",
               "99:99", "F;0;1;2;3;,,,,"]
    for msg in garbage:
        out = aligner.feed(msg)
        # A partial F; still yields an (empty) frame, exactly as in batch.
        assert out is None or out.points == ()
    assert aligner.ref_seen is False
    # The aligner still works after the abuse.
    aligner.feed(f"C;{REF[0]},{REF[1]}")
    f = aligner.feed(f"F;0;1;2;3;101,7,{REF[0]},{REF[1]},90.0")
    assert f.points[0].x_ft == pytest.approx(aligner.anchor_ft[0], abs=1e-9)


def test_feed_first_ref_wins(site):
    aligner = LiveAligner(site, sensor_index=0)
    aligner.feed(f"C;{REF[0]},{REF[1]}")
    aligner.feed("C;999.0,999.0")
    assert aligner.ref_m == REF


def test_feed_frame_before_ref_uses_identity_fallback(site):
    """An F; before any C; uses the documented (0, 0) fallback — raw meters
    treated as anchor-relative, the batch default."""
    aligner = LiveAligner(site, sensor_index=0)
    f = aligner.feed("F;0;1;2;3;7,1,3.0,-2.0,0.0")
    assert aligner.ref_seen is False
    p = f.points[0]
    assert p.x_ft - aligner.anchor_ft[0] == pytest.approx(units.m_to_ft(3.0), abs=1e-9)
    assert p.y_ft - aligner.anchor_ft[1] == pytest.approx(units.m_to_ft(-2.0), abs=1e-9)


def test_feed_late_ref_anchors_only_subsequent_frames(site):
    """The documented streaming/batch divergence: the batch whole-file scan
    applies a late C; retroactively, but a stream cannot rewrite frames it
    already emitted — only frames after the reference re-anchor. The real
    feed sends C; up front, so the paths agree on well-formed streams."""
    aligner = LiveAligner(site, sensor_index=0)
    before = aligner.feed("F;0;1;2;3;7,1,5.0,5.0,0.0")
    aligner.feed(f"C;{REF[0]},{REF[1]}")
    after = aligner.feed("F;0;1;2;3;7,1,5.0,5.0,0.0")
    a = aligner.anchor_ft
    assert before.points[0].x_ft - a[0] == pytest.approx(units.m_to_ft(5.0), abs=1e-9)
    assert after.points[0].x_ft - a[0] == pytest.approx(
        units.m_to_ft(5.0 - REF[0]), abs=1e-9)


def test_feed_points_per_frame_cap(site):
    ents = ";".join(f"{100 + j},1,{float(j)},0.0,0.0" for j in range(5))
    aligner = LiveAligner(site, sensor_index=0, max_points_per_frame=2)
    f = aligner.feed(f"F;0;1;2;3;{ents}")
    assert len(f.points) == 2
    # None lifts the cap, as in batch.
    aligner = LiveAligner(site, sensor_index=0, max_points_per_frame=None)
    assert len(aligner.feed(f"F;0;1;2;3;{ents}").points) == 5


def test_feed_multiline_message_keeps_state_returns_last_frame(site):
    """A multi-line message is consumed losslessly for state; the last F;
    frame is the one returned (the render slot is drop-to-latest, plan §3)."""
    batch = parse_recording(site, RECORDING, sensor_index=0)
    aligner = LiveAligner(site, sensor_index=0)
    f = aligner.feed(RECORDING)
    assert f == batch.frames[-1]
    assert aligner.ref_m == REF


def test_live_aligner_sensor_index_validated(site):
    with pytest.raises(ValueError):
        LiveAligner(site, sensor_index=len(site.sensors))
    with pytest.raises(ValueError):
        LiveAligner(site, sensor_index=-1)


# --- marker render helpers (ROADMAP Item 30) --------------------------------

def test_marker_color_matches_evo_replay_palette():
    """The Replay overlay must read the same as legacy evo_replay: cyan/yellow/
    lime/magenta/orange/deepskyblue by sensor (oid % 10)."""
    assert marker_color(0) == "cyan"
    assert marker_color(1) == "yellow"
    assert marker_color(2) == "lime"
    assert marker_color(3) == "magenta"
    assert marker_color(4) == "orange"
    assert marker_color(5) == "deepskyblue"
    # keys are the raw sensor index (oid % 10), as the engine emits.
    assert set(SENSOR_COLORS) == {0, 1, 2, 3, 4, 5}


def test_marker_color_unknown_sensor_falls_back():
    assert marker_color(7) == "white"
    assert marker_color(9) == "white"


def test_short_id_takes_trailing_digits():
    assert short_id(1234567) == "4567"        # default 4 digits
    assert short_id(1234567, 2) == "67"
    assert short_id(5) == "5"                  # shorter than the window
    assert short_id(42, 0) == ""               # 0 disables the label


# --- notebook convenience -----------------------------------------------------

def test_to_dataframe_lazy(site):
    pytest.importorskip("pandas")
    rec = parse_recording(site, RECORDING, sensor_index=0)
    df = rec.to_dataframe()
    assert list(df["Frame"].unique()) == [0, 1]  # empty frame 2 has no rows
    assert len(df) == 3
    assert {"Time", "ID", "Sensor", "Class", "X_ft", "Y_ft",
            "Heading", "X_raw_m", "Y_raw_m"} <= set(df.columns)
