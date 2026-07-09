"""Known EVO hosts for the Record panel (ROADMAP Item 31, plan §5).

Seeds the panel's host picker with `../evo_recorder_multi.py`'s device list
(the ``evo``/``root`` values are the vendor's own defaults, already public in
that committed script — not a secret). A gitignored ``hosts.local.json`` next
to this file can add or override entries for real deployments without ever
being committed, per plan §5's "do not commit new credentials" rule.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_HOSTS: dict[str, tuple[str, str]] = {
    "10.37.23.201": ("evo", "root"),
    "10.37.2.84": ("evo", "root"),
    "10.37.2.85": ("evo", "root"),
    "10.37.2.86": ("evo", "root"),
    "10.37.2.87": ("evo", "root"),
}

_LOCAL_CONFIG = Path(__file__).parent / "hosts.local.json"


def known_hosts(local_config: Path | None = None) -> dict[str, tuple[str, str]]:
    """``DEFAULT_HOSTS`` layered with the local override file, if present.

    ``local_config`` is exposed as a parameter for tests; the app always
    calls this with no argument so it reads the real gitignored file.
    """
    hosts = dict(DEFAULT_HOSTS)
    path = local_config if local_config is not None else _LOCAL_CONFIG
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return hosts
        for host, creds in data.items():
            if isinstance(creds, dict):
                hosts[host] = (
                    creds.get("username", "evo"),
                    creds.get("password", "root"),
                )
    return hosts
