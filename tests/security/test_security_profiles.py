"""Tests for security profile expansion (Section 7)."""

from __future__ import annotations

import pytest


class TestProfileExpansion:
    """Profiles should pre-fill security and server config fields."""

    def test_personal_profile_sets_redact(self) -> None:
        from openjarvis.core.config import SecurityConfig, apply_security_profile

        cfg = SecurityConfig(profile="personal")
        apply_security_profile(cfg, None)
        assert cfg.mode == "redact"
        assert cfg.rate_limit_enabled is True

    def test_server_profile_sets_block(self) -> None:
        from openjarvis.core.config import (
            SecurityConfig,
            ServerConfig,
            apply_security_profile,
        )

        cfg = SecurityConfig(profile="server")
        server_cfg = ServerConfig()
        apply_security_profile(cfg, server_cfg)
        assert cfg.mode == "block"
        assert cfg.rate_limit_rpm == 30
        assert cfg.rate_limit_burst == 5
        assert server_cfg.host == "0.0.0.0"

    def test_explicit_override_beats_profile(self) -> None:
        from openjarvis.core.config import SecurityConfig, apply_security_profile

        cfg = SecurityConfig(profile="server", mode="warn")
        apply_security_profile(cfg, None, overrides={"mode"})
        assert cfg.mode == "warn"

    def test_empty_profile_is_noop(self) -> None:
        from openjarvis.core.config import SecurityConfig, apply_security_profile

        cfg = SecurityConfig()
        original_mode = cfg.mode
        apply_security_profile(cfg, None)
        assert cfg.mode == original_mode

    def test_unknown_profile_raises(self) -> None:
        from openjarvis.core.config import SecurityConfig, apply_security_profile

        cfg = SecurityConfig(profile="nonexistent")
        with pytest.raises(ValueError, match="Unknown security profile"):
            apply_security_profile(cfg, None)
