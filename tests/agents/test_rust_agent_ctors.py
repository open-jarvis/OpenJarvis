"""Tests for openjarvis_rust agent constructors and host configuration (#1174)."""

from __future__ import annotations

import pytest


def test_rust_agent_classes_construct_without_panic():
    """Verify that all 5 Rust agent classes construct without Tokio reactor panic."""
    openjarvis_rust = pytest.importorskip("openjarvis_rust")

    classes = [
        ("SimpleAgent", "simple", False),
        ("OrchestratorAgent", "orchestrator", True),
        ("NativeReActAgent", "native_react", True),
        ("NativeOpenHandsAgent", "native_openhands", True),
        ("MonitorOperativeAgent", "monitor_operative", True),
    ]

    for class_name, expected_id, expected_tools in classes:
        cls = getattr(openjarvis_rust, class_name)
        agent = cls()
        assert agent.agent_id() == expected_id
        assert agent.accepts_tools() is expected_tools


def test_rust_agent_classes_accept_custom_host_and_engine():
    """Verify that agent constructors accept explicit host and engine configurations."""
    openjarvis_rust = pytest.importorskip("openjarvis_rust")

    custom_host = "http://127.0.0.1:9999"

    # Default engine (ollama) with custom host
    simple = openjarvis_rust.SimpleAgent(
        host=custom_host,
        model="custom-model",
        temperature=0.5,
    )
    assert simple.agent_id() == "simple"

    orch = openjarvis_rust.OrchestratorAgent(
        engine_key="vllm",
        host="http://127.0.0.1:8000",
        model="vllm-model",
        max_turns=5,
    )
    assert orch.agent_id() == "orchestrator"

    react = openjarvis_rust.NativeReActAgent(
        engine_key="sglang",
        host="http://127.0.0.1:30000",
        model="sglang-model",
        max_turns=8,
    )
    assert react.agent_id() == "native_react"

    openhands = openjarvis_rust.NativeOpenHandsAgent(
        engine_key="llamacpp",
        host="http://127.0.0.1:8080",
        model="llama-model",
        max_turns=6,
    )
    assert openhands.agent_id() == "native_openhands"

    monitor = openjarvis_rust.MonitorOperativeAgent(
        engine_key="mlx",
        host="http://127.0.0.1:8080",
        model="mlx-model",
        max_turns=4,
        memory_extraction="scratchpad",
        observation_compression="truncate",
        retrieval_strategy="keyword",
        task_decomposition="monolithic",
    )
    assert monitor.agent_id() == "monitor_operative"


def test_rust_agent_invalid_engine_raises_runtime_error():
    """Verify that unsupported engine_key returns an error rather than crashing."""
    openjarvis_rust = pytest.importorskip("openjarvis_rust")

    with pytest.raises(RuntimeError, match="Unknown engine|not found"):
        openjarvis_rust.SimpleAgent(engine_key="nonexistent_engine")
