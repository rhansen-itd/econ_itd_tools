"""Live EVO websocket capture, driven from the app's own asyncio loop
(ROADMAP Item 31, RECORD_PLAYBACK_PLAN.md plan §5).

Ports ``../evo_recorder.py``'s auth + raw-stream capture into a controller
safe to drive from inside NiceGUI's already-running event loop:
``RecordingSession.start()`` schedules ``asyncio.create_task`` on the
*running* loop — never ``asyncio.run``, which would collide with the
uvicorn server loop already driving it. ``stop()`` cancels the task and lets
the ``with open(...)`` block close the file handle on the way out.

The blocking login POST (``requests``) is pushed through
``asyncio.to_thread`` so it never stalls the event loop other sessions and
the GUI share.
"""

from __future__ import annotations

import asyncio
import ssl
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests
import urllib3
from websockets.client import connect as ws_connect

# Self-signed device certs, same as evo_recorder.py.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SUBPROTOCOL = "ws_ui"
FIELD_USER = "uname"
FIELD_PASS = "passwd"


@dataclass
class RecordingStatus:
    """Live state of one session, polled by the GUI's status label/timer."""

    host: str
    path: Path | None = None
    connected: bool = False
    frames: int = 0
    error: str | None = None
    stopped: bool = False


def _get_auth_cookie(host: str, username: str, password: str) -> str | None:
    """Blocking login POST (evo_recorder.get_auth_cookie, unchanged logic).
    Callers must run this via asyncio.to_thread — see RecordingSession._run."""
    session = requests.Session()
    payload = {FIELD_USER: username, FIELD_PASS: password}
    try:
        response = session.post(
            f"http://{host}/login", data=payload, verify=False, timeout=10)
        if response.status_code != 200 or not session.cookies:
            return None
        return "; ".join(f"{c.name}={c.value}" for c in session.cookies)
    except requests.RequestException:
        return None


class RecordingSession:
    """One host's capture: owns its asyncio task and output file.

    Guarded against double-start (``running``); ``stop()`` is the only
    supported way to end a session early — closing the dialog without
    stopping leaves it recording, matching evo_recorder's Ctrl+C-to-stop
    model but safe under NiceGUI since the task lives on the server loop,
    not the dialog's lifetime.
    """

    def __init__(self, host: str, username: str, password: str, out_dir: Path):
        self.host = host
        self.username = username
        self.password = password
        self.out_dir = out_dir
        self.status = RecordingStatus(host=host)
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self.status = RecordingStatus(host=self.host)
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self.status.stopped = True

    async def _run(self) -> None:
        cookie = await asyncio.to_thread(
            _get_auth_cookie, self.host, self.username, self.password)
        if cookie is None:
            self.status.error = "login failed"
            return

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        headers = {
            "Cookie": cookie,
            "User-Agent": "Mozilla/5.0",
            "Origin": f"http://{self.host}",
        }

        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{self.host.replace('.', '_')}_EVO_{int(time.time())}.txt"
        self.status.path = path

        try:
            async with ws_connect(
                f"wss://{self.host}/", subprotocols=[SUBPROTOCOL],
                ssl=ssl_context, extra_headers=headers,
                ping_interval=20, ping_timeout=20,
            ) as websocket:
                self.status.connected = True
                await websocket.send("GetCfg")
                with open(path, "w", encoding="utf-8") as f:
                    async for message in websocket:
                        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        f.write(f"{ts}\n{message}\n")
                        f.flush()
                        self.status.frames += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — surfaced via status.error
            self.status.error = str(exc)
        finally:
            self.status.connected = False
