"""Tests for setup_security() helper."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

import openjarvis.security.scanner as scanner_module
from openjarvis.core.config import CapabilitiesConfig, JarvisConfig, SecurityConfig
from openjarvis.core.events import EventBus
from openjarvis.security import SecurityContext, setup_security


def _make_mock_engine() -> MagicMock:
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {"content": "ok"}
    engine.list_models.return_value = ["m"]
    engine.health.return_value = True
    return engine


def _make_config(*, enabled: bool = True, caps_enabled: bool = False) -> JarvisConfig:
    cfg = JarvisConfig()
    cfg.security = SecurityConfig(
        enabled=enabled,
        secret_scanner=True,
        pii_scanner=True,
        mode="warn",
        capabilities=CapabilitiesConfig(enabled=caps_enabled),
    )
    return cfg


class TestSetupSecurityEnabled:
    def test_returns_wrapped_engine(self) -> None:
        from openjarvis.security.guardrails import GuardrailsEngine

        engine = _make_mock_engine()
        bus = EventBus()
        sec = setup_security(_make_config(), engine, bus)

        assert isinstance(sec.engine, GuardrailsEngine)
        assert sec.audit_logger is not None
        sec.audit_logger.close()

    def test_returns_security_context(self) -> None:
        engine = _make_mock_engine()
        bus = EventBus()
        sec = setup_security(_make_config(), engine, bus)

        assert isinstance(sec, SecurityContext)
        # Audit logger should always work (no Rust dependency)
        assert sec.audit_logger is not None
        sec.audit_logger.close()

    def test_wraps_and_redacts_without_rust(self, monkeypatch) -> None:
        """Default data-protection controls remain active without Rust."""
        from openjarvis.core.types import Message, Role
        from openjarvis.security.guardrails import GuardrailsEngine

        monkeypatch.setattr(scanner_module._rust_bridge, "RUST_AVAILABLE", False)
        engine = _make_mock_engine()
        bus = EventBus()
        config = _make_config()
        config.security.mode = "redact"

        sec = setup_security(config, engine, bus)

        sec.engine.generate(
            [
                Message(
                    role=Role.USER,
                    content="key sk-abc123def456ghi789jkl012 email user@example.com",
                )
            ],
            model="mock",
        )

        assert isinstance(sec.engine, GuardrailsEngine)
        sent_messages = engine.generate.call_args.args[0]
        assert sent_messages[0].content == (
            "key [REDACTED:openai_key] email [REDACTED:email]"
        )
        sec.audit_logger.close()

    def test_personal_profile_warns_when_scanner_initialization_fails(
        self, monkeypatch, caplog
    ) -> None:
        config = _make_config()
        config.security.profile = "personal"

        def _broken_scanner():
            raise RuntimeError("scanner unavailable")

        monkeypatch.setattr(scanner_module, "SecretScanner", _broken_scanner)

        with caplog.at_level(logging.WARNING, logger="openjarvis.security"):
            sec = setup_security(config, _make_mock_engine(), EventBus())

        assert isinstance(sec, SecurityContext)
        assert "Failed to set up security scanners" in caplog.text
        sec.audit_logger.close()

    @pytest.mark.parametrize("profile", ["shared", "server"])
    def test_server_profiles_fail_closed_when_scanner_initialization_fails(
        self, monkeypatch, profile
    ) -> None:
        config = _make_config()
        config.security.profile = profile

        def _broken_scanner():
            raise RuntimeError("scanner unavailable")

        monkeypatch.setattr(scanner_module, "SecretScanner", _broken_scanner)

        with pytest.raises(RuntimeError, match="Security scanner initialization"):
            setup_security(config, _make_mock_engine(), EventBus())

    @pytest.mark.parametrize("profile", ["", "personal", "shared", "server"])
    def test_enabled_policy_fails_closed_when_initialization_fails(
        self, monkeypatch, profile
    ) -> None:
        cfg = _make_config(caps_enabled=True)
        cfg.security.profile = profile

        def _broken_policy(*args, **kwargs):
            raise RuntimeError("policy unavailable")

        monkeypatch.setattr(
            "openjarvis.security.capabilities.CapabilityPolicy",
            _broken_policy,
        )

        with pytest.raises(RuntimeError, match="Capability policy initialization"):
            setup_security(cfg, _make_mock_engine(), EventBus())

    @pytest.mark.parametrize("profile", ["shared", "server"])
    def test_server_rate_limiter_fails_closed_when_initialization_fails(
        self, monkeypatch, profile
    ) -> None:
        cfg = _make_config(caps_enabled=False)
        cfg.security.profile = profile

        def _broken_limiter(*args, **kwargs):
            raise RuntimeError("limiter unavailable")

        monkeypatch.setattr(
            "openjarvis.security.rate_limiter.RateLimiter",
            _broken_limiter,
        )

        with pytest.raises(RuntimeError, match="Rate limiter initialization"):
            setup_security(cfg, _make_mock_engine(), EventBus())


class TestSetupSecurityDisabled:
    def test_returns_original_engine(self) -> None:
        engine = _make_mock_engine()
        sec = setup_security(_make_config(enabled=False), engine)

        assert sec.engine is engine
        assert sec.capability_policy is None
        assert sec.audit_logger is None


@pytest.mark.parametrize("profile", ["shared", "server"])
@pytest.mark.parametrize(
    ("settings", "enabled", "default_deny"),
    [
        ('policy_path = "policy.json"', True, True),
        ("enabled = false", False, True),
        ("default_deny = false", True, False),
    ],
)
def test_partial_capability_config_preserves_profile_defaults(
    tmp_path,
    profile,
    settings,
    enabled,
    default_deny,
):
    from openjarvis.core.config import load_config

    path = tmp_path / "config.toml"
    path.write_text(
        f'[security]\nprofile = "{profile}"\n[security.capabilities]\n{settings}\n'
    )
    config = load_config(path)
    assert config.security.capabilities.enabled is enabled
    assert config.security.capabilities.default_deny is default_deny


def test_empty_explicit_policy_grants_no_baseline_privileges(tmp_path):
    policy_path = tmp_path / "deny-all.json"
    policy_path.write_text('{"agents": []}')
    config = _make_config(caps_enabled=True)
    config.security.capabilities.default_deny = True
    config.security.capabilities.policy_path = str(policy_path)
    security = setup_security(config, _make_mock_engine(), EventBus())
    try:
        for capability in ("file:read", "network:fetch", "memory:read", "memory:write"):
            assert not security.capability_policy.check("arbitrary-agent", capability)
    finally:
        security.audit_logger.close()
