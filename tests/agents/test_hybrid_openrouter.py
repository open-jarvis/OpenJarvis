"""Fail-closed Ox Alpha coverage for raw hybrid OpenRouter calls."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openjarvis.agents.hybrid import _base
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.cloud import _OX_ALPHA_PROVIDER_POLICY


def _install_openrouter_response(monkeypatch, *, model="stealth/ox-alpha", cost=0):
    captured = {}
    response = SimpleNamespace(
        model=model,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="ok",
                    tool_calls=None,
                    reasoning_content=None,
                    reasoning=None,
                ),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, cost=cost),
    )

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return response

    class _OpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=_Completions())

    limiter = MagicMock()
    monkeypatch.setattr("openai.OpenAI", _OpenAI)
    monkeypatch.setattr(_base, "_openrouter_limiter", lambda: limiter)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    return captured


@pytest.mark.parametrize("model", ["openrouter/stealth/ox-alpha", "stealth/ox-alpha"])
def test_hybrid_ox_enforces_provider_policy_and_zero_cost(monkeypatch, model):
    captured = _install_openrouter_response(monkeypatch)

    result = _base.LocalCloudAgent._call_openrouter(
        model,
        user="hello",
        extra_body={
            "reasoning": {"effort": "medium"},
            "provider": {"allow_fallbacks": True},
        },
    )

    assert result == ("ok", 1, 2)
    assert captured["model"] == "stealth/ox-alpha"
    assert captured["extra_body"] == {
        "reasoning": {"effort": "medium"},
        "provider": _OX_ALPHA_PROVIDER_POLICY,
    }


@pytest.mark.parametrize(
    ("response_model", "cost"),
    [
        ("paid/substitute", 0),
        ("stealth/ox-alpha", 0.01),
        ("stealth/ox-alpha", "0"),
        ("stealth/ox-alpha", None),
    ],
)
def test_hybrid_ox_rejects_unattested_response(monkeypatch, response_model, cost):
    _install_openrouter_response(
        monkeypatch,
        model=response_model,
        cost=cost,
    )

    with pytest.raises(EngineConnectionError):
        _base.LocalCloudAgent._call_openrouter(
            "openrouter/stealth/ox-alpha",
            user="hello",
        )


def test_hybrid_other_openrouter_models_keep_caller_routing(monkeypatch):
    captured = _install_openrouter_response(
        monkeypatch,
        model="openai/gpt-4o",
        cost=None,
    )

    assert _base.LocalCloudAgent._call_openrouter(
        "openrouter/openai/gpt-4o",
        user="hello",
        extra_body={"provider": {"order": ["OpenAI"]}},
    ) == ("ok", 1, 2)
    assert captured["extra_body"] == {"provider": {"order": ["OpenAI"]}}
