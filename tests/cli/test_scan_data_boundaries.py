from __future__ import annotations

import json

from click.testing import CliRunner

from openjarvis.cli.scan_cmd import PrivacyScanner, ScanResult, scan
from openjarvis.core.config import JarvisConfig


def _low_noise_config():
    """Baseline config with no warn/fail findings under an empty scan root.

    JarvisConfig defaults include absolute store paths under the real
    OPENJARVIS_HOME; clear those so tests only see artifacts under tmp_path.
    """
    config = JarvisConfig()
    config.analytics.enabled = False
    config.traces.enabled = False
    config.telemetry.enabled = False
    config.agent.context_from_memory = False
    config.agent.tools = ""
    config.skills.enabled = False
    config.digest.enabled = False
    config.channel.enabled = False
    config.learning.enabled = False
    config.learning.training_enabled = False
    config.learning.auto_update = False
    config.learning.spec_search.enabled = False
    config.tools.enabled = ""
    config.tools.mcp.enabled = False
    config.tools.storage.enabled = False
    config.optimize.optimizer_provider = ""
    config.optimize.judge_model = ""
    config.server.host = "127.0.0.1"
    config.security.profile = "personal"
    # Avoid scanning the developer's real ~/.openjarvis store files.
    config.traces.db_path = ""
    config.telemetry.db_path = ""
    config.security.audit_log_path = ""
    config.security.vault_key_path = ""
    config.tools.storage.db_path = ""
    config.tools.storage.facts_path = ""
    config.sessions.db_path = ""
    config.agent_manager.db_path = ""
    config.optimize.db_path = ""
    config.scheduler.db_path = ""
    config.skills.index_dir = ""
    config.memory_files.soul_path = ""
    config.memory_files.memory_path = ""
    config.memory_files.user_path = ""
    return config


def _patch_config(monkeypatch, tmp_path, config, config_loaded=True, error=""):
    monkeypatch.setattr(
        "openjarvis.cli.scan_cmd._load_data_boundary_config",
        lambda: (config, tmp_path, config_loaded, error, ""),
    )
    monkeypatch.setattr("openjarvis.cli.scan_cmd.get_config_dir", lambda: tmp_path)


def test_scan_data_boundaries_json_redacts_paths(monkeypatch, tmp_path):
    config = _low_noise_config()
    (tmp_path / "traces.db").write_text("", encoding="utf-8")
    _patch_config(monkeypatch, tmp_path, config)

    result = CliRunner().invoke(scan, ["--data-boundaries", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["root"] != str(tmp_path.resolve())
    assert str(tmp_path.resolve()) not in result.output
    assert "findings" in payload


def test_scan_data_boundaries_show_paths_json(monkeypatch, tmp_path):
    config = _low_noise_config()
    trace_db = tmp_path / "traces.db"
    trace_db.write_text("", encoding="utf-8")
    _patch_config(monkeypatch, tmp_path, config)

    result = CliRunner().invoke(
        scan,
        ["--data-boundaries", "--json", "--show-paths"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["root"] == str(tmp_path.resolve())
    assert "traces.db" in result.output


def test_scan_data_boundaries_handles_config_load_error(monkeypatch, tmp_path):
    config = _low_noise_config()
    _patch_config(
        monkeypatch,
        tmp_path,
        config,
        config_loaded=False,
        error="TOMLDecodeError: invalid config",
    )

    result = CliRunner().invoke(scan, ["--data-boundaries", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["summary"]["fail"] == 1
    assert payload["findings"][0]["id"] == "config-load-error"


def test_scan_data_boundaries_strict_exits_nonzero_on_fail(
    monkeypatch,
    tmp_path,
):
    config = _low_noise_config()
    config.intelligence.provider = "openai"
    config.agent.context_from_memory = True
    _patch_config(monkeypatch, tmp_path, config)

    result = CliRunner().invoke(scan, ["--data-boundaries", "--strict"])

    assert result.exit_code == 1
    assert "local memory may be sent to cloud inference" in result.output


def test_scan_data_boundaries_fail_exits_zero_without_strict(
    monkeypatch,
    tmp_path,
):
    config = _low_noise_config()
    config.intelligence.provider = "openai"
    config.agent.context_from_memory = True
    _patch_config(monkeypatch, tmp_path, config)

    result = CliRunner().invoke(scan, ["--data-boundaries"])

    assert result.exit_code == 0
    assert "local memory may be sent to cloud inference" in result.output


def test_scan_data_boundaries_strict_exits_on_warning(
    monkeypatch,
    tmp_path,
):
    config = _low_noise_config()
    config.tools.enabled = "web_search"
    _patch_config(monkeypatch, tmp_path, config)

    result = CliRunner().invoke(scan, ["--data-boundaries", "--strict"])

    assert result.exit_code == 1
    assert "Web search tool is configured" in result.output


def test_scan_data_boundaries_strict_passes_with_info_only(
    monkeypatch,
    tmp_path,
):
    config = _low_noise_config()
    config.agent.context_from_memory = True
    _patch_config(monkeypatch, tmp_path, config)

    result = CliRunner().invoke(scan, ["--data-boundaries", "--strict"])

    assert result.exit_code == 0
    assert "OpenJarvis Data-Boundary Scan" in result.output


def test_scan_data_boundaries_init_defaults_strict_exits_on_warn(
    monkeypatch,
    tmp_path,
):
    config = _low_noise_config()
    config.server.host = "0.0.0.0"
    config.telemetry.enabled = True
    _patch_config(monkeypatch, tmp_path, config)

    result = CliRunner().invoke(scan, ["--data-boundaries", "--strict"])

    assert result.exit_code == 1
    assert "bind all" in result.output


def test_scan_data_boundaries_rejects_quick(monkeypatch, tmp_path):
    config = _low_noise_config()
    _patch_config(monkeypatch, tmp_path, config)

    result = CliRunner().invoke(scan, ["--quick", "--data-boundaries"])

    assert result.exit_code != 0
    assert "cannot be combined" in result.output


def test_scan_rejects_strict_without_data_boundaries():
    result = CliRunner().invoke(scan, ["--strict"])

    assert result.exit_code != 0
    assert "only supported with --data-boundaries" in result.output


def test_existing_scan_json_still_works(monkeypatch):
    monkeypatch.setattr(
        PrivacyScanner,
        "run_all",
        lambda self: [
            ScanResult(
                name="Network Exposure",
                status="ok",
                message="No exposed ports.",
                platform="all",
            )
        ],
    )

    result = CliRunner().invoke(scan, ["--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["name"] == "Network Exposure"
    assert payload[0]["status"] == "ok"


def test_existing_scan_quick_json_still_works(monkeypatch):
    monkeypatch.setattr(
        PrivacyScanner,
        "run_quick",
        lambda self: [
            ScanResult(
                name="Cloud Sync Agents",
                status="ok",
                message="No cloud-sync agents detected.",
                platform="all",
            )
        ],
    )

    result = CliRunner().invoke(scan, ["--quick", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["name"] == "Cloud Sync Agents"


def test_top_level_cli_registers_data_boundary_scan(monkeypatch, tmp_path):
    from openjarvis.cli import cli

    config = _low_noise_config()
    _patch_config(monkeypatch, tmp_path, config)

    result = CliRunner().invoke(cli, ["scan", "--data-boundaries", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert "summary" in payload


def test_top_level_scan_data_boundaries_does_not_check_for_updates(
    monkeypatch,
    tmp_path,
):
    import sys

    from openjarvis.cli import cli
    from openjarvis.core.config import JarvisConfig

    called = {"value": False}

    def fake_check_for_updates(_subcommand):
        called["value"] = True

    monkeypatch.setattr(
        "openjarvis.cli._version_check.check_for_updates",
        fake_check_for_updates,
    )
    monkeypatch.setattr(
        "openjarvis.cli.scan_cmd._load_data_boundary_config",
        lambda: (JarvisConfig(), tmp_path, False, "", ""),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["jarvis", "scan", "--data-boundaries", "--json"],
    )

    result = CliRunner().invoke(cli, ["scan", "--data-boundaries", "--json"])

    assert result.exit_code == 0
    assert called["value"] is False


def test_update_check_skip_helper_is_precise():
    from click import Command, Context

    from openjarvis.cli import _should_skip_update_check

    ctx = Context(Command("jarvis"))
    ctx.invoked_subcommand = "scan"
    assert _should_skip_update_check(ctx, ["scan", "--data-boundaries"])

    ctx.invoked_subcommand = "ask"
    assert not _should_skip_update_check(ctx, ["ask", "scan", "--data-boundaries"])


def test_existing_scan_quick_text_still_works(monkeypatch):
    monkeypatch.setattr(
        PrivacyScanner,
        "run_quick",
        lambda self: [
            ScanResult(
                name="Cloud Sync Agents",
                status="ok",
                message="No cloud-sync agents detected.",
                platform="all",
            )
        ],
    )

    result = CliRunner().invoke(scan, ["--quick"])

    assert result.exit_code == 0
    assert "OpenJarvis Security Scan" in result.output


def test_data_boundary_loader_honors_openjarvis_config(
    monkeypatch,
    tmp_path,
):
    from openjarvis.cli import scan_cmd
    from openjarvis.core.config import load_config

    config_path = tmp_path / "custom.toml"
    config_path.write_text(
        "[telemetry]\nenabled = false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENJARVIS_CONFIG", str(config_path))
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "home"))
    load_config.cache_clear()

    _config, _root, loaded, error, root_error = (
        scan_cmd._load_data_boundary_config()
    )

    assert loaded is True
    assert error == ""
    assert root_error == ""


def test_data_boundary_loader_reports_root_error(monkeypatch):
    from openjarvis.cli import scan_cmd

    monkeypatch.setattr(
        "openjarvis.cli.scan_cmd.get_config_dir",
        lambda: (_ for _ in ()).throw(RuntimeError("bad home")),
    )

    _config, root, loaded, error, root_error = (
        scan_cmd._load_data_boundary_config()
    )

    assert root is None
    assert loaded is False
    assert error == ""
    assert "bad home" in root_error
