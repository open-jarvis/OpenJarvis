"""PostHog client wrapper.

A thin adapter over the official ``posthog`` SDK that:
  - Initialises lazily and only if analytics is enabled.
  - Pipes every capture through :mod:`redaction` and :mod:`events` for
    PII stripping and structural validation.
  - Fails silently — analytics must never break the host application.

The underlying SDK handles batching, async send on a background
thread, retries, and silent failure on network errors. We layer
"never crash the app" on top by wrapping every call in try/except.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from openjarvis.analytics.events import validate_event
from openjarvis.analytics.identity import (
    get_or_create_anon_id,
    is_analytics_enabled,
)
from openjarvis.analytics.redaction import redact
from openjarvis.core.config import AnalyticsConfig

logger = logging.getLogger(__name__)


class AnalyticsClient:
    """Send anonymized usage events to PostHog.

    Construct once at server / CLI startup, share for the process
    lifetime, call :meth:`shutdown` on exit to flush pending events.
    """

    def __init__(self, config: AnalyticsConfig, anon_id: str | None = None) -> None:
        self.config = config
        self.anon_id = anon_id or get_or_create_anon_id(config.anon_id_path)
        self._lock = threading.Lock()
        self._posthog: Any = None
        self._enabled = is_analytics_enabled(config)
        if self._enabled:
            self._init_sdk()

    def _init_sdk(self) -> None:
        try:
            from posthog import Posthog

            self._posthog = Posthog(
                project_api_key=self.config.key,
                host=self.config.host,
                # The SDK queues events and flushes on a background
                # thread; these knobs just tune the batch size/cadence.
                max_queue_size=10_000,
                flush_at=self.config.flush_at_size,
                flush_interval=self.config.flush_interval_seconds,
                # Don't sample or auto-capture anything beyond what we
                # explicitly send.
                disable_geoip=True,
            )
            logger.debug(
                "PostHog analytics initialised host=%s anon_id=%s…",
                self.config.host,
                self.anon_id[:8],
            )
        except Exception as exc:
            logger.debug("Analytics SDK init failed (%s); analytics disabled", exc)
            self._posthog = None
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled and self._posthog is not None

    def capture(
        self,
        event_name: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Send one event. Unknown events are silently dropped.

        Runs through redaction → event-spec validation → SDK capture.
        Failures at any stage are swallowed; analytics is best-effort.
        """
        if not self.enabled:
            return
        try:
            raw = properties or {}
            cleaned = redact(raw)
            validated = validate_event(event_name, cleaned)
            if validated is None:
                logger.debug("Dropped unknown analytics event: %s", event_name)
                return
            self._posthog.capture(
                distinct_id=self.anon_id,
                event=event_name,
                properties=validated,
            )
        except Exception as exc:
            logger.debug("Analytics capture failed for %s: %s", event_name, exc)

    def flush(self) -> None:
        """Force-flush queued events. Safe to call repeatedly."""
        if self._posthog is None:
            return
        try:
            self._posthog.flush()
        except Exception:
            pass

    def shutdown(self) -> None:
        """Flush and close the SDK. Call once on process exit."""
        with self._lock:
            if self._posthog is None:
                return
            try:
                self._posthog.flush()
                self._posthog.shutdown()
            except Exception:
                pass
            self._posthog = None
            self._enabled = False


__all__ = ["AnalyticsClient"]
