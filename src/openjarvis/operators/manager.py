"""Operator manager — lifecycle management for autonomous operators."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

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
            "metrics": manifest.metrics,
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
        return task_id

    def deactivate(self, operator_id: str) -> None:
        """Deactivate an operator by cancelling its scheduler task."""
        scheduler = self._system.scheduler
        if scheduler is None:
            raise RuntimeError("TaskScheduler not available.")
        task_id = f"operator:{operator_id}"
        try:
            scheduler.cancel_task(task_id)
            logger.info("Deactivated operator %s", operator_id)
        except KeyError:
            logger.warning("No active task for operator %s", operator_id)

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
                "metrics": manifest.metrics,
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

    # -- Metrics -------------------------------------------------------------

    def collect_metrics(
        self,
        operator_id: str,
        *,
        since: Optional[float] = None,
        until: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Collect telemetry metrics declared in the operator's manifest.

        Reads the ``metrics`` list from :class:`OperatorManifest` and queries
        the system's ``TelemetryAggregator`` (when available) for matching
        statistics.  Only fields explicitly listed in ``manifest.metrics`` are
        returned, giving operators fine-grained control over what data they
        expose.

        Parameters
        ----------
        operator_id:
            ID of the registered operator.
        since:
            Optional Unix timestamp; restrict stats to records after this time.
        until:
            Optional Unix timestamp; restrict stats to records before this time.

        Returns
        -------
        Dict[str, Any]
            Mapping of ``{metric_name: value}`` for every metric declared in
            the manifest that could be resolved.  Unknown metric names are
            silently skipped and logged at DEBUG level.

        Raises
        ------
        KeyError
            If *operator_id* is not registered.
        """
        manifest = self._manifests.get(operator_id)
        if manifest is None:
            raise KeyError(f"Operator not registered: {operator_id}")

        if not manifest.metrics:
            logger.debug(
                "Operator %s declares no metrics; returning empty dict.",
                operator_id,
            )
            return {}

        aggregator = getattr(self._system, "telemetry", None)
        if aggregator is None:
            logger.warning(
                "TelemetryAggregator not available on system; "
                "cannot collect metrics for operator %s.",
                operator_id,
            )
            return {}

        try:
            summary = aggregator.summary(since=since, until=until)
        except Exception as exc:
            logger.error(
                "Failed to query telemetry for operator %s: %s",
                operator_id,
                exc,
            )
            return {}

        # Build a flat lookup of all available summary-level stats
        available: Dict[str, Any] = {
            "total_calls": summary.total_calls,
            "total_tokens": summary.total_tokens,
            "total_cost": summary.total_cost,
            "total_latency": summary.total_latency,
            "total_energy_joules": summary.total_energy_joules,
            "avg_throughput_tok_per_sec": (
                summary.avg_throughput_tok_per_sec
            ),
            "avg_gpu_utilization_pct": summary.avg_gpu_utilization_pct,
            "avg_energy_per_output_token_joules": (
                summary.avg_energy_per_output_token_joules
            ),
            "avg_throughput_per_watt": summary.avg_throughput_per_watt,
            "total_prefill_energy_joules": (
                summary.total_prefill_energy_joules
            ),
            "total_decode_energy_joules": (
                summary.total_decode_energy_joules
            ),
            "avg_mean_itl_ms": summary.avg_mean_itl_ms,
            "avg_median_itl_ms": summary.avg_median_itl_ms,
            "avg_p95_itl_ms": summary.avg_p95_itl_ms,
        }

        collected: Dict[str, Any] = {}
        for metric in manifest.metrics:
            if metric in available:
                collected[metric] = available[metric]
            else:
                logger.debug(
                    "Operator %s requested unknown metric '%s'; skipping.",
                    operator_id,
                    metric,
                )

        logger.info(
            "Collected %d/%d metrics for operator %s.",
            len(collected),
            len(manifest.metrics),
            operator_id,
        )
        return collected

    def get_manifest(self, operator_id: str) -> Optional[OperatorManifest]:
        """Return the manifest for an operator, or None."""
        return self._manifests.get(operator_id)

    @property
    def manifests(self) -> Dict[str, OperatorManifest]:
        """All registered manifests."""
        return dict(self._manifests)


__all__ = ["OperatorManager"]
