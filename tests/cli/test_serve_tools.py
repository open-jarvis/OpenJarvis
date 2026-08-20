"""Regression tests for tool selection during ``jarvis serve`` startup."""

from __future__ import annotations

import pytest

from openjarvis.cli.serve import _resolve_allowed_tools
from openjarvis.core.config import JarvisConfig


@pytest.mark.parametrize(
    "configured",
    [
        "code_interpreter,file_read",
        ["code_interpreter", "file_read"],
    ],
)
def test_tools_enabled_is_used_by_serve(configured):
    config = JarvisConfig()
    config.tools.enabled = configured

    allowed, explicit = _resolve_allowed_tools(config)

    assert allowed == {"code_interpreter", "file_read"}
    assert explicit is True


def test_tools_enabled_takes_precedence_over_legacy_agent_tools():
    config = JarvisConfig()
    config.tools.enabled = "file_read"
    config.agent.tools = "calculator"

    allowed, explicit = _resolve_allowed_tools(config)

    assert allowed == {"file_read"}
    assert explicit is True


def test_agent_tools_remains_a_backward_compatible_fallback():
    config = JarvisConfig()
    config.agent.tools = "file_read"

    allowed, explicit = _resolve_allowed_tools(config)

    assert allowed == {"file_read"}
    assert explicit is True


def test_serve_defaults_tools_when_no_selection_is_configured():
    allowed, explicit = _resolve_allowed_tools(JarvisConfig())

    assert allowed == {"think", "calculator", "web_search"}
    assert explicit is False
