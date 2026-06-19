"""Eval backend that drives the ToolOrchestra orchestrator as the "model".

This adapts our unified-tool orchestrator rollout
(:func:`openjarvis.agents.hybrid.toolorchestra.rollout.run_unified_rollout`)
to the eval framework's :class:`~openjarvis.evals.core.backend.InferenceBackend`
interface so it can be scored by the existing
:class:`~openjarvis.evals.core.runner.EvalRunner` over any registered benchmark.

The orchestrator is an OpenAI-compatible chat model (served locally via vLLM,
default ``http://localhost:8001/v1``) that emits tool calls over the fixed
8-tool catalog from :func:`expert_registry.orchestrator_catalog`. For each eval
sample we run one full rollout and return ``rollout.final_answer`` as the model
answer, plus token/cost telemetry in the ``generate_full`` payload.

Construction is import-safe and network-free; the OpenAI SDK is only touched
inside ``call_orchestrator`` at generate time (lazy import in ``unified.py``).
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from openjarvis.agents.hybrid.expert_registry import orchestrator_catalog
from openjarvis.agents.hybrid.toolorchestra import rollout as _rollout_mod
from openjarvis.agents.hybrid.toolorchestra.unified import (
    make_call_orchestrator,
    make_dispatch,
)
from openjarvis.evals.core.backend import InferenceBackend

DEFAULT_ENDPOINT = "http://localhost:8001/v1"
DEFAULT_MODEL = "qwen3-8b"


class OrchestratorBackend(InferenceBackend):
    """Run the ToolOrchestra orchestrator rollout as an eval "model".

    Parameters
    ----------
    orchestrator_endpoint:
        OpenAI-compatible base URL for the served orchestrator (vLLM). Defaults
        to ``http://localhost:8001/v1``.
    orchestrator_model:
        Served model id for the orchestrator. Defaults to ``"qwen3-8b"`` (will
        be the Qwen3.5-9B checkpoint later).
    api_key:
        API key for the endpoint. ``"EMPTY"`` for a local vLLM server.
    local_endpoints:
        Optional dict mapping a local OSS model id (e.g. ``"Qwen/Qwen3.5-9B"``)
        to its vLLM base URL. Unmapped local models are still listed in the
        catalog but served as unconfigured (``base_url=None``).
    max_turns:
        Maximum orchestrator reasoning->action->observation turns per sample.
    temperature:
        Orchestrator sampling temperature.
    dispatch_cfg:
        Optional config dict passed to :func:`make_dispatch` (worker dispatch).
    """

    backend_id = "orchestrator"
    framework_name = "openjarvis-orchestrator"

    def __init__(
        self,
        *,
        orchestrator_endpoint: str = DEFAULT_ENDPOINT,
        orchestrator_model: str = DEFAULT_MODEL,
        api_key: str = "EMPTY",
        local_endpoints: Optional[Dict[str, str]] = None,
        max_turns: int = 8,
        temperature: float = 1.0,
        dispatch_cfg: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.orchestrator_endpoint = orchestrator_endpoint
        self.orchestrator_model = orchestrator_model
        self.api_key = api_key
        self.local_endpoints = dict(local_endpoints or {})
        self.max_turns = int(max_turns)
        self.temperature = float(temperature)
        self._dispatch_cfg = dict(dispatch_cfg or {})

        # Build the catalog once; it is stateless. ``local_endpoints`` now maps
        # full local model ids (e.g. ``"Qwen/Qwen3.5-9B"``) -> vLLM base_url.
        self._tools = orchestrator_catalog(local_endpoints=self.local_endpoints)

    # ------------------------------------------------------------------
    # InferenceBackend abstract methods
    # ------------------------------------------------------------------
    def generate(
        self,
        prompt: str,
        *,
        model: str,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        """Run a rollout and return just the final-answer text."""
        full = self.generate_full(
            prompt,
            model=model,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return full.get("content", "") or ""

    def generate_full(
        self,
        prompt: str,
        *,
        model: str,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        """Run one orchestrator rollout over ``prompt`` and return full details.

        Returns a dict with the keys the runner reads: ``content``, ``usage``,
        ``model``, ``latency_seconds``, ``cost_usd``, plus ``tool_calls`` /
        ``turn_count`` / ``framework``. On error, returns ``content=""`` and a
        non-empty ``error`` field so the runner records it as a failed sample
        rather than crashing the whole run.
        """
        # The caller-supplied ``model`` is the RunConfig.model (the orchestrator
        # model name). Fall back to the configured one if blank.
        orch_model = model or self.orchestrator_model
        # Prefer the explicit per-call temperature only when the caller set a
        # non-default value; otherwise use the backend's configured temperature.
        temp = temperature if temperature else self.temperature

        started = time.time()
        try:
            call_orch = make_call_orchestrator(
                orch_model,
                base_url=self.orchestrator_endpoint,
                api_key=self.api_key,
                temperature=temp,
                max_tokens=max_tokens,
            )
            dispatch = make_dispatch(self._dispatch_cfg)
            rollout = _rollout_mod.run_unified_rollout(
                prompt,
                self._tools,
                call_orchestrator=call_orch,
                dispatch=dispatch,
                max_turns=self.max_turns,
            )
        except Exception as exc:  # noqa: BLE001 - surface as a failed sample
            return {
                "content": "",
                "error": f"{type(exc).__name__}: {exc}",
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                "model": orch_model,
                "latency_seconds": time.time() - started,
                "cost_usd": 0.0,
                "tool_calls": 0,
                "turn_count": 0,
                "framework": self.framework_name,
            }

        latency = time.time() - started
        total_tokens = int(getattr(rollout, "tokens", 0) or 0)
        return {
            "content": rollout.final_answer or "",
            # The rollout reports a single combined token count; we surface it
            # as completion_tokens so it still flows into total-token telemetry.
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": total_tokens,
            },
            "model": orch_model,
            "latency_seconds": latency,
            "cost_usd": float(getattr(rollout, "cost_usd", 0.0) or 0.0),
            "tool_calls": int(getattr(rollout, "num_tool_calls", 0) or 0),
            "turn_count": len(getattr(rollout, "turns", []) or []),
            "framework": self.framework_name,
            "trace_data": {
                "parse_failures": int(getattr(rollout, "parse_failures", 0) or 0),
                "tool_calls": [
                    {"name": n, "arguments": a} for n, a in rollout.tool_calls()
                ],
            },
        }


__all__ = ["OrchestratorBackend", "DEFAULT_ENDPOINT", "DEFAULT_MODEL"]
