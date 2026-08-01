from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _module():
    path = (
        Path(__file__).resolve().parents[2] / "scripts" / "phase8_final_live_smoke.py"
    )
    spec = importlib.util.spec_from_file_location("phase8_final_live_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_claim_is_durable_before_sdk_and_second_attempt_is_blocked(
    tmp_path: Path,
) -> None:
    module = _module()
    proof = tmp_path / "codex-live-smoke-proof.json"
    calls = 0

    def factory(config):
        nonlocal calls
        calls += 1
        claimed = json.loads(proof.read_text(encoding="utf-8"))
        assert claimed["status"] == "claimed_before_sdk_call"
        return module._FakeCodex(config)

    payload = await module.execute_once(proof, client_factory=factory)
    assert calls == 1
    assert payload["status"] == "passed"
    assert payload["marker"] == "JARVIS-FINAL-LIVE-OK"
    assert payload["trace_evaluation"]["evaluation_class"] == "completed"
    assert set(payload) == {
        "task_id",
        "session_id",
        "time",
        "backend",
        "status",
        "marker",
        "trace_evaluation",
    }

    with pytest.raises(FileExistsError):
        await module.execute_once(proof, client_factory=factory)
    assert calls == 1


@pytest.mark.asyncio
async def test_fake_preflight_is_hermetic(tmp_path: Path, monkeypatch) -> None:
    module = _module()

    def forbidden_socket(*_args, **_kwargs):
        raise AssertionError("fake preflight attempted network access")

    monkeypatch.setattr("socket.socket", forbidden_socket)
    await module.fake_preflight()
    assert list(tmp_path.iterdir()) == []


def test_result_allows_reasoning_but_rejects_tool_items() -> None:
    module = _module()
    safe = SimpleNamespace(
        final_response=module.MARKER,
        items=(SimpleNamespace(type="reasoning"), SimpleNamespace(type="agentMessage")),
    )
    module._validate_result(safe)

    prohibited = SimpleNamespace(
        final_response=module.MARKER,
        items=(SimpleNamespace(type="commandExecution"),),
    )
    with pytest.raises(RuntimeError, match="prohibited tool"):
        module._validate_result(prohibited)
