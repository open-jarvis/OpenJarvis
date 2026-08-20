"""Verify cli._build_backend correctly dispatches hermes/openclaw."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import click
import pytest

from openjarvis.evals.cli import BACKENDS, _build_backend


class TestBuildBackendDispatch:
    def test_backends_dict_includes_external(self) -> None:
        assert "hermes" in BACKENDS
        assert "openclaw" in BACKENDS
        assert "jarvis-agent" in BACKENDS
        assert "jarvis-direct" in BACKENDS

    def test_unknown_backend_raises(self) -> None:
        with pytest.raises(click.UsageError, match="unknown backend"):
            _build_backend(
                backend_name="not-real",
                engine_key=None,
                agent_name="o",
                tools=[],
            )

    def test_hermes_requires_base_url(self) -> None:
        with pytest.raises(click.UsageError, match="--base-url"):
            _build_backend(
                backend_name="hermes",
                engine_key=None,
                agent_name="o",
                tools=[],
                base_url=None,
                api_key="k",
            )

    def test_openclaw_requires_api_key(self) -> None:
        with pytest.raises(click.UsageError, match="--api-key"):
            _build_backend(
                backend_name="openclaw",
                engine_key=None,
                agent_name="o",
                tools=[],
                base_url="http://x",
                api_key=None,
            )

    def test_hermes_returns_hermes_backend(self) -> None:
        from openjarvis.evals.comparison.third_party import (
            ThirdPartyConfig,
            ThirdPartyEntry,
        )

        cfg = ThirdPartyConfig(
            entries={
                "hermes": ThirdPartyEntry(
                    name="hermes",
                    path=Path("/tmp"),
                    pinned_commit="abc",
                    runner_script="x",
                )
            }
        )
        with (
            patch(
                "openjarvis.evals.backends.external.hermes_agent.load_third_party_config",
                return_value=cfg,
            ),
            patch("openjarvis.evals.backends.external.hermes_agent.verify_commit_pin"),
        ):
            from openjarvis.evals.backends.external import HermesBackend

            backend = _build_backend(
                backend_name="hermes",
                engine_key=None,
                agent_name="o",
                tools=[],
                base_url="http://x",
                api_key="k",
            )
            assert isinstance(backend, HermesBackend)
