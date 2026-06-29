"""
eos_set_time.py
===============
Automation script for setting the clock on an Econolite EOS traffic signal
controller via its front-panel WebSocket interface.

Usage (direct):
    python eos_set_time.py

Usage (cron / scheduled):
    Call `run_with_retry()` from an external scheduler, or add a cron entry:
        */5 * * * * /usr/bin/python3 /path/to/eos_set_time.py

Configuration:
    Edit the CONFIGURATION block below, or import EOSController
    and SchedulerManager into your own code.
"""

import asyncio
import ssl
import re
import logging
import subprocess
import sys
from datetime import datetime, timedelta

import websockets

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────
IP_ADDRESS      = "localhost"  #"10.37.23.200"
PORT            = "8443"          # 8081 = plain ws://  |  8443 = wss://
USE_SSL         = PORT == "8443"
WS_URL          = f"{'wss' if USE_SSL else 'ws'}://{IP_ADDRESS}:{PORT}/"
SUB_PROTOCOL    = "front-panel-protocol"

USER_ID         = "01"            # two-digit user ID ("0" → key10, "1" → key1)
PASSWORD        = "12345678"      # eight-digit password

# Key mappings  (digit → keycode string)
DIGIT_KEYS = {
    "0": "key10", "1": "key1", "2": "key2", "3": "key3", "4": "key4",
    "5": "key5",  "6": "key6", "7": "key7", "8": "key8", "9": "key9",
}
KEY_MENU        = "key17"   # 'm' / Menu button
KEY_ENTER       = "key23"   # Enter / Accept
KEY_SPEC_FUNC   = "key11"   # Special Function (used in logout)
KEY_STATUS      = "key21"   # Status (used in logout)
KEY_UP          = "key13"   # Arrow Up
KEY_DOWN        = "key14"   # Arrow Down
KEY_LEFT        = "key15"   # Arrow Left
KEY_RIGHT       = "key16"   # Arrow Right

# Clock screen cursor targets — confirmed from live field controller captures:
#   On entry to CLOCK OPTION the cursor starts at (2, 29).
#   One DOWN arrow jumps to the SET TIME row.
#   Time is formatted HH:MM:SS; cursor lands on the ones digit of each field:
#     hours ones   = col 28  (0x1C)
#     minutes ones = col 31  (0x1F)
#     seconds ones = col 34  (0x22)
CLOCK_ENTRY_CURSOR_ROW = 2   # cursor position when CLOCK OPTION first opens
CLOCK_ENTRY_CURSOR_COL = 29
HOURS_CURSOR_ROW   = 4
HOURS_CURSOR_COL   = 28   # ones digit of HH
MINUTES_CURSOR_ROW = 4
MINUTES_CURSOR_COL = 31   # ones digit of MM  (hex 0x1F)
SECONDS_CURSOR_ROW = 4
SECONDS_CURSOR_COL = 34   # ones digit of SS  (hex 0x22)

# Maximum drift (seconds) correctable via seconds field alone.
# If |drift| exceeds this, a minutes correction is done first.
MAX_SECONDS_ONLY_DELTA = 50

# Timing knobs
OBSERVATION_SECONDS     = 3    # passive observation period before acting
TIME_LEAD_SECONDS       = 5     # commit this many seconds ahead of now
VERIFICATION_WINDOW     = 2.0   # seconds to read screen after commit
MAX_TIME_RETRIES        = 3     # max attempts before raising TimeVerificationError
MSG_TIMEOUT             = 10.0  # seconds to wait for an expected screen
HEARTBEAT_INTERVAL      = 50    # send "get" every N received messages

# If the controller time is within this many seconds of local, skip the sync.
SYNC_TOLERANCE_SECONDS  = 1     # consider in-sync if |drift| <= this value

# Retry intervals differentiated by exception type
RETRY_BUSY_MINUTES      = 30    # UserActiveError / SessionActiveError
RETRY_FAILURE_MINUTES   = 5     # NavigationError / CursorPositionError / TimeVerificationError

# Diagnostic capture — set to a file path to record raw WebSocket messages
# during the time-screen navigation phase for debugging.  Set to None to disable.
# Example: DIAGNOSTIC_CAPTURE_FILE = "/tmp/eos_nav_debug.txt"
DIAGNOSTIC_CAPTURE_FILE = "./eos_nav_debug.txt"
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("eos_set_time")


# ══════════════════════════════════════════════════════════════════════════════
# Custom Exceptions
# ══════════════════════════════════════════════════════════════════════════════

class UserActiveError(Exception):
    """Raised when another user is detected on the panel."""

class SessionActiveError(Exception):
    """Raised when the controller already has an authenticated session open."""

class NavigationError(Exception):
    """Raised when the expected screen text never appears within the timeout."""

class CursorPositionError(Exception):
    """Raised when the cursor is not at the expected field."""

class TimeVerificationError(Exception):
    """Raised after MAX_TIME_RETRIES failed time-set attempts."""


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _mm_ss_delta(ctrl_m: int, ctrl_s: int, local_m: int, local_s: int) -> int:
    """
    Signed difference (controller − local) in seconds using mm:ss only.
    Result is in the range (-1800, +1800] via modulo-3600 shortest-arc.

    Positive → controller is AHEAD of local time.
    Negative → controller is BEHIND local time.
    Safe in both directions, handles minute rollovers (e.g. 00:01 vs 59:59).
    """
    diff = (ctrl_m * 60 + ctrl_s) - (local_m * 60 + local_s)
    return (diff + 1800) % 3600 - 1800


# ══════════════════════════════════════════════════════════════════════════════
# EOSController
# ══════════════════════════════════════════════════════════════════════════════

class EOSController:
    """
    Manages a single WebSocket session with an Econolite EOS controller.

    Lifecycle
    ---------
    async with EOSController() as ctrl:
        await ctrl.observe_for_active_user()
        await ctrl.login()
        await ctrl.navigate_to_clock()
        await ctrl.set_time()
        # logout is called automatically on context exit (success OR failure)
    """

    def __init__(self):
        self._ws = None
        self._msg_count = 0
        self._last_message = ""

    # ── context manager ──────────────────────────────────────────────────────

    async def __aenter__(self):
        ssl_ctx = ssl._create_unverified_context() if USE_SSL else None
        log.info("Connecting to %s …", WS_URL)
        self._ws = await websockets.connect(
            WS_URL,
            subprotocols=[SUB_PROTOCOL],
            ssl=ssl_ctx,
        )
        log.info("Connected.")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Always attempt graceful logout before closing, to avoid leaving the
        # panel locked out for other users.  Use .close() — not .closed —
        # since websockets.ClientConnection exposes close() not a .closed attr.
        if self._ws is not None:
            try:
                await self.logout()
            except Exception as e:
                log.warning("Logout attempt raised: %s", e)
            finally:
                try:
                    await self._ws.close()
                except Exception:
                    pass
        return False   # do not suppress exceptions

    # ── low-level helpers ─────────────────────────────────────────────────────

    async def _send(self, key: str):
        """Send a keycode string and log it."""
        log.debug("→ send: %s", key)
        await self._ws.send(key)

    async def _recv(self) -> str:
        """
        Receive one message, handle heartbeat, and return the raw string.
        Silently discards messages too short to contain screen data.
        """
        while True:
            raw = await self._ws.recv()
            self._msg_count += 1
            if self._msg_count >= HEARTBEAT_INTERVAL:
                await self._ws.send("get")
                self._msg_count = 0
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            self._last_message = raw
            if len(raw) >= 20:
                return raw

    # ── cursor / screen parsing ───────────────────────────────────────────────

    @staticmethod
    def get_cursor_position(message: str) -> tuple[int, int]:
        """
        Extract (row, col) from the hex prefix that precedes the screen text.

        Payload format:  <16-char hex prefix ending RRCCSEPblob...screen>
        where SEP is 'v' (emulator) or 'a' (field controller).
        The 4 hex digits immediately before SEP are row (RR) and col (CC).

        The separator is always at index 16, so we read coords from [12:16]
        directly rather than searching for the separator character — this is
        more robust and avoids false matches on hex letters in the blob.

        Special values:
            0000  →  (0, 0)  hidden / idle cursor
            0101  →  (1, 1)  status-display cursor

        Returns (row, col) as ints, or (-1, -1) on parse failure.
        """
        if len(message) < 17:
            return (-1, -1)
        try:
            row = int(message[12:14], 16)
            col = int(message[14:16], 16)
            return (row, col)
        except ValueError:
            return (-1, -1)

    # Payload layout (confirmed by Gemini analysis of full sample data):
    #   [0:15]   hex prefix (16 chars, last 4 = cursor coords)
    #   [16]     literal 'v'
    #   [17:256] 240-char hex blob (UI formatting / color state, changes every frame)
    #   [257:]   human-readable screen text, 40 columns wide
    #
    # First line of screen is always message[257:297].
    SCREEN_TEXT_OFFSET = 257

    @staticmethod
    def get_screen_text(message: str) -> str:
        """
        Return the human-readable screen text at the fixed offset (index 257).

        Payload layout (confirmed from full sample analysis):
          [0:16]   hex prefix ending in cursor coords + literal 'v'
          [17:256] 240-char hex blob — UI color/format state, changes every frame
          [257:]   human-readable screen text (40-column grid)

        The blob contains hex letters A-F that vary constantly, making any
        scan-based approach (first 'v', first space) unreliable for structural
        comparisons.  The fixed offset is the only correct approach.
        """
        if len(message) <= EOSController.SCREEN_TEXT_OFFSET:
            # Short/heartbeat message — best-effort fallback
            idx = message.find("v")
            return message[idx + 1:] if idx != -1 else message
        return message[EOSController.SCREEN_TEXT_OFFSET:]

    # ── wait helpers ─────────────────────────────────────────────────────────

    async def _wait_for_text(self, expected: str, timeout: float = MSG_TIMEOUT) -> str:
        """
        Read messages until `expected` appears in the screen text.
        Returns the full raw message.  Raises NavigationError on timeout.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            try:
                raw = await asyncio.wait_for(self._recv(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            if expected in self.get_screen_text(raw):
                log.debug("Screen matched %r", expected)
                return raw
        raise NavigationError(f"Timed out waiting for screen text: {expected!r}")

    async def _wait_for_cursor_change(self, old_row: int, old_col: int, timeout: float = 3.0):
        """
        Drain incoming messages until the cursor coordinates differ from
        (old_row, old_col), confirming the controller processed the last key.

        Returns the first raw message where the cursor has moved, so the
        caller can use it directly instead of reading another message.
        Returns None on timeout (cursor never moved within the window).
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            try:
                raw = await asyncio.wait_for(self._recv(), timeout=min(1.0, remaining))
                r, c = self.get_cursor_position(raw)
                self._diag_log("WAIT_CHANGE", raw)
                if r != old_row or c != old_col:
                    return raw   # cursor moved — return the message to the caller
            except asyncio.TimeoutError:
                continue
        self._diag_log("WAIT_CHANGE_TIMEOUT", self._last_message)
        return None   # timed out — cursor did not move

    # ── Step 1: Active user observation ──────────────────────────────────────

    async def observe_for_active_user(self):
        """
        Read the first substantive screen and decide whether it is safe to act.

        Rules
        -----
        • If the initial screen is anything other than the STATUS display or
          MAIN MENU, assume someone else is using the panel → UserActiveError.
        • STATUS screen: watch for OBSERVATION_SECONDS for any cursor movement
          or structural screen change.
        • MAIN MENU: watch for OBSERVATION_SECONDS for any structural change.
        • If nothing changes in either case, proceed.

        "Structural change" means non-digit characters changed — pure clock
        ticks (digits only) are ignored.
        """
        log.info("Reading initial screen …")
        first_raw = await asyncio.wait_for(self._recv(), timeout=MSG_TIMEOUT)
        first_screen = self.get_screen_text(first_raw).strip()

        on_status    = "STATUS" in first_screen
        on_main_menu = "MAIN MENU" in first_screen

        if not on_status and not on_main_menu:
            raise UserActiveError(
                f"Initial screen is neither STATUS nor MAIN MENU — "
                f"panel appears to be in use. Screen starts with: "
                f"{first_screen[:60]!r}"
            )

        log.info(
            "Initial screen: %s. Observing for %d seconds …",
            "STATUS" if on_status else "MAIN MENU",
            OBSERVATION_SECONDS,
        )

        end_time = asyncio.get_event_loop().time() + OBSERVATION_SECONDS
        last_structural = re.sub(r"\d", "", first_screen).strip()

        while asyncio.get_event_loop().time() < end_time:
            remaining = end_time - asyncio.get_event_loop().time()
            try:
                raw = await asyncio.wait_for(self._recv(), timeout=remaining)
            except asyncio.TimeoutError:
                break

            screen     = self.get_screen_text(raw).strip()
            row, col   = self.get_cursor_position(raw)
            structural = re.sub(r"\d", "", screen).strip()

            if on_status:
                # Any non-idle cursor position means someone is interacting
                if (row, col) not in ((0, 0), (1, 1), (-1, -1)):
                    raise UserActiveError(
                        f"Cursor moved on STATUS screen to ({row},{col}) — "
                        "user appears active."
                    )
                if structural != last_structural:
                    raise UserActiveError(
                        "STATUS screen content changed structurally during observation."
                    )
            else:  # MAIN MENU
                if structural != last_structural:
                    raise UserActiveError(
                        "MAIN MENU changed during observation — user appears active."
                    )

            last_structural = structural

        log.info("Observation complete — panel appears idle.")

    # ── Step 1b: Pre-login time check ────────────────────────────────────────

    def _parse_status_screen_time(self, screen: str) -> tuple[int, int, int] | None:
        """
        Extract (hh, mm, ss) from a STATUS screen, which has two possible layouts:

        Layout A — time in top row, pipe-separated:
            mm/dd/yy|hh:mm:ss
        Layout B — time in bottom row, space-separated:
            mm/dd/yy hh:mm:ss

        Returns (hh, mm, ss) as ints, or None if no time found.
        """
        # Both layouts share the same HH:MM:SS pattern; the date always
        # immediately precedes it so we anchor to avoid matching other fields.
        m = re.search(r"\d{2}/\d{2}/\d{2}[\s|](\d{2}):(\d{2}):(\d{2})", screen)
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3))
        return None

    async def check_time_in_sync(self) -> bool:
        """
        Read the current STATUS screen and compare the controller time to local.

        Returns True  if the controller is within SYNC_TOLERANCE_SECONDS of
                       local time — no sync needed, safe to exit.
        Returns False if out of sync or if the time cannot be read (proceed
                       with the full login + set flow).

        Must be called after observe_for_active_user() while still on the
        STATUS screen.
        """
        screen = self.get_screen_text(self._last_message)
        ctrl_time = self._parse_status_screen_time(screen)

        if ctrl_time is None:
            log.info("Could not read time from STATUS screen — proceeding with sync.")
            return False

        ctrl_hh, ctrl_mm, ctrl_ss = ctrl_time
        local = datetime.now()
        drift = abs(_mm_ss_delta(ctrl_mm, ctrl_ss, local.minute, local.second))

        log.info(
            "STATUS screen time: %02d:%02d:%02d  Local: %02d:%02d:%02d  Δ=%ds",
            ctrl_hh, ctrl_mm, ctrl_ss, local.hour, local.minute, local.second, drift,
        )

        if drift <= SYNC_TOLERANCE_SECONDS:
            log.info(
                "Controller is within %ds tolerance — no sync needed.",
                SYNC_TOLERANCE_SECONDS,
            )
            return True

        log.info("Controller is %+ds off — sync required.", drift)
        return False

    # ── Step 2: Login ─────────────────────────────────────────────────────────

    async def login(self) -> bool:
        """
        Send Menu (if not already there), navigate to SCHEDULER to trigger
        the auth check, and log in if required.

        Raises:
            SessionActiveError – controller already has an open session.
            NavigationError    – expected screen never appeared.
        """
        current = self.get_screen_text(self._last_message)
        if "MAIN MENU" not in current:
            log.info("Sending Menu key …")
            await self._send(KEY_MENU)
            await self._wait_for_text("MAIN MENU")

        log.info("Navigating to SCHEDULER to check auth …")
        await self._send(DIGIT_KEYS["5"])

        deadline = asyncio.get_event_loop().time() + MSG_TIMEOUT
        access_prompt_found = False
        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            try:
                raw = await asyncio.wait_for(self._recv(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            screen = self.get_screen_text(raw)
            if "SCHEDULE SUBMENU" in screen:
                raise SessionActiveError(
                    "Controller already has an authenticated session. Exiting without changes."
                )
            if "Access Code:" in screen:
                access_prompt_found = True
                break

        if not access_prompt_found:
            raise NavigationError("Neither SCHEDULE SUBMENU nor Access Code prompt appeared.")

        log.info("Access Code prompt found. Entering credentials …")
        await self._enter_credentials()
        return True

    async def _enter_credentials(self):
        """Type User ID and Password digit-by-digit, verifying cursor advance."""
        log.info("Entering User ID: %s", USER_ID)
        for digit in USER_ID:
            await asyncio.sleep(0.2)
            _, col_before = self.get_cursor_position(self._last_message)
            await self._send(DIGIT_KEYS[digit])
            await self._wait_for_star_advance(col_before)

        log.info("Entering Password …")
        for digit in PASSWORD:
            await asyncio.sleep(0.2)
            _, col_before = self.get_cursor_position(self._last_message)
            await self._send(DIGIT_KEYS[digit])
            await self._wait_for_star_advance(col_before)

        log.info("Submitting credentials …")
        await self._send(KEY_ENTER)
        raw = await self._wait_for_text("Logged in")
        log.info("Login confirmed: %s", self.get_screen_text(raw)[:80].strip())

        await self._send(KEY_ENTER)
        await self._wait_for_text("MAIN MENU")
        log.info("Back at MAIN MENU.")

        log.info("Re-sending SCHEDULER key after login …")
        await self._send(DIGIT_KEYS["5"])
        await self._wait_for_text("SCHEDULE SUBMENU")
        log.info("SCHEDULE SUBMENU reached.")

    async def _wait_for_star_advance(self, col_before: int, timeout: float = 5.0):
        """
        Wait for cursor column to advance by 1 after a credential digit.

        Uses a 1 s inner poll window so we keep retrying across the full
        timeout rather than giving up after the first slow response.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            try:
                raw = await asyncio.wait_for(self._recv(), timeout=min(1.0, remaining))
            except asyncio.TimeoutError:
                continue   # keep waiting until outer deadline
            _, col_now = self.get_cursor_position(raw)
            if col_now == col_before + 1:
                return
        log.warning("Could not confirm cursor advance after digit; proceeding anyway.")

    # ── Step 3: Navigate to Clock ─────────────────────────────────────────────

    async def navigate_to_clock(self):
        """
        From SCHEDULE SUBMENU, send key1 and wait for CLOCK OPTION screen.

        The controller continues streaming update frames for a moment after
        SCHEDULE SUBMENU appears.  Sending key1 immediately can land while
        those buffered frames are still being processed and get dropped.
        We drain incoming messages for a short settle period first, then
        retry sending key1 up to 3 times if CLOCK OPTION doesn't appear.
        """
        log.info("Navigating to CLOCK OPTION …")

        # Drain any in-flight frames so the controller is truly settled on
        # SCHEDULE SUBMENU before we send the next key.
        await asyncio.sleep(0.5)
        # Consume any messages already buffered
        drain_deadline = asyncio.get_event_loop().time() + 0.5
        while asyncio.get_event_loop().time() < drain_deadline:
            try:
                await asyncio.wait_for(self._recv(), timeout=0.1)
            except asyncio.TimeoutError:
                break

        for attempt in range(1, 4):
            log.info("Sending key1 for CLOCK OPTION (attempt %d) …", attempt)
            await self._send(DIGIT_KEYS["1"])
            try:
                await self._wait_for_text("CLOCK OPTION", timeout=5.0)
                log.info("CLOCK OPTION screen reached.")
                return
            except NavigationError:
                log.warning("CLOCK OPTION not seen after attempt %d.", attempt)
                # Re-confirm we are still on SCHEDULE SUBMENU before retrying
                try:
                    await self._wait_for_text("SCHEDULE SUBMENU", timeout=3.0)
                except NavigationError:
                    pass  # screen state unknown — just retry anyway

        raise NavigationError("Could not reach CLOCK OPTION after 3 attempts.")

    def _diag_log(self, tag: str, raw: str):
        """
        Append a raw message to the diagnostic capture file if enabled.
        Each line is: TAG | cursor_row,cursor_col | first 60 chars of screen text
        """
        if not DIAGNOSTIC_CAPTURE_FILE:
            return
        try:
            row, col = self.get_cursor_position(raw)
            screen = self.get_screen_text(raw)[:80].replace("\n", " ")
            with open(DIAGNOSTIC_CAPTURE_FILE, "a") as f:
                f.write(f"{tag} | ({row:3d},{col:3d}) | {screen}\n")
        except Exception:
            pass

    async def _navigate_to_field(self, target_row: int, target_col: int):
        """
        Arrow-key navigate to (target_row, target_col) on the CLOCK OPTION screen.

        Sends one key at a time and waits for the cursor to actually move before
        re-evaluating (avoids double-press race condition against the high-freq
        update stream).  Raises NavigationError immediately if the CLOCK OPTION
        screen is left — prevents navigation commands from firing on the wrong screen.
        """
        log.info("Navigating to field (row=%d, col=%d) …", target_row, target_col)

        if DIAGNOSTIC_CAPTURE_FILE:
            import os
            # Truncate/create fresh capture file for this navigation attempt
            with open(DIAGNOSTIC_CAPTURE_FILE, "w") as f:
                f.write(f"=== navigate_to_field target=({target_row},{target_col}) ===\n")
            log.info("Diagnostic capture → %s", DIAGNOSTIC_CAPTURE_FILE)

        deadline = asyncio.get_event_loop().time() + MSG_TIMEOUT * 2

        # Seed the loop with the current message so we evaluate immediately
        # without reading a new frame first.
        raw = self._last_message

        while asyncio.get_event_loop().time() < deadline:
            row, col = self.get_cursor_position(raw)
            screen = self.get_screen_text(raw)

            self._diag_log("EVAL", raw)

            # Safety gate: abort if we've left CLOCK OPTION
            if "CLOCK OPTION" not in screen:
                self._diag_log("ERROR_LEFT_SCREEN", raw)
                raise NavigationError(
                    f"Left CLOCK OPTION screen unexpectedly during navigation. "
                    f"Screen now shows: {screen[:60]!r}"
                )

            log.debug("Cursor at (%d,%d), target (%d,%d)", row, col, target_row, target_col)

            if row == target_row and col == target_col:
                log.info("Cursor confirmed at (%d,%d).", target_row, target_col)
                self._diag_log("CONFIRMED", raw)
                return raw

            # Minimum inter-key delay for high-latency field controllers
            await asyncio.sleep(0.2)

            if row < target_row:
                self._diag_log("SEND_DOWN", raw)
                await self._send(KEY_DOWN)
            elif row > target_row:
                self._diag_log("SEND_UP", raw)
                await self._send(KEY_UP)
            elif col < target_col:
                self._diag_log("SEND_RIGHT", raw)
                await self._send(KEY_RIGHT)
            elif col > target_col:
                self._diag_log("SEND_LEFT", raw)
                await self._send(KEY_LEFT)
            else:
                raise CursorPositionError(
                    f"Cursor stuck at ({row},{col}) — cannot reach "
                    f"target ({target_row},{target_col})"
                )

            # Wait for the cursor to move, then use that message as the next
            # loop iteration — avoids reading a stale buffered frame.
            moved = await self._wait_for_cursor_change(row, col)
            if moved is not None:
                raw = moved   # cursor confirmed moved; evaluate new position
            else:
                # Timeout: controller didn't respond to the key in 3s.
                # Read one fresh frame and try again — the key may have been
                # lost or the controller is slow.
                log.warning(
                    "Cursor did not move after key at (%d,%d); reading fresh frame.",
                    row, col,
                )
                try:
                    raw = await asyncio.wait_for(self._recv(), timeout=2.0)
                except asyncio.TimeoutError:
                    raw = self._last_message  # nothing arrived; re-evaluate same state

        raise CursorPositionError(
            f"Could not navigate to field ({target_row},{target_col})"
        )

    # ── Step 4: Set the time ──────────────────────────────────────────────────

    async def set_time(self):
        """
        Full time-setting routine with retry logic.

        Raises:
            TimeVerificationError after MAX_TIME_RETRIES failed attempts.
        """
        for attempt in range(1, MAX_TIME_RETRIES + 1):
            log.info("Time-set attempt %d / %d", attempt, MAX_TIME_RETRIES)
            try:
                await self._attempt_set_time()
                log.info("✓ Time verified successfully.")
                return
            except TimeVerificationError as e:
                log.warning("Attempt %d failed: %s", attempt, e)
                if attempt == MAX_TIME_RETRIES:
                    raise TimeVerificationError(
                        f"Time setting failed after {MAX_TIME_RETRIES} attempts."
                    ) from e
                await asyncio.sleep(2)

    async def _read_controller_time(self) -> tuple[int, int, int] | None:
        """
        Read up to MSG_TIMEOUT seconds of messages and return the first
        (hh, mm, ss) parsed from the day-anchored time on the CLOCK OPTION screen.
        Returns None if no match is found.
        """
        deadline = asyncio.get_event_loop().time() + MSG_TIMEOUT
        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            try:
                raw = await asyncio.wait_for(self._recv(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            screen = self.get_screen_text(raw)
            m = re.search(r"[A-Z]{3}\s+(\d{2}):(\d{2}):(\d{2})", screen)
            if m:
                return int(m.group(1)), int(m.group(2)), int(m.group(3))
        return None

    async def _attempt_set_time(self):
        """
        Single attempt at time correction.

        Strategy
        --------
        1.  Read the controller's current mm:ss from the CLOCK OPTION screen.
        2.  Compute signed drift = controller − local (positive = ctrl ahead).
        3a. |drift| ≤ 50 s  →  correct via seconds field only.
        3b. |drift| > 50 s  →  correct minutes by ±1 first (bringing |drift|
            within 50 s), then correct seconds.  The minutes edit is refused
            if local second > 50 (too close to a minute boundary).

        Seconds-field safe windows
        --------------------------
        Controller BEHIND (drift < 0, e.g. −10 s):
          We type a LARGER seconds value.  Safe when
          (local.second + TIME_LEAD_SECONDS) < 60, i.e. the commit second
          won't roll the minute over.

        Controller AHEAD (drift > 0, e.g. +10 s):
          We type a SMALLER seconds value.  Safe when local.second < 10
          (we're in the first 10 s of a minute), so the new value is
          positive and we stay in the same minute.

        In both cases we stay in the same minute on the controller — only the
        seconds field is changed.
        """
        ctrl_time = await self._read_controller_time()
        if ctrl_time is None:
            raise TimeVerificationError(
                "Could not read controller time from CLOCK OPTION screen."
            )
        ctrl_hh, ctrl_mm, ctrl_ss = ctrl_time
        local_now = datetime.now()
        drift = _mm_ss_delta(ctrl_mm, ctrl_ss, local_now.minute, local_now.second)

        log.info(
            "Controller: %02d:%02d, Local: %02d:%02d, drift=%+ds",
            ctrl_mm, ctrl_ss, local_now.minute, local_now.second, drift,
        )

        # ── Large drift: fix minutes first (loops until within 50s) ────────────
        if abs(drift) > MAX_SECONDS_ONLY_DELTA:
            drift = await self._correct_minutes(ctrl_mm, drift)

        # ── Seconds correction ────────────────────────────────────────────────
        await self._correct_seconds(drift)

    async def _safe_recv_wait(self, seconds: float):
        """Sleep for `seconds` while continuing to receive so heartbeats fire."""
        deadline = asyncio.get_event_loop().time() + seconds
        while asyncio.get_event_loop().time() < deadline:
            try:
                await asyncio.wait_for(self._recv(), timeout=0.5)
            except asyncio.TimeoutError:
                pass

    async def _correct_minutes(self, ctrl_mm: int, drift: int) -> int:
        """
        Repeatedly adjust the minutes field until |drift| <= MAX_SECONDS_ONLY_DELTA.

        Each iteration subtracts or adds 1 minute to the controller's current
        minute, re-reads the controller time, recomputes drift, and loops until
        within the seconds-correction window.  Returns the final drift value.

        Capped at MAX_MINUTE_ITERS iterations as a safety net.
        All blocking waits use _safe_recv_wait so heartbeats keep firing.
        """
        MAX_MINUTE_ITERS = 20   # safety cap — handles up to ~20 min of drift

        for iteration in range(MAX_MINUTE_ITERS):
            if abs(drift) <= MAX_SECONDS_ONLY_DELTA:
                log.info("Minutes correction complete after %d edit(s) — drift %+ds.",
                         iteration, drift)
                return drift

            # Wait away from minute boundary before each edit
            if datetime.now().second > 50:
                wait_s = 60 - datetime.now().second + 3
                log.info(
                    "Too close to minute boundary (local_s=%d). Waiting %ds …",
                    datetime.now().second, wait_s,
                )
                await self._safe_recv_wait(wait_s)

            direction  = -1 if drift > 0 else +1
            new_minute = (ctrl_mm + direction) % 60
            log.info(
                "Minutes edit %d: %s ctrl min %02d → %02d  (drift=%+ds)",
                iteration + 1,
                "subtracting" if direction == -1 else "adding",
                ctrl_mm, new_minute, drift,
            )

            await self._navigate_to_field(MINUTES_CURSOR_ROW, MINUTES_CURSOR_COL)
            await self._send(DIGIT_KEYS[str(new_minute // 10)])
            await asyncio.sleep(0.1)
            await self._send(DIGIT_KEYS[str(new_minute % 10)])
            await asyncio.sleep(0.1)
            await self._send(KEY_ENTER)
            await self._safe_recv_wait(0.5)
            await self._wait_for_text("CLOCK OPTION")

            # Drain stale frames then re-read controller time
            await self._safe_recv_wait(1.0)
            ctrl_time = await self._read_controller_time()
            if ctrl_time is None:
                raise TimeVerificationError(
                    "Could not re-read controller time during minutes correction."
                )
            _, ctrl_mm, ctrl_ss = ctrl_time
            local_now = datetime.now()
            drift = _mm_ss_delta(ctrl_mm, ctrl_ss, local_now.minute, local_now.second)
            log.info(
                "After edit %d — Controller: %02d:%02d, Local: %02d:%02d, drift=%+ds",
                iteration + 1, ctrl_mm, ctrl_ss, local_now.minute, local_now.second, drift,
            )

        raise TimeVerificationError(
            f"Could not bring drift within {MAX_SECONDS_ONLY_DELTA}s "
            f"after {MAX_MINUTE_ITERS} minute corrections."
        )

    async def _correct_seconds(self, drift: int):
        """
        Correct the seconds field only.  Waits for the safe timing window
        before navigating, then types the target seconds value and commits
        exactly when local time reaches that second.

        Safe windows (enforced by _wait_for_seconds_window):
          drift < 0 (ctrl behind): act when local.second + TIME_LEAD_SECONDS < 60
          drift > 0 (ctrl ahead):  act when local.second < 10
        """
        await self._wait_for_seconds_window(drift)
        await self._navigate_to_field(SECONDS_CURSOR_ROW, SECONDS_CURSOR_COL)

        local_now = datetime.now()
        target_dt = local_now + timedelta(seconds=TIME_LEAD_SECONDS)

        # Guard: if typing + lead would cross a minute boundary, bail out
        if target_dt.minute != local_now.minute:
            raise TimeVerificationError(
                "Commit second would cross a minute boundary — aborting this attempt."
            )

        target_ss = target_dt.second
        log.info(
            "Typing seconds=%02d, committing at local %02d:%02d:%02d …",
            target_ss, target_dt.hour, target_dt.minute, target_dt.second,
        )

        await self._send(DIGIT_KEYS[str(target_ss // 10)])
        await asyncio.sleep(0.1)
        await self._send(DIGIT_KEYS[str(target_ss % 10)])
        await asyncio.sleep(0.1)

        # Block until local clock reaches commit time, then fire Enter
        while datetime.now() < target_dt:
            await asyncio.sleep(0.005)

        log.info("NOW — sending Enter.")
        await self._send(KEY_ENTER)

        # ── Verification ─────────────────────────────────────────────────────
        log.info("Verifying clock for %.1f seconds …", VERIFICATION_WINDOW)
        verify_deadline = asyncio.get_event_loop().time() + VERIFICATION_WINDOW
        verified = False

        while asyncio.get_event_loop().time() < verify_deadline:
            remaining = verify_deadline - asyncio.get_event_loop().time()
            try:
                raw = await asyncio.wait_for(self._recv(), timeout=remaining)
            except asyncio.TimeoutError:
                break

            screen = self.get_screen_text(raw)

            # Safety gate: if we've left CLOCK OPTION, fail fast rather than
            # trying to navigate or verify on the wrong screen
            if "CLOCK OPTION" not in screen:
                raise TimeVerificationError(
                    f"Left CLOCK OPTION screen during verification. "
                    f"Screen now: {screen[:60]!r}"
                )

            # Anchor regex on day abbreviation to avoid matching SET TIME / SYNC REF
            m = re.search(r"[A-Z]{3}\s+(\d{2}):(\d{2}):(\d{2})", screen)
            if m:
                ctrl_m, ctrl_s = int(m.group(2)), int(m.group(3))
                local = datetime.now()
                delta = abs(_mm_ss_delta(ctrl_m, ctrl_s, local.minute, local.second))
                log.debug(
                    "Controller: %02d:%02d  Local: %02d:%02d  Δ=%ds",
                    ctrl_m, ctrl_s, local.minute, local.second, delta,
                )
                if delta <= 1:
                    verified = True
                    break

        if not verified:
            raise TimeVerificationError(
                "Controller mm:ss does not match local time within 1-second tolerance."
            )

    async def _wait_for_seconds_window(self, drift: int, max_wait: float = 65.0):
        """
        Wait until the timing window is safe for a seconds-only commit, while
        continuing to receive WebSocket messages so heartbeats keep firing and
        the connection stays alive.

        Controller BEHIND (drift < 0):
          Safe when local.second ≤ (59 − TIME_LEAD_SECONDS).

        Controller AHEAD (drift > 0):
          Safe when local.second < 10.
        """
        deadline = asyncio.get_event_loop().time() + max_wait
        safe_upper = 59 - TIME_LEAD_SECONDS   # e.g. 54 with lead=5

        while asyncio.get_event_loop().time() < deadline:
            s = datetime.now().second
            if drift <= 0:
                if s <= safe_upper:
                    log.debug("Seconds window open (ctrl behind, local_s=%d).", s)
                    return
            else:
                if s < 10:
                    log.debug("Seconds window open (ctrl ahead, local_s=%d).", s)
                    return

            await self._safe_recv_wait(0.5)

        raise TimeVerificationError(
            f"Timed out waiting for safe seconds-edit window (drift={drift:+d}s)."
        )

    # ── Step 5: Logout ────────────────────────────────────────────────────────

    async def logout(self):
        """Send Special Function then Status to log out."""
        log.info("Logging out (SPEC FUNC → STATUS) …")
        try:
            await self._send(KEY_SPEC_FUNC)
            await asyncio.sleep(0.3)
            await self._send(KEY_STATUS)
            log.info("Logout commands sent.")
        except Exception as e:
            log.warning("Error during logout send: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
# High-Level Scheduler Manager
# ══════════════════════════════════════════════════════════════════════════════

class SchedulerManager:
    """
    Intended to be called by cron or a task scheduler.

    Retry intervals are differentiated by exception type:
      UserActiveError / SessionActiveError  → retry_busy_minutes    (default 30)
      NavigationError / Cursor / Verify     → retry_failure_minutes (default 5)
    """

    def __init__(
        self,
        retry_busy_minutes:    int = RETRY_BUSY_MINUTES,
        retry_failure_minutes: int = RETRY_FAILURE_MINUTES,
    ):
        self.retry_busy_minutes    = retry_busy_minutes
        self.retry_failure_minutes = retry_failure_minutes

    async def run(self):
        """Execute the full time-synchronisation flow."""
        log.info("=" * 60)
        log.info("EOS Time Sync — %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        log.info("=" * 60)

        try:
            async with EOSController() as ctrl:
                await ctrl.observe_for_active_user()

                if await ctrl.check_time_in_sync():
                    # Controller is already within tolerance — skip login entirely.
                    # __aexit__ will still run but logout is a no-op if we never
                    # logged in (the send will simply go to the STATUS screen).
                    log.info("✓ Controller already in sync — no changes made.")
                    return True

                await ctrl.login()
                await ctrl.navigate_to_clock()
                await ctrl.set_time()

            log.info("✓ Time synchronisation completed successfully.")
            return True

        except (UserActiveError, SessionActiveError) as e:
            log.warning("Panel in use – no changes made. Reason: %s", e)
            log.info("Scheduling retry in %d minutes.", self.retry_busy_minutes)
            await self._schedule_retry(self.retry_busy_minutes)
            return False

        except (NavigationError, CursorPositionError, TimeVerificationError) as e:
            log.error("Operational failure: %s", e)
            log.info("Scheduling retry in %d minutes.", self.retry_failure_minutes)
            await self._schedule_retry(self.retry_failure_minutes)
            return False

        except Exception as e:
            log.exception("Unexpected error: %s", e)
            log.info("Scheduling retry in %d minutes.", self.retry_failure_minutes)
            await self._schedule_retry(self.retry_failure_minutes)
            return False

    async def _schedule_retry(self, minutes: int):
        """Schedule a retry via Unix `at`; logs a warning if unavailable."""
        script_path = __file__
        retry_time  = f"now + {minutes} minutes"
        try:
            result = subprocess.run(
                ["at", retry_time, "-f", script_path],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                log.info("Retry scheduled via `at`: %s", retry_time)
            else:
                log.warning(
                    "`at` command failed (rc=%d). "
                    "Ensure this script is called by cron every %d minutes.",
                    result.returncode, minutes,
                )
        except FileNotFoundError:
            log.warning(
                "`at` not available. "
                "Run via cron every %d minutes for automatic retry.", minutes,
            )


# ══════════════════════════════════════════════════════════════════════════════
# Entry Point
# ══════════════════════════════════════════════════════════════════════════════

def run_with_retry(
    retry_busy_minutes:    int = RETRY_BUSY_MINUTES,
    retry_failure_minutes: int = RETRY_FAILURE_MINUTES,
):
    """
    Convenience wrapper — instantiates SchedulerManager and runs the event loop.
    Call this from an external orchestrator or directly via __main__.
    """
    manager = SchedulerManager(
        retry_busy_minutes=retry_busy_minutes,
        retry_failure_minutes=retry_failure_minutes,
    )
    success = asyncio.run(manager.run())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    run_with_retry()