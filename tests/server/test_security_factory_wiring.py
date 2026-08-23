"""Adversarial security wiring tests for the programmatic app factory."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from openjarvis.core.config import JarvisConfig
from openjarvis.security import SecurityContext
from openjarvis.server.app import create_app


def _config() -> JarvisConfig:
    config = JarvisConfig()
    config.analytics.enabled = False
    config.traces.enabled = False
    config.security.enabled = True
    return config


def test_factory_derives_missing_security_and_secures_prebuilt_agent(
    monkeypatch,
) -> None:
    engine = MagicMock(name="raw-engine")
    wrapped = MagicMock(name="wrapped-engine")
    policy = object()
    limiter = object()
    audit = object()
    setup = MagicMock(
        return_value=SecurityContext(
            engine=wrapped,
            capability_policy=policy,
            rate_limiter=limiter,
            audit_logger=audit,
        )
    )
    monkeypatch.setattr("openjarvis.security.setup_security", setup)
    agent = SimpleNamespace(
        agent_id="tool-agent",
        _engine=engine,
        _executor=SimpleNamespace(
            _capability_policy=None,
            _rate_limiter=None,
            _agent_id="",
        ),
    )

    app = create_app(engine, "model", agent=agent, config=_config())

    setup.assert_called_once()
    assert app.state.engine is wrapped
    assert app.state.bus is not None
    assert app.state.capability_policy is policy
    assert app.state.rate_limiter is limiter
    assert app.state.audit_logger is audit
    assert agent._engine is wrapped
    assert agent._bus is app.state.bus
    assert agent._executor._bus is app.state.bus
    assert agent._executor._capability_policy is policy
    assert agent._executor._rate_limiter is limiter
    assert agent._executor._agent_id == "tool-agent"


def test_factory_preserves_explicit_security_primitives(monkeypatch) -> None:
    derived_policy = object()
    derived_limiter = object()
    derived_audit = object()
    explicit_policy = object()
    explicit_limiter = object()
    setup = MagicMock(
        return_value=SecurityContext(
            engine="wrapped",
            capability_policy=derived_policy,
            rate_limiter=derived_limiter,
            audit_logger=derived_audit,
        )
    )
    monkeypatch.setattr("openjarvis.security.setup_security", setup)

    app = create_app(
        "raw",
        "model",
        config=_config(),
        capability_policy=explicit_policy,
        rate_limiter=explicit_limiter,
    )

    assert app.state.engine == "wrapped"
    assert app.state.capability_policy is explicit_policy
    assert app.state.rate_limiter is explicit_limiter
    assert app.state.audit_logger is derived_audit


def test_factory_propagates_strict_security_setup_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "openjarvis.security.setup_security",
        MagicMock(side_effect=RuntimeError("policy failed")),
    )

    with pytest.raises(RuntimeError, match="policy failed"):
        create_app("raw", "model", config=_config())
