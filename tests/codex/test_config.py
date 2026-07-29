from __future__ import annotations

from openjarvis.core.config import JarvisConfig


def test_codex_config_defaults_are_safe() -> None:
    config = JarvisConfig().codex

    assert config.enabled is False
    assert config.primary_backend == "python_sdk"
    assert config.approval_mode == "deny_all"
    assert config.analysis_sandbox == "read_only"
    assert config.allow_global_cli_override is False
    assert not hasattr(config, "api_key")
    assert not hasattr(config, "full_access")
