"""Live EVO capture (ROADMAP Item 31). Side-effectful I/O against an external
device — websocket auth, streaming, credentials — so it lives in this sibling
package rather than pure `model/` or render-only `gui/` (plan §2)."""

from .hosts import DEFAULT_HOSTS, known_hosts
from .recorder import RecordingSession, RecordingStatus

__all__ = [
    "DEFAULT_HOSTS",
    "known_hosts",
    "RecordingSession",
    "RecordingStatus",
]
