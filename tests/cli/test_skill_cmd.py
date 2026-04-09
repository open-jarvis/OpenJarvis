"""Tests for the ``jarvis skill`` CLI commands."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from openjarvis.cli import cli


class TestSkillCmd:
    def test_skill_list_help(self) -> None:
        result = CliRunner().invoke(cli, ["skill", "list", "--help"])
        assert result.exit_code == 0

    def test_skill_install_help(self) -> None:
        result = CliRunner().invoke(cli, ["skill", "install", "--help"])
        assert result.exit_code == 0

    def test_skill_search_help(self) -> None:
        result = CliRunner().invoke(cli, ["skill", "search", "--help"])
        assert result.exit_code == 0

    def test_skill_group_help(self) -> None:
        result = CliRunner().invoke(cli, ["skill", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "install" in result.output
        assert "remove" in result.output
        assert "search" in result.output

    def test_skill_run_help(self) -> None:
        result = CliRunner().invoke(cli, ["skill", "run", "--help"])
        assert result.exit_code == 0

    def test_skill_info_help(self) -> None:
        result = CliRunner().invoke(cli, ["skill", "info", "--help"])
        assert result.exit_code == 0

    def test_skill_update_help(self) -> None:
        result = CliRunner().invoke(cli, ["skill", "update", "--help"])
        assert result.exit_code == 0

    def test_skill_list_shows_discovered_skills(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "skill.toml").write_text(
            textwrap.dedent("""\
            [skill]
            name = "my_skill"
            description = "A test skill"

            [[skill.steps]]
            tool_name = "echo"
            output_key = "x"
        """)
        )
        with patch(
            "openjarvis.cli.skill_cmd._get_skill_paths",
            return_value=[tmp_path],
        ):
            result = CliRunner().invoke(cli, ["skill", "list"])
            assert result.exit_code == 0
            assert "my_skill" in result.output

    def test_skill_info_shows_details(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "info_skill"
        skill_dir.mkdir()
        (skill_dir / "skill.toml").write_text(
            textwrap.dedent("""\
            [skill]
            name = "info_skill"
            description = "Detailed skill"
            author = "test_author"
            tags = ["research", "test"]
            required_capabilities = ["network:fetch"]

            [[skill.steps]]
            tool_name = "echo"
            output_key = "x"
        """)
        )
        with patch(
            "openjarvis.cli.skill_cmd._get_skill_paths",
            return_value=[tmp_path],
        ):
            result = CliRunner().invoke(cli, ["skill", "info", "info_skill"])
            assert result.exit_code == 0
            assert "info_skill" in result.output
            assert "test_author" in result.output


class TestSkillInstallCommand:
    def test_install_help(self) -> None:
        result = CliRunner().invoke(cli, ["skill", "install", "--help"])
        assert result.exit_code == 0
        assert "source" in result.output.lower()

    def test_install_invalid_source_format(self) -> None:
        result = CliRunner().invoke(cli, ["skill", "install", "invalid"])
        assert result.exit_code != 0
        assert "format" in result.output.lower() or "source" in result.output.lower()


class TestSkillSyncCommand:
    def test_sync_help(self) -> None:
        result = CliRunner().invoke(cli, ["skill", "sync", "--help"])
        assert result.exit_code == 0


class TestSkillSourcesCommand:
    def test_sources_help(self) -> None:
        result = CliRunner().invoke(cli, ["skill", "sources", "--help"])
        assert result.exit_code == 0

    def test_sources_lists_configured_sources(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from openjarvis.core.config import (
            JarvisConfig,
            SkillsConfig,
            SkillSourceConfig,
        )

        cfg = JarvisConfig()
        cfg.skills = SkillsConfig(
            sources=[
                SkillSourceConfig(source="hermes"),
                SkillSourceConfig(source="openclaw"),
            ]
        )
        with patch("openjarvis.cli.skill_cmd.load_config", return_value=cfg):
            result = CliRunner().invoke(cli, ["skill", "sources"])
            assert result.exit_code == 0
            assert "hermes" in result.output
            assert "openclaw" in result.output


class TestSkillDiscoverCommand:
    def test_discover_help(self) -> None:
        result = CliRunner().invoke(cli, ["skill", "discover", "--help"])
        assert result.exit_code == 0

    def test_discover_dry_run_no_traces(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        # Patch the trace store to return nothing
        class _EmptyStore:
            def list_traces(self, *, limit: int = 100, **kwargs):
                return []

        with patch(
            "openjarvis.cli.skill_cmd._get_trace_store",
            return_value=_EmptyStore(),
        ):
            result = CliRunner().invoke(cli, ["skill", "discover", "--dry-run"])
            assert result.exit_code == 0

    def test_discover_writes_when_not_dry_run(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from openjarvis.core.types import StepType, Trace, TraceStep

        def _trace():
            return Trace(
                query="q",
                steps=[
                    TraceStep(
                        step_type=StepType.TOOL_CALL,
                        timestamp=0.0,
                        input={"tool": "web_search", "arguments": {}},
                        output={"success": True, "result": "ok"},
                        metadata={},
                    ),
                    TraceStep(
                        step_type=StepType.TOOL_CALL,
                        timestamp=0.0,
                        input={"tool": "calculator", "arguments": {}},
                        output={"success": True, "result": "ok"},
                        metadata={},
                    ),
                ],
                outcome="success",
                feedback=1.0,
            )

        class _Store:
            def list_traces(self, *, limit: int = 100, **kwargs):
                return [_trace() for _ in range(5)]

        output_dir = tmp_path / "discovered"
        with patch(
            "openjarvis.cli.skill_cmd._get_trace_store",
            return_value=_Store(),
        ):
            with patch(
                "openjarvis.cli.skill_cmd._get_discovered_dir",
                return_value=output_dir,
            ):
                result = CliRunner().invoke(
                    cli, ["skill", "discover", "--min-frequency", "3"]
                )
                assert result.exit_code == 0
                assert output_dir.exists()
                # At least one manifest should have been written
                assert any(output_dir.rglob("skill.toml"))


class TestSkillShowOverlayCommand:
    def test_show_overlay_help(self) -> None:
        result = CliRunner().invoke(cli, ["skill", "show-overlay", "--help"])
        assert result.exit_code == 0

    def test_show_overlay_missing(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        with patch(
            "openjarvis.cli.skill_cmd._get_overlay_dir",
            return_value=tmp_path / "no-such",
        ):
            result = CliRunner().invoke(cli, ["skill", "show-overlay", "nonexistent"])
            assert result.exit_code != 0

    def test_show_overlay_displays_optimized(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from openjarvis.skills.overlay import SkillOverlay, write_overlay

        write_overlay(
            SkillOverlay(
                skill_name="research-skill",
                optimizer="dspy",
                optimized_at="2026-04-08T14:30:00Z",
                trace_count=42,
                description="Better description",
                few_shot=[{"input": "q", "output": "a"}],
            ),
            tmp_path,
        )

        with patch(
            "openjarvis.cli.skill_cmd._get_overlay_dir",
            return_value=tmp_path,
        ):
            result = CliRunner().invoke(
                cli, ["skill", "show-overlay", "research-skill"]
            )
            assert result.exit_code == 0
            assert "research-skill" in result.output
            assert "Better description" in result.output
            assert "42" in result.output
            assert "dspy" in result.output
