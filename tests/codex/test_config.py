from __future__ import annotations

from openjarvis.core.config import JarvisConfig


def test_codex_config_defaults_are_safe() -> None:
    config = JarvisConfig().codex

    assert config.enabled is False
    assert config.primary_backend == "python_sdk"
    assert config.approval_mode == "deny_all"
    assert config.analysis_sandbox == "read_only"
    assert config.allow_cli_fallback is False
    assert config.allow_global_cli_override is False
    assert config.max_input_tokens == 200_000
    assert config.max_output_tokens == 32_000
    assert config.max_total_tokens_per_task == 500_000
    assert config.warning_threshold == 0.8
    assert config.hard_limit_action == "interrupt"
    assert not hasattr(config, "api_key")
    assert not hasattr(config, "full_access")
