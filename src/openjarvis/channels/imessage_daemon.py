"""iMessage daemon — polls chat.db and routes to DeepResearchAgent.

Monitors a designated iMessage conversation for new messages, routes
them to the agent, and sends responses back via AppleScript.

Requires macOS with Full Disk Access for chat.db reading and
Accessibility permission for AppleScript Messages control.
"""

from __future__ import annotations

import logging
import os
import signal
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = str(Path.home() / "Library" / "Messages" / "chat.db")
_POLL_INTERVAL = 5
_PID_FILE = str(Path.home() / ".openjarvis" / "imessage-agent.pid")


def poll_new_messages(
    *,
    db_path: str = _DEFAULT_DB_PATH,
    last_rowid: int = 0,
    chat_identifier: str = "",
) -> List[Dict[str, Any]]:
    """Return new incoming messages since last_rowid."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.OperationalError:
        return []

    try:
        rows = conn.execute(
            "SELECT m.ROWID as rowid, m.text, m.date, "
            "c.chat_identifier "
            "FROM message m "
            "JOIN chat_message_join cmj "
            "ON cmj.message_id = m.ROWID "
            "JOIN chat c ON c.ROWID = cmj.chat_id "
            "WHERE m.ROWID > ? AND m.is_from_me = 0 "
            "AND m.text IS NOT NULL "
            "AND c.chat_identifier = ? "
            "ORDER BY m.ROWID ASC",
            (last_rowid, chat_identifier),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def send_imessage(chat_identifier: str, message: str) -> bool:
    """Send an iMessage via AppleScript."""
    escaped = message.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'tell application "Messages"\n'
        f"  set targetChat to a reference to "
        f'chat id "{chat_identifier}"\n'
        f'  send "{escaped}" to targetChat\n'
        f"end tell"
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.error("Failed to send iMessage via AppleScript")
        return False


def run_daemon(
    *,
    chat_identifier: str,
    db_path: str = _DEFAULT_DB_PATH,
    handler: Any = None,
    poll_interval: float = _POLL_INTERVAL,
    max_iterations: int = 0,
) -> None:
    """Run the iMessage polling daemon."""
    pid_path = Path(_PID_FILE)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()))

    last_rowid = _get_max_rowid(db_path)
    logger.info(
        "iMessage daemon started — monitoring %s from ROWID %d",
        chat_identifier,
        last_rowid,
    )

    running = True

    def _stop(signum: int, frame: Any) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    iterations = 0
    while running:
        messages = poll_new_messages(
            db_path=db_path,
            last_rowid=last_rowid,
            chat_identifier=chat_identifier,
        )

        for msg in messages:
            last_rowid = msg["rowid"]
            text = msg["text"]
            logger.info("Received: %s", text[:100])

            if handler is not None:
                try:
                    response = handler(text)
                    if response:
                        send_imessage(chat_identifier, response)
                except Exception:
                    logger.exception(
                        "Handler failed for message %d",
                        msg["rowid"],
                    )

        iterations += 1
        if max_iterations and iterations >= max_iterations:
            break
        time.sleep(poll_interval)

    if pid_path.exists():
        pid_path.unlink()
    logger.info("iMessage daemon stopped")


def _get_max_rowid(db_path: str) -> int:
    """Get the current max ROWID from chat.db."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        row = conn.execute("SELECT MAX(ROWID) FROM message").fetchone()
        conn.close()
        return row[0] or 0
    except sqlite3.OperationalError:
        return 0


def is_running() -> bool:
    """Check if the daemon is currently running."""
    pid_path = Path(_PID_FILE)
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        pid_path.unlink(missing_ok=True)
        return False


def stop_daemon() -> bool:
    """Stop the running daemon. Returns True if stopped."""
    pid_path = Path(_PID_FILE)
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        pid_path.unlink(missing_ok=True)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        pid_path.unlink(missing_ok=True)
        return False
