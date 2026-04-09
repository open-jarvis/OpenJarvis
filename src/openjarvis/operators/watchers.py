"""Event source watchers for event-driven operators.

Each watcher monitors a real-world source and calls a callback when
an event of interest occurs.  Watchers run in background daemon threads.

Four watcher types are supported:

``FileWatcher``
    Monitors a file or directory for creation/modification/deletion.
    Uses ``watchdog`` if available; falls back to polling ``os.scandir``.

``SystemMetricWatcher``
    Fires when a system metric (CPU, memory, disk) crosses a threshold.
    Requires ``psutil``; skips gracefully if not installed.

``HttpPollWatcher``
    Polls a URL and fires when content changes (hash-based) or always.
    Uses the already-installed ``httpx``.

``BusEventWatcher``
    Subscribes to the ``EventBus`` and fires when a matching event
    is published.  No extra dependencies needed.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Type for the watcher callback: (description: str, event_data: dict) -> None
WatcherCallback = Callable[[str, Dict[str, Any]], None]


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class BaseWatcher:
    """Abstract watcher base class."""

    def __init__(self, config: Dict[str, Any], callback: WatcherCallback) -> None:
        self._config = config
        self._callback = callback
        self._last_fire: float = 0.0
        self._cooldown = float(config.get("cooldown_s", 300))

    def _can_fire(self) -> bool:
        """Enforce cooldown — don't fire more than once per cooldown window."""
        now = time.time()
        if now - self._last_fire < self._cooldown:
            return False
        self._last_fire = now
        return True

    def _fire(self, description: str, data: Dict[str, Any]) -> None:
        if self._can_fire():
            logger.info("Watcher firing: %s", description)
            try:
                self._callback(description, data)
            except Exception:
                logger.exception("Watcher callback raised an exception")

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# File watcher
# ---------------------------------------------------------------------------


class _PollHandler:
    """Pure-Python directory poller used when watchdog is not installed."""

    def __init__(
        self,
        root: Path,
        pattern: str,
        events: list[str],
        callback: WatcherCallback,
        fire_fn: Callable,
    ) -> None:
        self._root = root
        self._pattern = pattern
        self._events = events
        self._callback = callback
        self._fire = fire_fn
        self._snapshot: Dict[str, float] = {}

    def _scan(self) -> Dict[str, float]:
        result: Dict[str, float] = {}
        if not self._root.exists():
            return result
        if self._root.is_file():
            result[str(self._root)] = self._root.stat().st_mtime
            return result
        for entry in os.scandir(self._root):
            p = Path(entry.path)
            if p.match(self._pattern):
                try:
                    result[str(p)] = p.stat().st_mtime
                except OSError:
                    pass
        return result

    def check(self) -> None:
        current = self._scan()
        prev = self._snapshot

        if "created" in self._events:
            for path in set(current) - set(prev):
                self._fire(
                    f"File created: {path}",
                    {"event": "created", "path": path},
                )
        if "deleted" in self._events:
            for path in set(prev) - set(current):
                self._fire(
                    f"File deleted: {path}",
                    {"event": "deleted", "path": path},
                )
        if "modified" in self._events:
            for path in set(current) & set(prev):
                if current[path] != prev[path]:
                    self._fire(
                        f"File modified: {path}",
                        {"event": "modified", "path": path},
                    )

        self._snapshot = current


class FileWatcher(BaseWatcher):
    """Watch a directory (or file) for filesystem changes.

    Configuration keys
    ------------------
    path: str
        Path to watch (``~`` expanded).
    pattern: str
        Glob pattern to match within the directory.  Default ``"*"``.
    events: list[str]
        Which events to care about: ``"created"``, ``"modified"``, ``"deleted"``.
        Default ``["created"]``.
    check_interval_s: int
        Polling interval in seconds (used for polling fallback).  Default 5.
    cooldown_s: int
        Minimum seconds between repeated trigger fires.  Default 300.
    """

    def __init__(self, config: Dict[str, Any], callback: WatcherCallback) -> None:
        super().__init__(config, callback)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._watchdog_observer: Any = None

    def start(self) -> None:
        root = Path(self._config.get("path", ".")).expanduser()
        pattern = self._config.get("pattern", "*")
        events = self._config.get("events", ["created"])
        interval = int(self._config.get("check_interval_s", 5))

        # Try watchdog
        try:
            from watchdog.events import FileSystemEventHandler  # type: ignore[import]
            from watchdog.observers import Observer  # type: ignore[import]

            class _Handler(FileSystemEventHandler):
                def __init__(self_h) -> None:
                    super().__init__()

                def _handle(self_h, ev_type: str, path: str) -> None:
                    if ev_type not in events:
                        return
                    p = Path(path)
                    if p.match(pattern) or str(pattern) == "*":
                        self._fire(
                            f"File {ev_type}: {path}",
                            {"event": ev_type, "path": path},
                        )

                def on_created(self_h, event) -> None:  # type: ignore[override]
                    if not event.is_directory:
                        self_h._handle("created", event.src_path)

                def on_modified(self_h, event) -> None:  # type: ignore[override]
                    if not event.is_directory:
                        self_h._handle("modified", event.src_path)

                def on_deleted(self_h, event) -> None:  # type: ignore[override]
                    if not event.is_directory:
                        self_h._handle("deleted", event.src_path)

            handler = _Handler()
            observer = Observer()
            observer.schedule(handler, str(root), recursive=True)
            observer.start()
            self._watchdog_observer = observer
            logger.debug("FileWatcher using watchdog for %s", root)
            return
        except ImportError:
            logger.debug("watchdog not installed — using polling FileWatcher")

        # Fallback: polling
        poller = _PollHandler(root, pattern, events, self._callback, self._fire)
        poller.check()  # Baseline snapshot

        def _poll_loop() -> None:
            while not self._stop_event.wait(interval):
                poller.check()

        self._thread = threading.Thread(target=_poll_loop, daemon=True, name="file-watcher")
        self._thread.start()
        logger.debug("FileWatcher polling %s every %ds", root, interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._watchdog_observer is not None:
            try:
                self._watchdog_observer.stop()
                self._watchdog_observer.join(timeout=5)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)


# ---------------------------------------------------------------------------
# System metric watcher
# ---------------------------------------------------------------------------


class SystemMetricWatcher(BaseWatcher):
    """Fire when a system metric crosses a threshold.

    Requires ``psutil`` (``pip install psutil``).

    Configuration keys
    ------------------
    metric: str
        ``"cpu_percent"``, ``"memory_percent"``, or ``"disk_percent"``.
    threshold: float
        Numeric threshold value.
    operator: str
        Comparison operator: ``">"``, ``"<"``, ``">="`` or ``"<="``.
    disk_path: str
        Path to check for disk usage (default ``"/"`` on Unix, ``"C:\\"`` on Windows).
    check_interval_s: int
        How often to sample the metric.  Default 30.
    cooldown_s: int
        Min seconds between repeated fires.  Default 300.
    """

    def __init__(self, config: Dict[str, Any], callback: WatcherCallback) -> None:
        super().__init__(config, callback)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _read_metric(self) -> Optional[float]:
        try:
            import psutil  # type: ignore[import]
        except ImportError:
            logger.warning(
                "psutil not installed — SystemMetricWatcher unavailable. "
                "Install with: pip install psutil"
            )
            return None

        metric = self._config.get("metric", "cpu_percent")
        if metric == "cpu_percent":
            return float(psutil.cpu_percent(interval=1))
        if metric == "memory_percent":
            return float(psutil.virtual_memory().percent)
        if metric == "disk_percent":
            disk_path = self._config.get("disk_path", os.path.sep)
            return float(psutil.disk_usage(disk_path).percent)
        logger.warning("Unknown metric: %s", metric)
        return None

    def _compare(self, value: float, threshold: float, op: str) -> bool:
        if op == ">":
            return value > threshold
        if op == "<":
            return value < threshold
        if op in (">=", "=>"):
            return value >= threshold
        if op in ("<=", "=<"):
            return value <= threshold
        return False

    def start(self) -> None:
        interval = int(self._config.get("check_interval_s", 30))
        metric = self._config.get("metric", "cpu_percent")
        threshold = float(self._config.get("threshold", 90.0))
        op = self._config.get("operator", ">")

        def _loop() -> None:
            while not self._stop_event.wait(interval):
                value = self._read_metric()
                if value is None:
                    break
                if self._compare(value, threshold, op):
                    self._fire(
                        f"{metric} is {value:.1f}% ({op} {threshold}%)",
                        {
                            "metric": metric,
                            "value": value,
                            "threshold": threshold,
                            "operator": op,
                        },
                    )

        self._thread = threading.Thread(target=_loop, daemon=True, name="sysmetric-watcher")
        self._thread.start()
        logger.debug(
            "SystemMetricWatcher: %s %s %.1f, checking every %ds",
            metric, op, threshold, interval,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


# ---------------------------------------------------------------------------
# HTTP poll watcher
# ---------------------------------------------------------------------------


class HttpPollWatcher(BaseWatcher):
    """Poll a URL and fire when the content changes or a status code matches.

    Uses ``httpx`` (already a core dependency).

    Configuration keys
    ------------------
    url: str
        URL to poll.
    check_interval_s: int
        Polling interval in seconds.  Default 300.
    fire_on_change: bool
        Fire when response content hash changes.  Default True.
    fire_on_status: int or null
        Fire when response has this specific HTTP status code.
    cooldown_s: int
        Min seconds between fires.  Default 600.
    """

    def __init__(self, config: Dict[str, Any], callback: WatcherCallback) -> None:
        super().__init__(config, callback)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_hash: Optional[str] = None

    def start(self) -> None:
        interval = int(self._config.get("check_interval_s", 300))
        url = self._config.get("url", "")
        fire_on_change = bool(self._config.get("fire_on_change", True))
        fire_on_status = self._config.get("fire_on_status")

        if not url:
            logger.warning("HttpPollWatcher: no URL configured — skipping")
            return

        def _poll() -> None:
            nonlocal fire_on_change, fire_on_status
            try:
                import httpx

                resp = httpx.get(url, timeout=30, follow_redirects=True)
                content_hash = hashlib.md5(resp.content).hexdigest()

                if fire_on_status is not None and resp.status_code == fire_on_status:
                    self._fire(
                        f"URL {url} returned status {resp.status_code}",
                        {"url": url, "status_code": resp.status_code},
                    )

                if fire_on_change and self._last_hash is not None:
                    if content_hash != self._last_hash:
                        self._fire(
                            f"Content changed at {url}",
                            {
                                "url": url,
                                "status_code": resp.status_code,
                                "content_length": len(resp.content),
                            },
                        )

                self._last_hash = content_hash
            except Exception as exc:
                logger.warning("HttpPollWatcher error for %s: %s", url, exc)

        def _loop() -> None:
            _poll()  # Initial baseline
            while not self._stop_event.wait(interval):
                _poll()

        self._thread = threading.Thread(target=_loop, daemon=True, name="http-watcher")
        self._thread.start()
        logger.debug("HttpPollWatcher polling %s every %ds", url, interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


# ---------------------------------------------------------------------------
# EventBus watcher
# ---------------------------------------------------------------------------


class BusEventWatcher(BaseWatcher):
    """Fire when a matching event is published on the EventBus.

    No extra dependencies needed — subscribes directly to the bus.

    Configuration keys
    ------------------
    event_type: str
        The ``EventType`` value to listen for (e.g. ``"channel_message_received"``).
    filter_key: str (optional)
        If set, the event's ``data[filter_key]`` must match ``filter_value``.
    filter_value: str (optional)
        Value to match against ``data[filter_key]``.
    cooldown_s: int
        Min seconds between fires.  Default 10 (bus events can be frequent).
    """

    def __init__(
        self,
        config: Dict[str, Any],
        callback: WatcherCallback,
        bus: Any,
    ) -> None:
        super().__init__(config, callback)
        self._bus = bus
        self._event_type_val: Optional[Any] = None

    def _on_event(self, event: Any) -> None:
        filter_key = self._config.get("filter_key", "")
        filter_value = self._config.get("filter_value", "")

        if filter_key:
            actual = str(event.data.get(filter_key, ""))
            if actual != str(filter_value):
                return

        self._fire(
            f"EventBus event: {event.event_type}",
            {"event_type": str(event.event_type), "data": dict(event.data)},
        )

    def start(self) -> None:
        from openjarvis.core.events import EventType

        event_type_str = self._config.get("event_type", "")
        if not event_type_str:
            logger.warning("BusEventWatcher: no event_type configured — skipping")
            return

        try:
            self._event_type_val = EventType(event_type_str)
        except ValueError:
            logger.warning("BusEventWatcher: unknown event_type '%s'", event_type_str)
            return

        self._bus.subscribe(self._event_type_val, self._on_event)
        logger.debug("BusEventWatcher subscribed to %s", event_type_str)

    def stop(self) -> None:
        if self._event_type_val is not None and self._bus is not None:
            try:
                self._bus.unsubscribe(self._event_type_val, self._on_event)
            except Exception:
                pass


__all__ = [
    "BaseWatcher",
    "BusEventWatcher",
    "FileWatcher",
    "HttpPollWatcher",
    "SystemMetricWatcher",
    "WatcherCallback",
]
