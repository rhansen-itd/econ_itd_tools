"""Live-overlay pipeline tests (ROADMAP Item 35).

The GUI/async wiring in gui/app.py (the Live mode, the ui.timer, the marker
render) is exercised by hand. What is checked headlessly here is the load-
bearing composition Item 35 assembles out of Items 33 and 34: the recorder
feed-tap (Item 34) fans each captured message to a subscriber that runs the
streaming LiveAligner (Item 33) and overwrites a single "latest aligned frame"
slot — the drop-to-latest seam of LIVE_OVERLAY_PLAN.md §3.

No real device or network: RecordingSession._run is driven against a fake
websocket (a C; reference once, then F; track frames), exactly as
tests/test_capture.py does. Alignment is anchored to the real 86_US95&SH8
site fixture (read-only); nothing is written under sites/.
"""

import asyncio
import time
from pathlib import Path

import pytest

from capture.recorder import RecordingSession
from model.iprj_io import load_iprj
from model.replay import LiveAligner, parse_recording

SITES = Path(__file__).resolve().parents[3] / "sites"

# A C; reference and three F; frames at known metric offsets from it — the
# messages a live socket delivers one at a time (no wall-clock line; the GUI
# stamps time, so these carry none).
REF = (12.5, -3.75)
LIVE_MESSAGES = [
    f"C;{REF[0]},{REF[1]},0.0,extra-ignored",
    f"F;0;1;2;3;101,7,{REF[0]},{REF[1]},90.0;42,2,{REF[0] + 10.0},{REF[1] + 5.0},180.0",
    f"F;0;1;2;3;101,7,{REF[0] + 1.0},{REF[1] + 1.0},91.5",
    "F;0;1;2;3;101,7,{},{}",  # filled below
]
LIVE_MESSAGES[-1] = f"F;0;1;2;3;101,7,{REF[0] + 2.0},{REF[1] + 3.0},92.0"


@pytest.fixture(scope="module")
def site():
    return load_iprj(SITES / "86_US95&SH8" / "us95&sh8.iprj")


class ScriptedWebSocket:
    """Async-iterable stand-in that replays a fixed list of raw messages —
    one C; reference then F; frames, as a real EVO feed opens."""

    def __init__(self, messages, delay=0.0):
        self._messages = list(messages)
        self._delay = delay
        self._i = 0
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i >= len(self._messages):
            raise StopAsyncIteration
        if self._delay:
            await asyncio.sleep(self._delay)
        msg = self._messages[self._i]
        self._i += 1
        return msg


class _Connect:
    def __init__(self, ws):
        self._ws = ws

    async def __aenter__(self):
        return self._ws

    async def __aexit__(self, *exc_info):
        return False


def _patch(monkeypatch, ws):
    monkeypatch.setattr("capture.recorder.ws_connect", lambda *a, **k: _Connect(ws))
    monkeypatch.setattr(
        "capture.recorder._get_auth_cookie", lambda host, u, p: "sid=abc")


def _drive(session):
    async def run():
        session.start()
        await session._task

    asyncio.run(run())


# --- the Item 35 composition: feed-tap -> aligner -> latest-frame slot -------

def test_live_pipeline_slot_holds_latest_and_feed_is_lossless(site, monkeypatch):
    """The end-to-end seam Live mode builds: every captured message reaches the
    aligner (lossless — so the one-time C; anchors the whole stream), while the
    slot keeps only the newest aligned frame (drop-to-latest, plan §3). The
    frames produced must match a batch parse of the same stream frame-for-frame
    on aligned coordinates."""
    _patch(monkeypatch, ScriptedWebSocket(LIVE_MESSAGES))
    session = RecordingSession("10.0.0.1", "evo", "root", Path("/unused"),
                               save=False)
    aligner = LiveAligner(site, sensor_index=0)
    slot = {}          # the single "latest aligned frame" slot (v.live_frame)
    produced = []      # every frame the render feed saw, to prove losslessness

    def on_message(msg):
        frame = aligner.feed(msg, t="12:00:00.000")
        if frame is not None:
            slot["frame"] = (frame, time.monotonic())
            produced.append(frame)

    session.subscribe(on_message)
    _drive(session)

    # Lossless: the C; reference arrived and anchored the aligner.
    assert aligner.ref_seen is True
    assert aligner.ref_m == REF

    # Every F; message produced exactly one aligned frame.
    n_frames = sum(1 for m in LIVE_MESSAGES if m.startswith("F;"))
    assert len(produced) == n_frames

    # Frame-for-frame equal to the batch engine on aligned coordinates.
    text = "\n".join(LIVE_MESSAGES) + "\n"
    batch = parse_recording(site, text, sensor_index=0)
    assert [f.points for f in produced] == [f.points for f in batch.frames]

    # The slot holds only the latest frame (drop-to-latest).
    assert slot["frame"][0].points == batch.frames[-1].points


def test_live_pipeline_survives_a_raising_render_callback(site, monkeypatch):
    """A bug in the render-side subscriber must not take down capture (Item 34's
    try/except contract), so the Live overlay can never kill the feed."""
    _patch(monkeypatch, ScriptedWebSocket(LIVE_MESSAGES))
    session = RecordingSession("10.0.0.1", "evo", "root", Path("/unused"),
                               save=False)

    def bad(_msg):
        raise RuntimeError("render boom")

    session.subscribe(bad)
    _drive(session)

    assert session.status.error is None
    assert session.status.frames == len(LIVE_MESSAGES)


def test_live_overlay_needs_no_disk(site, monkeypatch, tmp_path):
    """Overlay-only: save=False fans out to the aligner without writing a file
    (plan §1), so a live overlay leaves nothing under the recordings dir."""
    _patch(monkeypatch, ScriptedWebSocket(LIVE_MESSAGES))
    session = RecordingSession("10.0.0.1", "evo", "root", tmp_path, save=False)
    aligner = LiveAligner(site, sensor_index=0)
    got = []
    session.subscribe(lambda m: got.append(aligner.feed(m, t="12:00:00.000")))
    _drive(session)

    assert session.status.path is None
    assert not list(tmp_path.iterdir())
    assert sum(1 for f in got if f is not None) == 3
