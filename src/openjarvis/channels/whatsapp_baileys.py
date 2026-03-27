"""WhatsAppBaileysChannel -- bidirectional WhatsApp messaging via Baileys protocol.

Spawns a Node.js subprocess that runs the Baileys bridge (JSON-line protocol
on stdio).  The bridge handles QR-code authentication, message sending, and
incoming-message forwarding.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.channels._stubs import (
    BaseChannel,
    ChannelHandler,
    ChannelMessage,
    ChannelStatus,
)
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry

logger = logging.getLogger(__name__)

# Path to the bundled bridge shipped inside the package.
# In editable installs this lives next to this file; in wheel installs
# it is placed under _node_modules/ to avoid namespace package conflicts.
_BRIDGE_SRC = Path(__file__).resolve().parent / "whatsapp_baileys_bridge"
if not _BRIDGE_SRC.exists():
    _BRIDGE_SRC = (
        Path(__file__).resolve().parents[2]
        / "_node_modules"
        / "whatsapp_baileys_bridge"
    )

# Default runtime directory (npm install + auth state).
_DEFAULT_RUNTIME_DIR = Path.home() / ".openjarvis" / "whatsapp_baileys_bridge"


@ChannelRegistry.register("whatsapp_baileys")
class WhatsAppBaileysChannel(BaseChannel):
    """Bidirectional WhatsApp channel using the Baileys protocol.

    Communicates with a Node.js bridge subprocess over JSON-line stdio.

    Parameters
    ----------
    auth_dir:
        Directory for Baileys auth state persistence.  Defaults to
        ``~/.openjarvis/whatsapp_baileys_bridge/auth``.
    assistant_name:
        Display name used by the assistant in conversations.
    assistant_has_own_number:
        If ``True`` the assistant has a dedicated WhatsApp number and will
        not filter out its own messages.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "whatsapp_baileys"

    def __init__(
        self,
        *,
        auth_dir: str = "",
        assistant_name: str = "Jarvis",
        assistant_has_own_number: bool = False,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._auth_dir = auth_dir
        self._assistant_name = assistant_name
        self._assistant_has_own_number = assistant_has_own_number
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._runtime_dir = _DEFAULT_RUNTIME_DIR
        self._last_qr: str = ""

    # -- bridge lifecycle -------------------------------------------------------

    def _ensure_bridge(self) -> Path:
        """Copy bundled bridge to runtime dir and run ``npm install`` if needed.

        Returns the path to ``dist/bridge.js``.

        Raises
        ------
        RuntimeError
            If ``node`` is not found on ``PATH``.
        """
        if shutil.which("node") is None:
            raise RuntimeError(
                "Node.js is required for WhatsAppBaileysChannel but 'node' "
                "was not found on PATH.  Install Node.js 22+ and try again."
            )

        runtime = self._runtime_dir
        runtime.mkdir(parents=True, exist_ok=True)

        # Copy package.json + dist/ from bundled source if not already present,
        # or if the bundled version is newer.
        pkg_dst = runtime / "package.json"
        pkg_src = _BRIDGE_SRC / "package.json"
        if pkg_src.exists() and (
            not pkg_dst.exists() or pkg_src.stat().st_mtime > pkg_dst.stat().st_mtime
        ):
            shutil.copy2(pkg_src, pkg_dst)

        dist_dst = runtime / "dist"
        dist_src = _BRIDGE_SRC / "dist"
        if dist_src.exists():
            if dist_dst.exists():
                shutil.rmtree(dist_dst)
            shutil.copytree(dist_src, dist_dst)

        # Run npm install if node_modules is missing.
        node_modules = runtime / "node_modules"
        if not node_modules.exists():
            logger.info("Running npm install in %s", runtime)
            subprocess.run(
                ["npm", "install", "--production"],
                cwd=str(runtime),
                check=True,
                capture_output=True,
            )

        bridge_js = runtime / "dist" / "bridge.js"
        if not bridge_js.exists():
            raise RuntimeError(
                f"Bridge entry point not found at {bridge_js}.  "
                "Ensure the bridge TypeScript has been compiled."
            )
        return bridge_js

    # -- BaseChannel interface ---------------------------------------------------

    def connect(self) -> None:
        """Spawn the Node.js bridge subprocess and start the reader thread."""
        if self._status == ChannelStatus.CONNECTED:
            return

        self._status = ChannelStatus.CONNECTING

        try:
            bridge_js = self._ensure_bridge()
        except RuntimeError as exc:
            logger.error("Bridge setup failed: %s", exc)
            self._status = ChannelStatus.ERROR
            return

        auth = self._auth_dir or str(self._runtime_dir / "auth")

        try:
            self._stop_event.clear()
            self._process = subprocess.Popen(
                ["node", str(bridge_js), "--auth-dir", auth],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                daemon=True,
            )
            self._reader_thread.start()
            logger.info(
                "WhatsApp Baileys bridge started (pid=%s)",
                self._process.pid,
            )
        except Exception:
            logger.exception("Failed to start bridge subprocess")
            self._status = ChannelStatus.ERROR

    def disconnect(self) -> None:
        """Send disconnect command to the bridge and terminate the subprocess."""
        self._stop_event.set()

        if self._process is not None and self._process.stdin is not None:
            try:
                self._write_command({"type": "disconnect"})
            except Exception:
                logger.debug("Could not send disconnect command", exc_info=True)

        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5.0)
            except Exception:
                logger.debug("Bridge process termination error", exc_info=True)
            self._process = None

        if self._reader_thread is not None:
            self._reader_thread.join(timeout=5.0)
            self._reader_thread = None

        self._status = ChannelStatus.DISCONNECTED

    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        """Send a message to a WhatsApp JID via the bridge subprocess."""
        if self._process is None or self._status != ChannelStatus.CONNECTED:
            logger.warning("Cannot send: bridge not connected")
            return False

        try:
            self._write_command(
                {
                    "type": "send",
                    "jid": channel,
                    "text": content,
                }
            )
            self._publish_sent(channel, content, conversation_id)
            return True
        except Exception:
            logger.debug("WhatsApp Baileys send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["whatsapp_baileys"]

    def on_message(self, handler: ChannelHandler) -> None:
        """Register a callback for incoming messages."""
        self._handlers.append(handler)

    # -- internal helpers -------------------------------------------------------

    def _write_command(self, cmd: Dict[str, Any]) -> None:
        """Write a JSON-line command to the bridge's stdin."""
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("Bridge process not running")
        line = json.dumps(cmd, separators=(",", ":")) + "\n"
        self._process.stdin.write(line)
        self._process.stdin.flush()

    def _reader_loop(self) -> None:
        """Background thread: read JSON lines from bridge stdout."""
        proc = self._process
        if proc is None or proc.stdout is None:
            return

        try:
            for raw_line in proc.stdout:
                if self._stop_event.is_set():
                    break

                line = raw_line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("Non-JSON line from bridge: %s", line)
                    continue

                self._handle_bridge_event(event)
        except Exception:
            if not self._stop_event.is_set():
                logger.debug("Reader loop error", exc_info=True)
                self._status = ChannelStatus.ERROR

    def _handle_bridge_event(self, event: Dict[str, Any]) -> None:
        """Dispatch a single JSON event from the bridge."""
        event_type = event.get("type", "")

        if event_type == "status":
            new_status = event.get("status", "")
            if new_status == "connected":
                self._status = ChannelStatus.CONNECTED
                logger.info("WhatsApp Baileys bridge connected")
            elif new_status == "disconnected":
                self._status = ChannelStatus.DISCONNECTED

        elif event_type == "qr":
            self._last_qr = event.get("data", "")
            logger.info("WhatsApp QR code received -- scan to authenticate")

        elif event_type == "message":
            cm = ChannelMessage(
                channel="whatsapp_baileys",
                sender=event.get("sender", ""),
                content=event.get("text", ""),
                message_id=event.get("message_id", ""),
                conversation_id=event.get("jid", ""),
            )
            for handler in self._handlers:
                try:
                    handler(cm)
                except Exception:
                    logger.exception("WhatsApp Baileys handler error")
            if self._bus is not None:
                self._bus.publish(
                    EventType.CHANNEL_MESSAGE_RECEIVED,
                    {
                        "channel": cm.channel,
                        "sender": cm.sender,
                        "content": cm.content,
                        "message_id": cm.message_id,
                    },
                )

        elif event_type == "error":
            logger.error("Bridge error: %s", event.get("message", "unknown"))
            self._status = ChannelStatus.ERROR

    def _publish_sent(self, channel: str, content: str, conversation_id: str) -> None:
        """Publish a CHANNEL_MESSAGE_SENT event on the bus."""
        if self._bus is not None:
            self._bus.publish(
                EventType.CHANNEL_MESSAGE_SENT,
                {
                    "channel": channel,
                    "content": content,
                    "conversation_id": conversation_id,
                },
            )


__all__ = ["WhatsAppBaileysChannel"]
