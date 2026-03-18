"""Tests for the ``jarvis telemetry`` CLI commands."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.core.types import TelemetryRecord
from openjarvis.telemetry.store import TelemetryStore


def _populate_db(db_path: Path, n: int = 3) -> None:
    """Create a telemetry DB with *n* records."""
    store = TelemetryStore(db_path)
    for i in range(n):
        store.record(
            TelemetryRecord(
                timestamp=time.time() - (n - i),
                model_id=f"model-{i % 2}",
                engine="ollama",
                prompt_tokens=10 * (i + 1),
                completion_tokens=5 * (i + 1),
                total_tokens=15 * (i + 1),
                latency_seconds=0.5 * (i + 1),
                cost_usd=0.001 * (i + 1),
            )
        )
    store.close()


def _patch_config(tmp_path: Path):
    """Patch load_config to use a temp DB."""
    db_path = tmp_path / "telemetry.db"
    cfg = mock.MagicMock()
    cfg.telemetry.db_path = str(db_path)
    return mock.patch(
        "openjarvis.cli.telemetry_cmd.load_config",
        return_value=cfg,
    ), db_path


class TestTelemetrySubcommands:
    def test_subcommands_exist_in_help(self) -> None:
        result = CliRunner().invoke(cli, ["telemetry", "--help"])
        assert result.exit_code == 0
        assert "stats" in result.output
        assert "export" in result.output
        assert "clear" in result.output


class TestTelemetryStats:
    def test_stats_empty_db(self, tmp_path: Path) -> None:
        patch, db_path = _patch_config(tmp_path)
        # Create empty DB
        store = TelemetryStore(db_path)
        store.close()
        with patch:
            result = CliRunner().invoke(cli, ["telemetry", "stats"])
        assert result.exit_code == 0
        assert "No telemetry data" in result.output

    def test_stats_with_data(self, tmp_path: Path) -> None:
        patch, db_path = _patch_config(tmp_path)
        _populate_db(db_path)
        with patch:
            result = CliRunner().invoke(cli, ["telemetry", "stats"])
        assert result.exit_code == 0
        assert "Total Calls" in result.output
        assert "3" in result.output

    def test_top_flag(self, tmp_path: Path) -> None:
        patch, db_path = _patch_config(tmp_path)
        _populate_db(db_path, n=5)
        with patch:
            result = CliRunner().invoke(cli, ["telemetry", "stats", "-n", "1"])
        assert result.exit_code == 0
        assert "Top 1 Models" in result.output


class TestTelemetryExport:
    def test_export_json_empty(self, tmp_path: Path) -> None:
        patch, db_path = _patch_config(tmp_path)
        store = TelemetryStore(db_path)
        store.close()
        with patch:
            result = CliRunner().invoke(cli, ["telemetry", "export"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == []

    def test_export_json_with_data(self, tmp_path: Path) -> None:
        patch, db_path = _patch_config(tmp_path)
        _populate_db(db_path)
        with patch:
            result = CliRunner().invoke(cli, ["telemetry", "export"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 3

    def test_export_csv(self, tmp_path: Path) -> None:
        patch, db_path = _patch_config(tmp_path)
        _populate_db(db_path, n=2)
        with patch:
            result = CliRunner().invoke(cli, ["telemetry", "export", "-f", "csv"])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert len(lines) == 3  # header + 2 rows
        assert "model_id" in lines[0]

    def test_export_to_file(self, tmp_path: Path) -> None:
        patch, db_path = _patch_config(tmp_path)
        _populate_db(db_path)
        out_file = tmp_path / "export.json"
        with patch:
            result = CliRunner().invoke(
                cli,
                ["telemetry", "export", "-o", str(out_file)],
            )
        assert result.exit_code == 0
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert len(data) == 3


class TestTelemetryClear:
    def test_clear_empty(self, tmp_path: Path) -> None:
        patch, db_path = _patch_config(tmp_path)
        store = TelemetryStore(db_path)
        store.close()
        with patch:
            result = CliRunner().invoke(cli, ["telemetry", "clear", "--yes"])
        assert result.exit_code == 0
        assert "Deleted 0" in result.output

    def test_clear_with_yes(self, tmp_path: Path) -> None:
        patch, db_path = _patch_config(tmp_path)
        _populate_db(db_path)
        with patch:
            result = CliRunner().invoke(cli, ["telemetry", "clear", "--yes"])
        assert result.exit_code == 0
        assert "Deleted 3" in result.output

    def test_clear_abort_without_yes(self, tmp_path: Path) -> None:
        patch, db_path = _patch_config(tmp_path)
        _populate_db(db_path)
        with patch:
            result = CliRunner().invoke(cli, ["telemetry", "clear"], input="n\n")
        assert result.exit_code == 0
        assert "Aborted" in result.output
