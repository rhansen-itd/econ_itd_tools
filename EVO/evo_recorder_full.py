"""Full-stream EVO recorder — captures the config geometry, not just tracks.

The EVO websocket answers a ``GetCfg`` request with the sensor's *current
configuration*: ``C;`` (per-sensor reference positions in the EVO frame) and
``Z;`` (every event-loop / detector-zone polygon, in EVO-frame metres). Those
lines are the site's alignment reference — the zone polygons span the whole
intersection, a far richer EVO-frame ↔ map correspondence than the 2-3 sensor
points alone (see EVO/iprj_designer/OVERLAY_ROTATION_INVESTIGATION.md).

The existing recorders (``evo_recorder.py`` / ``evo_recorder_multi.py`` /
``iprj_designer/capture/recorder.py``) already write every raw message, so they
*do* capture ``C;``/``Z;`` — but only the single copy the sensor sends once at
connect. Miss that one message (timing, a reconnect, a sensor that only answers
GetCfg once) and the alignment reference is gone, and nothing labels it, so it's
easy to overlook in a 50k-line capture.

This recorder hardens that:
  * sends ``GetCfg`` on connect and **re-requests** it until a ``Z;`` config is
    seen (and periodically after, to catch config changes / a missed first copy),
  * writes the complete raw stream to ``<host>_EVO_<epoch>.txt`` in the exact
    format the existing parsers expect (``timestamp\nmessage\n`` per message),
    so recordings stay drop-in compatible, and
  * additionally mirrors every config line (``C;``/``Z;`` and any non-``F;``
    line) into a labelled sidecar ``<host>_EVO_<epoch>.config.txt`` so the
    alignment geometry is preserved prominently and never buried.

Usage:
    python evo_recorder_full.py --host 10.37.23.201 --user evo --password root
    python evo_recorder_full.py --host 10.37.2.86           # prompts if creds omitted
    python evo_recorder_full.py --host ... --no-recfg        # config-once, like the old recorders
    python evo_recorder_full.py --host ... --recfg-interval 0  # never re-request after first Z;

Ctrl+C stops cleanly. Compatible with the same auth flow as evo_recorder.py.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import ssl
import time
from collections import Counter
from datetime import datetime

import requests
import urllib3
from websockets.client import connect as ws_connect

SUBPROTOCOL = "ws_ui"
FIELD_USER = "uname"
FIELD_PASS = "passwd"

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_auth_cookie(host: str, username: str, password: str) -> str | None:
    """Log in over HTTP and return the cookie header (as evo_recorder.py does)."""
    login_url = f"http://{host}/login"
    print(f"🔐 Authenticating via POST to {login_url} ...")
    session = requests.Session()
    payload = {FIELD_USER: username, FIELD_PASS: password}
    try:
        r = session.post(login_url, data=payload, verify=False, timeout=10)
        if r.status_code != 200 or not session.cookies:
            print(f"❌ Login failed (status {r.status_code})")
            return None
        print("✅ Login successful.")
        return "; ".join(f"{c.name}={c.value}" for c in session.cookies)
    except Exception as e:  # noqa: BLE001
        print(f"❌ Auth error: {e}")
        return None


def _msg_type(message: str) -> str:
    """The leading token that types a message (``F``, ``C``, ``Z``, ...)."""
    head = message.lstrip()[:1]
    return head.upper() if head else "?"


async def record(host: str, auth_cookie: str, *, recfg: bool,
                 recfg_interval: float) -> None:
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    ws_uri = f"wss://{host}/"
    headers = {"Cookie": auth_cookie, "User-Agent": "Mozilla/5.0",
               "Origin": f"http://{host}"}

    print(f"📡 Connecting to {ws_uri} ...")
    async with ws_connect(ws_uri, subprotocols=[SUBPROTOCOL], ssl=ssl_ctx,
                          extra_headers=headers) as ws:
        print("🔹 Connected. Requesting configuration (GetCfg) ...")
        await ws.send("GetCfg")

        stamp = int(time.time())
        base = f"{host.replace('.', '_')}_EVO_{stamp}"
        raw_path, cfg_path = f"{base}.txt", f"{base}.config.txt"

        counts: Counter[str] = Counter()
        cfg_seen = {"C": 0, "Z": 0}
        last_getcfg = time.monotonic()

        # Re-request GetCfg until a Z; config is captured; a background task keeps
        # asking (early, so a missed first copy is retried) without blocking recv.
        stop = asyncio.Event()

        async def nag_getcfg() -> None:
            while recfg and not stop.is_set():
                await asyncio.sleep(2.0)
                # keep asking until we have a Z; config, then honour the interval
                if cfg_seen["Z"] == 0 or (
                    recfg_interval > 0
                    and time.monotonic() - last_getcfg >= recfg_interval
                ):
                    try:
                        await ws.send("GetCfg")
                    except Exception:  # noqa: BLE001 — socket may be closing
                        return

        nagger = asyncio.create_task(nag_getcfg())

        print(f"🔴 Recording RAW stream  -> {raw_path}")
        print(f"🧭 Mirroring config lines -> {cfg_path}")
        print("Press Ctrl+C to stop.\n")

        try:
            with open(raw_path, "w") as raw, open(cfg_path, "w") as cfg:
                cfg.write(f"# EVO config capture for {host} @ "
                          f"{datetime.now().isoformat(timespec='seconds')}\n"
                          f"# C; = per-sensor EVO-frame reference positions\n"
                          f"# Z; = event-loop / detector-zone polygons "
                          f"(EVO-frame metres) — the alignment reference\n\n")
                cfg.flush()
                async for message in ws:
                    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    raw.write(f"{ts}\n{message}\n")
                    raw.flush()

                    mtype = _msg_type(message)
                    counts[mtype] += 1
                    if mtype != "F":  # everything that isn't a track frame is config-ish
                        cfg.write(f"{ts}\n{message}\n")
                        cfg.flush()
                        if mtype in cfg_seen:
                            cfg_seen[mtype] += 1
                            last_getcfg = time.monotonic()

                    total = sum(counts.values())
                    summary = " ".join(f"{k}:{v}" for k, v in sorted(counts.items()))
                    flag = "" if cfg_seen["Z"] else "  ⚠️ no Z; config yet"
                    print(f"\r📥 {total} msgs  [{summary}]{flag}   ", end="")
        finally:
            stop.set()
            nagger.cancel()
            print(f"\n\n⏹️  Stopped. Wrote {raw_path}")
            print(f"    config capture: {cfg_seen['C']}× C;  {cfg_seen['Z']}× Z;  "
                  f"-> {cfg_path}")
            if not cfg_seen["Z"]:
                print("    ⚠️  NO Z; (event-loop) config was captured — the sensor "
                      "never answered GetCfg with zones. Alignment geometry is "
                      "missing from this recording.")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", required=True, help="EVO sensor IP, e.g. 10.37.23.201")
    p.add_argument("--user", default="evo", help="login username (default: evo)")
    p.add_argument("--password", default=None,
                   help="login password (prompts securely if omitted)")
    p.add_argument("--no-recfg", action="store_true",
                   help="don't re-request GetCfg (config-once, like the old recorders)")
    p.add_argument("--recfg-interval", type=float, default=60.0, metavar="SEC",
                   help="after the first Z;, re-request GetCfg every SEC seconds "
                        "to catch config changes (0 = only until first Z;; default 60)")
    args = p.parse_args(argv)

    password = args.password or getpass.getpass(f"Password for {args.user}@{args.host}: ")
    cookie = get_auth_cookie(args.host, args.user, password)
    if not cookie:
        return
    try:
        asyncio.run(record(args.host, cookie, recfg=not args.no_recfg,
                           recfg_interval=args.recfg_interval))
    except KeyboardInterrupt:
        print("\nUser stopped recording.")


if __name__ == "__main__":
    main()
