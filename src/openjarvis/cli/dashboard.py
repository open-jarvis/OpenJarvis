"""TUI dashboard — terminal-based system monitoring via textual."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DashboardApp:
    """Terminal dashboard for OpenJarvis monitoring.

    Panels:
    - System status (engine health, model, memory backend)
    - Live EventBus event stream
    - Telemetry metrics (throughput, latency, energy)
    - Agent activity (current runs, tool calls)
    - Session list (active sessions, last activity)

    Requires: ``uv sync --extra dashboard``
    """

    def __init__(self, config: Optional[Any] = None) -> None:
        self._config = config
        self._events: List[Dict[str, Any]] = []

    @staticmethod
    def available() -> bool:
        """Check if textual is available."""
        try:
            import textual  # noqa: F401

            return True
        except ImportError:
            return False

    def run(self) -> None:
        """Launch the TUI dashboard."""
        try:
            from textual.app import App, ComposeResult  # noqa: F401
            from textual.containers import Container, Horizontal, Vertical  # noqa: F401
            from textual.reactive import reactive  # noqa: F401
            from textual.widgets import (  # noqa: F401
                DataTable,
                Footer,
                Header,
                Log,
                Static,
            )
        except ImportError:
            raise ImportError(
                "TUI dashboard requires 'textual'. "
                "Install with: uv sync --extra dashboard"
            )

        class JarvisDashboard(App):
            """OpenJarvis TUI Dashboard."""

            TITLE = "OpenJarvis Dashboard"
            CSS_PATH = None
            CSS = """
            Screen {
                layout: grid;
                grid-size: 2 2;
                grid-gutter: 1;
            }
            .panel {
                border: solid green;
                padding: 1;
            }
            #status-panel { row-span: 1; }
            #events-panel { row-span: 1; }
            #telemetry-panel { row-span: 1; }
            #agent-panel { row-span: 1; }
            """

            def compose(self) -> ComposeResult:
                yield Header()
                yield Static(
                    "System Status\n"
                    "─────────────\n"
                    "Engine: checking...\n"
                    "Model: checking...\n"
                    "Memory: checking...",
                    id="status-panel",
                    classes="panel",
                )
                yield Log(
                    id="events-panel",
                    classes="panel",
                )
                yield Static(
                    "Telemetry\n─────────\nThroughput: --\nLatency: --\nEnergy: --",
                    id="telemetry-panel",
                    classes="panel",
                )
                yield Static(
                    "Agent Activity\n──────────────\nNo active agents.",
                    id="agent-panel",
                    classes="panel",
                )
                yield Footer()

            def on_mount(self) -> None:
                events_log = self.query_one("#events-panel", Log)
                events_log.write_line("Event stream started...")

                # Try to connect to event bus
                try:
                    from openjarvis.core.events import get_event_bus

                    bus = get_event_bus()

                    def _on_event(event: Any) -> None:
                        try:
                            events_log.write_line(
                                f"[{event.event_type.value}] {event.data}"
                            )
                        except Exception as exc:
                            logger.debug("Event serialization failed: %s", exc)

                    from openjarvis.core.events import EventType

                    for et in EventType:
                        bus.subscribe(et, _on_event)
                except Exception:
                    events_log.write_line("Could not connect to event bus.")

                # Update status
                self._update_status()

            def _update_status(self) -> None:
                status = self.query_one("#status-panel", Static)
                lines = ["System Status", "─────────────"]
                try:
                    from openjarvis.core.config import load_config

                    config = load_config()
                    lines.append(f"Engine: {config.engine.default}")
                    model = config.intelligence.default_model or "auto"
                    lines.append(f"Model: {model}")
                    backend = config.tools.storage.default_backend
                    lines.append(f"Memory: {backend}")
                    sec = "enabled" if config.security.enabled else "disabled"
                    lines.append(f"Security: {sec}")
                    tel = "enabled" if config.telemetry.enabled else "disabled"
                    lines.append(f"Telemetry: {tel}")
                except Exception:
                    lines.append("Config: not loaded")
                status.update("\n".join(lines))

        app = JarvisDashboard()
        app.run()


def launch_dashboard(config: Optional[Any] = None) -> None:
    """Convenience function to launch the dashboard."""
    app = DashboardApp(config=config)
    if not app.available():
        raise ImportError(
            "TUI dashboard requires 'textual'. Install with: uv sync --extra dashboard"
        )
    app.run()


__all__ = ["DashboardApp", "launch_dashboard"]
