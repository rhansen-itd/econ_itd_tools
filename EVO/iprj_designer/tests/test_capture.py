"""Live-capture controller tests (ROADMAP Item 31).

No real device or network: `RecordingSession._run` is driven against a fake
websocket (an async iterator standing in for `websockets.client.connect`) so
the start/stream/cancel lifecycle is exercised headless. Output files go to
pytest's `tmp_path`, never under `sites/`.
"""

import asyncio
import json

from capture.hosts import DEFAULT_HOSTS, known_hosts
from capture.recorder import RecordingSession


class FakeWebSocket:
    """Async-iterable stand-in for a websockets client connection."""

    def __init__(self, n_messages=None, delay=0.0):
        self._remaining = n_messages
        self._delay = delay
        self._i = 0
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._remaining is not None and self._i >= self._remaining:
            raise StopAsyncIteration
        if self._delay:
            await asyncio.sleep(self._delay)
        self._i += 1
        return f"F;0;1;2;3;{self._i},7,1.0,2.0,90.0"


class FakeConnect:
    def __init__(self, ws):
        self._ws = ws

    async def __aenter__(self):
        return self._ws

    async def __aexit__(self, *exc_info):
        return False


def _patch_connect(monkeypatch, ws):
    monkeypatch.setattr("capture.recorder.ws_connect", lambda *a, **k: FakeConnect(ws))


def _patch_auth(monkeypatch, cookie="sid=abc123"):
    monkeypatch.setattr(
        "capture.recorder._get_auth_cookie", lambda host, u, p: cookie)


# --- lifecycle ---------------------------------------------------------------

def test_finite_stream_writes_all_frames(tmp_path, monkeypatch):
    _patch_auth(monkeypatch)
    _patch_connect(monkeypatch, FakeWebSocket(n_messages=3))

    session = RecordingSession("10.0.0.1", "evo", "root", tmp_path)

    async def run():
        session.start()
        await session._task

    asyncio.run(run())

    assert session.status.frames == 3
    assert session.status.connected is False
    assert session.status.error is None
    path = session.status.path
    assert path is not None and path.parent == tmp_path
    lines = path.read_text().splitlines()
    assert len(lines) == 6  # timestamp + message per frame
    assert lines[1] == "F;0;1;2;3;1,7,1.0,2.0,90.0"


def test_stop_cancels_a_running_session(tmp_path, monkeypatch):
    _patch_auth(monkeypatch)
    _patch_connect(monkeypatch, FakeWebSocket(n_messages=None, delay=0.01))

    session = RecordingSession("10.0.0.1", "evo", "root", tmp_path)

    async def run():
        session.start()
        await asyncio.sleep(0.05)  # let a few frames land
        assert session.running
        await session.stop()

    asyncio.run(run())

    assert session.status.stopped is True
    assert session.status.connected is False
    assert session.status.frames > 0
    assert not session.running


def test_double_start_is_a_no_op(tmp_path, monkeypatch):
    _patch_auth(monkeypatch)
    _patch_connect(monkeypatch, FakeWebSocket(n_messages=None, delay=0.01))

    session = RecordingSession("10.0.0.1", "evo", "root", tmp_path)

    async def run():
        session.start()
        first_task = session._task
        session.start()  # should not replace the running task
        assert session._task is first_task
        await session.stop()

    asyncio.run(run())


def test_login_failure_sets_status_error(tmp_path, monkeypatch):
    _patch_auth(monkeypatch, cookie=None)

    session = RecordingSession("10.0.0.1", "evo", "root", tmp_path)

    async def run():
        session.start()
        await session._task

    asyncio.run(run())

    assert session.status.error == "login failed"
    assert session.status.frames == 0


# --- hosts.py -----------------------------------------------------------------

def test_known_hosts_defaults_when_no_local_file(tmp_path):
    missing = tmp_path / "hosts.local.json"
    assert known_hosts(missing) == DEFAULT_HOSTS


def test_known_hosts_layers_local_overrides(tmp_path):
    local = tmp_path / "hosts.local.json"
    local.write_text(json.dumps({
        "10.37.2.86": {"username": "custom", "password": "secret"},
        "10.0.0.99": {"username": "evo", "password": "root"},
    }))

    hosts = known_hosts(local)

    assert hosts["10.37.2.86"] == ("custom", "secret")
    assert hosts["10.0.0.99"] == ("evo", "root")
    # untouched defaults survive alongside the overrides
    assert hosts["10.37.2.84"] == DEFAULT_HOSTS["10.37.2.84"]
