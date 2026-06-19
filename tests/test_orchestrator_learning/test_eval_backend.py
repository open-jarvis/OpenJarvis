"""Offline tests for the orchestrator eval backend + the eval CLI's
benchmark-name normalization.

No network / models: ``run_unified_rollout`` is monkeypatched to return a
canned rollout, and the dataset-key mapping is asserted against the real
``openjarvis.evals.cli`` registry without instantiating any (network-bound)
dataset.
"""

from __future__ import annotations

import pytest

from openjarvis.learning.intelligence.orchestrator import eval_backend as eb
from openjarvis.learning.intelligence.orchestrator.eval_backend import (
    OrchestratorBackend,
)


class _CannedRollout:
    """Minimal stand-in for UnifiedRollout."""

    def __init__(self, final_answer: str) -> None:
        self.final_answer = final_answer
        self.cost_usd = 0.123
        self.tokens = 42
        self.num_tool_calls = 1
        self.parse_failures = 0
        self.turns = [object()]

    def tool_calls(self):
        return [("web_search", {"query": "x"})]


def _patch_rollout(monkeypatch, rollout):
    """Patch run_unified_rollout where the backend looks it up."""
    monkeypatch.setattr(
        eb._rollout_mod,
        "run_unified_rollout",
        lambda *a, **k: rollout,
    )


def test_construct_is_network_free():
    """Constructing the backend builds the catalog but touches no network."""
    backend = OrchestratorBackend()
    assert backend.backend_id == "orchestrator"
    assert backend.orchestrator_endpoint == eb.DEFAULT_ENDPOINT
    assert backend.orchestrator_model == eb.DEFAULT_MODEL
    # Catalog is non-empty (cloud frontier + local OSS + basic tools).
    assert len(backend._tools) > 0
    names = {t.name for t in backend._tools}
    assert "web_search" in names


def test_local_endpoints_mapping():
    """local_endpoints (model-id -> base_url) wires the local OSS tool."""
    backend = OrchestratorBackend(
        local_endpoints={"Qwen/Qwen3.5-9B": "http://m:9/v1"},
    )
    assert backend.local_endpoints["Qwen/Qwen3.5-9B"] == "http://m:9/v1"
    # The corresponding local-OSS tool should carry that base_url.
    tool = next(t for t in backend._tools if t.model == "Qwen/Qwen3.5-9B")
    assert tool.base_url == "http://m:9/v1"


def test_generate_returns_final_answer(monkeypatch):
    """generate() returns the rollout's final_answer string."""
    _patch_rollout(monkeypatch, _CannedRollout("42"))
    backend = OrchestratorBackend()
    out = backend.generate("what is 6*7?", model="qwen3-8b")
    assert out == "42"


def test_generate_full_payload(monkeypatch):
    """generate_full() returns the runner-expected payload shape."""
    _patch_rollout(monkeypatch, _CannedRollout("42"))
    backend = OrchestratorBackend()
    full = backend.generate_full("q", model="qwen3-8b")
    assert full["content"] == "42"
    assert full["cost_usd"] == 0.123
    assert full["usage"]["completion_tokens"] == 42
    assert full["tool_calls"] == 1
    assert full["turn_count"] == 1
    assert full["framework"] == "openjarvis-orchestrator"
    assert "error" not in full
    assert full["latency_seconds"] >= 0.0


def test_generate_full_error_path(monkeypatch):
    """An exception inside the rollout becomes a recorded error, not a crash."""

    def _boom(*a, **k):
        raise RuntimeError("vllm down")

    monkeypatch.setattr(eb._rollout_mod, "run_unified_rollout", _boom)
    backend = OrchestratorBackend()
    full = backend.generate_full("q", model="qwen3-8b")
    assert full["content"] == ""
    assert "vllm down" in full["error"]
    assert full["usage"]["completion_tokens"] == 0


# ---------------------------------------------------------------------------
# Eval-script benchmark name mapping
# ---------------------------------------------------------------------------

# The 5 benchmarks the eval script targets, by the script's (alias) names.
SCRIPT_BENCHMARKS = [
    "gaia",
    "terminalbench_v2_1",
    "taubench",
    "mmlu_pro",
    "supergpqa",
]


def _load_script():
    import importlib.util
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "orchestrator" / "eval_orchestrator.py"
    spec = importlib.util.spec_from_file_location("eval_orchestrator", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_benchmark_aliases_map_to_registry_keys():
    """Each script benchmark normalizes to a real evals.cli BENCHMARKS key."""
    from openjarvis.evals.cli import BENCHMARKS

    script = _load_script()
    for name in SCRIPT_BENCHMARKS:
        key = script._normalize_benchmark(name)
        assert key in BENCHMARKS, f"{name} -> {key} not in BENCHMARKS registry"


def test_normalize_specific_keys():
    """Spot-check the underscored aliases normalize to the dotted/dashed keys."""
    script = _load_script()
    assert script._normalize_benchmark("terminalbench_v2_1") == "terminalbench-v2.1"
    assert script._normalize_benchmark("mmlu_pro") == "mmlu-pro"
    assert script._normalize_benchmark("gaia") == "gaia"


def test_build_dataset_accepts_keys():
    """_build_dataset must recognise the normalized keys.

    We only assert it doesn't raise the 'Unknown benchmark' ClickException;
    datasets that need network/files at construction are xfail-skipped.
    """
    import click

    from openjarvis.evals.cli import _build_dataset

    script = _load_script()
    for name in SCRIPT_BENCHMARKS:
        key = script._normalize_benchmark(name)
        try:
            _build_dataset(key)
        except click.ClickException as exc:
            if "Unknown benchmark" in str(exc):
                pytest.fail(f"{key} not recognised by _build_dataset")
            # Other ClickExceptions (missing files/creds) are acceptable here.
        except Exception:
            # Construction may require network/files — that's fine; the point
            # is the key is recognised (didn't hit the unknown-benchmark else).
            pytest.skip(f"{key} dataset construction needs resources")
