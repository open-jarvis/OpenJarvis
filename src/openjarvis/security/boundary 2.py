"""BoundaryGuard — scans content at device exit points.

Wraps SecretScanner and PIIScanner to redact, warn, or block
secrets and PII before data leaves the device via cloud engines
or external tool calls.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, List, Optional

from openjarvis.core.types import ToolCall

if TYPE_CHECKING:
    from openjarvis.core.events import EventBus
    from openjarvis.security._stubs import BaseScanner

logger = logging.getLogger(__name__)


class SecurityBlockError(Exception):
    """Raised when mode='block' and secrets/PII are detected."""


class BoundaryGuard:
    """Scans outbound content for secrets and PII at device boundaries.

    Parameters
    ----------
    mode:
        Action on findings: ``"redact"`` replaces matches,
        ``"warn"`` logs but passes through, ``"block"`` raises.
    enabled:
        Master switch. When ``False``, all content passes through.
    bus:
        Optional event bus for publishing SECURITY_ALERT events.
    scanners:
        Custom scanners. Defaults to SecretScanner + PIIScanner.
    """

    def __init__(
        self,
        mode: str = "redact",
        *,
        enabled: bool = True,
        bus: Optional["EventBus"] = None,
        scanners: Optional[List["BaseScanner"]] = None,
    ) -> None:
        self._mode = mode
        self._enabled = enabled
        self._bus = bus
        if scanners is not None:
            self._scanners = scanners
        else:
            self._scanners = self._default_scanners()

    @staticmethod
    def _default_scanners() -> List["BaseScanner"]:
        try:
            from openjarvis.security.scanner import PIIScanner, SecretScanner

            return [SecretScanner(), PIIScanner()]
        except (ImportError, Exception) as exc:
            logger.warning(
                "Rust-backed scanners unavailable (%s); "
                "BoundaryGuard running without scanners. "
                "Build the Rust extension: uv run maturin develop",
                exc,
            )
            return []

    def scan_outbound(self, content: str, destination: str) -> str:
        """Scan text before it leaves the device.

        Returns redacted text in ``"redact"`` mode, original text in
        ``"warn"`` mode, or raises ``SecurityBlockError`` in ``"block"``
        mode when findings are detected.
        """
        if not self._enabled or not content:
            return content

        has_findings = False
        redacted = content
        for scanner in self._scanners:
            result = scanner.scan(content)
            if result.findings:
                has_findings = True
                if self._mode == "redact":
                    redacted = scanner.redact(redacted)

        if has_findings:
            self._emit_alert(destination, content)
            if self._mode == "block":
                raise SecurityBlockError(
                    f"Secrets/PII detected in outbound content to {destination}"
                )
            if self._mode == "warn":
                logger.warning(
                    "Secrets/PII detected in outbound content to %s", destination
                )
                return content
            return redacted

        return content

    def check_outbound(self, tool_call: ToolCall) -> ToolCall:
        """Scan tool call arguments before execution.

        Returns a new ToolCall with redacted arguments if needed.
        """
        if not self._enabled or not tool_call.arguments:
            return tool_call

        redacted_args = self.scan_outbound(
            tool_call.arguments, destination=f"tool:{tool_call.name}"
        )
        if redacted_args != tool_call.arguments:
            return replace(tool_call, arguments=redacted_args)
        return tool_call

    def _emit_alert(self, destination: str, content: str) -> None:
        if self._bus is None:
            return
        try:
            from openjarvis.core.events import EventType

            self._bus.publish(
                EventType.SECURITY_ALERT,
                {
                    "source": "boundary_guard",
                    "destination": destination,
                    "mode": self._mode,
                    "content_preview": content[:80],
                },
            )
        except Exception:
            logger.debug("Failed to emit security alert event", exc_info=True)
