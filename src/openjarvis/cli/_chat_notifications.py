"""Between-turn completion notifications for background work."""

from __future__ import annotations

from openjarvis.cli._bg_state import BgStatus


class NotificationDispatcher:
    """Compute one-shot notifications when background tasks transition state.

    Construct with the BgStatus snapshot at chat start; call ``diff(latest)``
    after each turn to get a list of new notification strings.  Each
    transition fires exactly once per session.
    """

    def __init__(self, initial: BgStatus) -> None:
        self._reported_rust: bool = initial.rust_extension in ("ready", "failed")
        self._reported_models: set[str] = {
            m for m, s in initial.models.items() if s in ("ready", "failed")
        }

    def diff(self, latest: BgStatus) -> list[str]:
        msgs: list[str] = []

        if not self._reported_rust:
            if latest.rust_extension == "ready":
                msgs.append("✓ Rust extension ready — memory features unlocked")
                self._reported_rust = True
            elif latest.rust_extension == "failed":
                msgs.append(
                    "⚠ Rust extension failed to build (memory features unavailable). "
                    "Run `jarvis doctor` for details."
                )
                self._reported_rust = True

        for model_id, state in latest.models.items():
            if model_id in self._reported_models:
                continue
            if state == "ready":
                msgs.append(f"✓ {model_id} ready — try `/model {model_id}`")
                self._reported_models.add(model_id)
            elif state == "failed":
                msgs.append(
                    f"⚠ {model_id} download failed. Run `jarvis doctor` for details."
                )
                self._reported_models.add(model_id)

        return msgs
