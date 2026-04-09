"""Operator manager — lifecycle management for autonomous operators."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.operators.event_engine import EventTriggerEngine
from openjarvis.operators.loader import load_operator
from openjarvis.operators.types import OperatorManifest

logger = logging.getLogger(__name__)

# Default tick prompt sent to the operative agent
_TICK_PROMPT = "[OPERATOR TICK] Execute your operational protocol."


class OperatorManager:
    """Manages operator manifests and their lifecycle via the TaskScheduler.

    Parameters
    ----------
    system:
        A ``JarvisSystem`` instance (used to access scheduler, session_store,
        memory_backend, and to run operators via ``system.ask()``).
    """

    def __init__(self, system: Any) -> None:
        self._system = system
        self._manifests: Dict[str, OperatorManifest] = {}
        # operator_id -> active EventTriggerEngine (only for event-driven operators)
        self._event_engines: Dict[str, EventTriggerEngine] = {}

    # -- Registration --------------------------------------------------------

    def register(self, manifest: OperatorManifest) -> None:
        """Register an operator manifest."""
        self._manifests[manifest.id] = manifest
        logger.info("Registered operator: %s", manifest.id)

    def discover(self, directory: str | Path) -> List[OperatorManifest]:
        """Discover and register operator manifests from a directory.

        Scans for ``*.toml`` files in *directory* and loads each as an
        operator manifest.
        """
        directory = Path(directory).expanduser()
        found: List[OperatorManifest] = []
        if not directory.is_dir():
            return found
        for toml_path in sorted(directory.glob("*.toml")):
            try:
                manifest = load_operator(toml_path)
                self.register(manifest)
                found.append(manifest)
            except Exception:
                logger.warning("Failed to load operator from %s", toml_path)
        return found

    # -- Lifecycle -----------------------------------------------------------

    def activate(self, operator_id: str) -> str:
        """Activate an operator by creating a scheduler task.

        Returns the scheduler task ID (deterministic: ``operator:{id}``).

        Raises ``KeyError`` if the operator is not registered, or
        ``RuntimeError`` if the scheduler is not available.
        """
        manifest = self._manifests.get(operator_id)
        if manifest is None:
            raise KeyError(f"Operator not registered: {operator_id}")

        scheduler = self._system.scheduler
        if scheduler is None:
            raise RuntimeError(
                "TaskScheduler not available. Enable [scheduler] in config."
            )

        task_id = f"operator:{operator_id}"

        # Check if already active
        try:
            existing = scheduler.list_tasks()
            for t in existing:
                if t.id == task_id and t.status == "active":
                    logger.info("Operator %s already active", operator_id)
                    return task_id
        except Exception:
            pass

        tools_str = ",".join(manifest.tools) if manifest.tools else ""

        metadata: Dict[str, Any] = {
            "operator_id": operator_id,
            "system_prompt": manifest.system_prompt,
            "temperature": manifest.temperature,
            "max_turns": manifest.max_turns,
        }

        # Use the scheduler's create_task but with a deterministic ID
        task = scheduler.create_task(
            prompt=_TICK_PROMPT,
            schedule_type=manifest.schedule_type,
            schedule_value=manifest.schedule_value,
            agent="operative",
            tools=tools_str,
            metadata=metadata,
        )
        # Override the random ID with our deterministic one
        task_dict = task.to_dict()
        task_dict["id"] = task_id
        scheduler._store.save_task(task_dict)

        logger.info("Activated operator %s (task_id=%s)", operator_id, task_id)

        # Start event-driven watchers if the manifest declares event triggers
        if manifest.event_triggers:
            self._start_event_engine(operator_id, manifest)

        return task_id

    def deactivate(self, operator_id: str) -> None:
        """Deactivate an operator by cancelling its scheduler task."""
        # Stop event engine first (if any)
        self._stop_event_engine(operator_id)

        scheduler = self._system.scheduler
        if scheduler is None:
            raise RuntimeError("TaskScheduler not available.")
        task_id = f"operator:{operator_id}"
        try:
            scheduler.cancel_task(task_id)
            logger.info("Deactivated operator %s", operator_id)
        except KeyError:
            logger.warning("No active task for operator %s", operator_id)

    # -- Event engine helpers -------------------------------------------------

    def _start_event_engine(
        self, operator_id: str, manifest: OperatorManifest
    ) -> None:
        """Spin up an ``EventTriggerEngine`` for the given operator."""
        # Stop any existing engine for this operator first
        self._stop_event_engine(operator_id)

        bus = getattr(self._system, "bus", None)
        if bus is None:
            logger.warning(
                "No EventBus on system — event triggers for operator %s will "
                "not fire.  Make sure the system was built with an EventBus.",
                operator_id,
            )
            return

        def _tick_callback(oid: str, prompt: str) -> None:
            """Run the operator agent with the event-enriched prompt."""
            op_manifest = self._manifests.get(oid)
            system_prompt = op_manifest.system_prompt if op_manifest else ""
            try:
                self._system.ask(
                    prompt,
                    agent="operative",
                    operator_id=oid,
                    system_prompt=system_prompt or None,
                )
            except Exception:
                logger.exception(
                    "Event tick failed for operator %s", oid
                )

        engine = EventTriggerEngine(
            operator_id=operator_id,
            bus=bus,
            tick_callback=_tick_callback,
        )
        engine.start(manifest.event_triggers)
        self._event_engines[operator_id] = engine
        logger.info(
            "Started event engine for operator %s (%d trigger(s))",
            operator_id,
            len(manifest.event_triggers),
        )

    def _stop_event_engine(self, operator_id: str) -> None:
        """Stop and remove the ``EventTriggerEngine`` for the given operator."""
        engine = self._event_engines.pop(operator_id, None)
        if engine is not None:
            engine.stop()

    def pause(self, operator_id: str) -> None:
        """Pause an active operator."""
        scheduler = self._system.scheduler
        if scheduler is None:
            raise RuntimeError("TaskScheduler not available.")
        scheduler.pause_task(f"operator:{operator_id}")
        logger.info("Paused operator %s", operator_id)

    def resume(self, operator_id: str) -> None:
        """Resume a paused operator."""
        scheduler = self._system.scheduler
        if scheduler is None:
            raise RuntimeError("TaskScheduler not available.")
        scheduler.resume_task(f"operator:{operator_id}")
        logger.info("Resumed operator %s", operator_id)

    def status(self) -> List[Dict[str, Any]]:
        """Return status of all registered operators.

        Merges manifest info with scheduler task state.
        """
        results: List[Dict[str, Any]] = []
        scheduler = self._system.scheduler

        for op_id, manifest in self._manifests.items():
            info: Dict[str, Any] = {
                "id": op_id,
                "name": manifest.name,
                "description": manifest.description,
                "schedule_type": manifest.schedule_type,
                "schedule_value": manifest.schedule_value,
                "tools": manifest.tools,
                "status": "registered",
                "next_run": None,
                "last_run": None,
            }

            if scheduler is not None:
                task_id = f"operator:{op_id}"
                try:
                    tasks = scheduler.list_tasks()
                    for t in tasks:
                        if t.id == task_id:
                            info["status"] = t.status
                            info["next_run"] = t.next_run
                            info["last_run"] = t.last_run
                            break
                except Exception:
                    pass

            results.append(info)
        return results

    def run_once(self, operator_id: str) -> str:
        """Execute a single tick of an operator immediately.

        Useful for development and testing. Returns the agent's response.
        """
        manifest = self._manifests.get(operator_id)
        if manifest is None:
            raise KeyError(f"Operator not registered: {operator_id}")

        tools_list = manifest.tools if manifest.tools else None
        result = self._system.ask(
            _TICK_PROMPT,
            agent="operative",
            tools=tools_list,
            system_prompt=manifest.system_prompt,
            operator_id=operator_id,
            temperature=manifest.temperature,
        )
        if isinstance(result, dict):
            return result.get("content", str(result))
        return str(result)

    def get_manifest(self, operator_id: str) -> Optional[OperatorManifest]:
        """Return the manifest for an operator, or None."""
        return self._manifests.get(operator_id)

    @property
    def manifests(self) -> Dict[str, OperatorManifest]:
        """All registered manifests."""
        return dict(self._manifests)


__all__ = ["OperatorManager"]
