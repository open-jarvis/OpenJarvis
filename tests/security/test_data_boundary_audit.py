from __future__ import annotations

import os

from openjarvis.core.config import JarvisConfig, load_config
from openjarvis.security.data_boundary_audit import build_data_boundary_report


def _ids(report):
    return {finding.id for finding in report.findings}


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


def test_missing_config_does_not_report_dataclass_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = JarvisConfig()

    report = build_data_boundary_report(config, tmp_path, config_loaded=False)

    assert report.config_loaded is False
    assert "config-file-missing" in _ids(report)
    assert "analytics-enabled" not in _ids(report)
    assert "traces-enabled" not in _ids(report)


def test_config_error_returns_fail_finding_without_crashing(tmp_path):
    config = JarvisConfig()

    report = build_data_boundary_report(
        config,
        tmp_path,
        config_loaded=False,
        config_error="TOMLDecodeError: invalid config",
    )

    findings = {finding.id: finding for finding in report.findings}
    assert report.config_loaded is False
    assert findings["config-load-error"].status == "fail"
    assert "configuration must be fixed" in report.verdict


def test_memory_context_injection_is_info_without_cloud(tmp_path):
    config = _low_noise_config()
    config.agent.context_from_memory = True
    config.intelligence.provider = ""
    config.engine.default = "ollama"

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["memory-context-injection-enabled"].status == "info"
    assert report.verdict == "no fail or warn findings detected"


def test_memory_plus_cloud_provider_is_fail(tmp_path):
    config = _low_noise_config()
    config.agent.context_from_memory = True
    config.intelligence.provider = "openai"

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["memory-context-to-cloud-risk"].status == "fail"
    assert report.verdict == "local memory may be sent to cloud inference"


def test_analytics_is_info_and_does_not_assert_prompt_capture(tmp_path):
    config = _low_noise_config()
    config.analytics.enabled = True

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    finding = findings["analytics-enabled"]
    assert finding.status == "info"
    assert "does not assert" in finding.recommendation


def test_traces_enabled_flags_capture_setting(tmp_path):
    config = _low_noise_config()
    config.traces.enabled = True

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["traces-enabled"].status == "warn"
    assert "traces database" in findings["traces-enabled"].potential_data_path


def test_telemetry_enabled_flags_capture_setting(tmp_path):
    config = _low_noise_config()
    config.telemetry.enabled = True

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["telemetry-enabled"].status == "warn"
    assert "telemetry.enabled = true" in findings["telemetry-enabled"].evidence


def test_trace_database_presence_redacts_and_shows_paths(tmp_path):
    config = _low_noise_config()
    (tmp_path / "traces.db").write_text("", encoding="utf-8")

    report = build_data_boundary_report(config, tmp_path)
    payload = report.to_dict()
    payload_with_paths = report.to_dict(show_paths=True)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["local-store-traces-db"].status == "warn"
    assert payload["schema_version"] == 1
    assert str(tmp_path) not in str(payload)
    assert "traces.db" in str(payload_with_paths)
    assert findings["local-store-traces-db"].absolute_location.endswith("traces.db")


def test_custom_traces_db_path_is_audited(tmp_path):
    config = _low_noise_config()
    custom_db = tmp_path / "custom" / "traces.db"
    custom_db.parent.mkdir()
    custom_db.write_text("", encoding="utf-8")
    config.traces.db_path = str(custom_db)

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["local-store-traces-db"].status == "warn"
    assert str(custom_db) in findings["local-store-traces-db"].absolute_location


def test_connector_json_basename_redacted_by_default(tmp_path):
    config = _low_noise_config()
    connector_dir = tmp_path / "connectors"
    connector_dir.mkdir()
    token_file = connector_dir / "alice-personal-gmail.json"
    token_file.write_text('{"refresh_token":"secret-value"}', encoding="utf-8")

    report = build_data_boundary_report(config, tmp_path)
    redacted = report.to_dict()
    shown = report.to_dict(show_paths=True)

    assert "alice-personal-gmail" not in str(redacted)
    assert "secret-value" not in str(shown)
    assert token_file.name in str(shown)


def test_spec_search_cloud_teacher_is_fail_only_when_enabled(tmp_path):
    config = _low_noise_config()
    config.learning.spec_search.enabled = False
    config.learning.spec_search.teacher_engine = "cloud"

    disabled_report = build_data_boundary_report(config, tmp_path)
    assert "spec-search-cloud-teacher-enabled" not in _ids(disabled_report)

    config.learning.spec_search.enabled = True
    enabled_report = build_data_boundary_report(config, tmp_path)
    findings = {finding.id: finding for finding in enabled_report.findings}
    assert findings["spec-search-cloud-teacher-enabled"].status == "fail"


def test_web_search_tool_and_tavily_env_are_correlated(
    tmp_path,
    monkeypatch,
):
    config = _low_noise_config()
    config.tools.enabled = "web_search"
    monkeypatch.setenv("TAVILY_API_KEY", "secret-value")

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["web-search-tool-configured"].status == "warn"
    assert findings["env-credential-tavily_api_key"].status == "warn"
    assert "secret-value" not in str(report.to_dict(show_paths=True))


def test_mcp_servers_are_flagged_when_non_empty(tmp_path):
    config = _low_noise_config()
    config.tools.mcp.enabled = True
    config.tools.mcp.servers = '[{"name":"external"}]'

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["mcp-servers-configured"].status == "warn"


def test_local_file_shell_and_code_tools_are_info(tmp_path):
    config = _low_noise_config()
    config.tools.enabled = ["file_read", "shell_exec", "code_interpreter"]

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["local-access-tools-configured"].status == "info"


def test_google_env_warns_when_gemini_provider_active(tmp_path, monkeypatch):
    config = _low_noise_config()
    config.intelligence.provider = "gemini"
    monkeypatch.setenv("GOOGLE_API_KEY", "secret-key")

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["env-credential-google_api_key"].status == "warn"


def test_environment_credentials_report_presence_only(tmp_path, monkeypatch):
    config = _low_noise_config()
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    finding = findings["env-credential-openai_api_key"]
    assert finding.status == "info"
    assert "OPENAI_API_KEY is set" in finding.evidence
    assert "secret-key" not in str(report.to_dict(show_paths=True))


def test_server_all_interfaces_is_warn(tmp_path):
    config = _low_noise_config()
    config.server.host = "0.0.0.0"

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["server-binds-all-interfaces"].status == "warn"


def test_a2a_without_auth_token_is_fail(tmp_path):
    config = _low_noise_config()
    config.a2a.enabled = True
    config.a2a.auth_token = ""

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["a2a-enabled-without-auth-token"].status == "fail"


def test_report_json_shape_is_stable(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = _low_noise_config()

    report = build_data_boundary_report(config, tmp_path)
    payload = report.to_dict()

    assert set(payload) == {
        "schema_version",
        "verdict",
        "root",
        "config_loaded",
        "summary",
        "findings",
    }
    assert payload["schema_version"] == 1
    assert set(payload["summary"]) == {"fail", "warn", "info"}
    assert isinstance(payload["findings"], list)


def test_channel_enabled_and_credentials_are_flagged(tmp_path):
    config = _low_noise_config()
    config.channel.enabled = True
    config.channel.telegram.bot_token = "telegram-secret"

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["channels-enabled"].status == "warn"
    channel_finding = findings["channel-secret-channel-telegram-bot-token"]
    assert channel_finding.status == "warn"
    assert "telegram-secret" not in str(report.to_dict(show_paths=True))


def test_channel_reference_fields_are_flagged(tmp_path):
    config = _low_noise_config()
    config.channel.matrix.homeserver = "https://matrix.example.org"

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    ref = findings["channel-reference-channel-matrix-homeserver"]
    assert ref.status == "info"
    assert "Matrix homeserver" in ref.title


def test_channel_env_credential_presence_only(tmp_path, monkeypatch):
    config = _low_noise_config()
    monkeypatch.setenv("SLACK_BOT_TOKEN", "slack-secret")

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    finding = findings["channel-env-secret-slack_bot_token"]
    assert finding.status == "info"
    assert "SLACK_BOT_TOKEN is set" in finding.evidence
    assert "slack-secret" not in str(report.to_dict(show_paths=True))


def test_cloud_speech_backend_is_warn(tmp_path):
    config = _low_noise_config()
    config.speech.backend = "openai"

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["cloud-speech-backend-configured"].status == "warn"


def test_skills_auto_sync_is_warn(tmp_path):
    config = _low_noise_config()
    config.skills.auto_sync = True

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["skills-auto-sync-enabled"].status == "warn"


def test_digest_enabled_is_warn(tmp_path):
    config = _low_noise_config()
    config.digest.enabled = True

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["digest-enabled"].status == "warn"


def test_memory_service_enabled_warns_with_cloud_engine(tmp_path):
    config = _low_noise_config()
    config.tools.storage.enabled = True
    config.intelligence.provider = "openai"

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    finding = findings["memory-service-enabled"]
    assert finding.status == "warn"
    assert "cloud inference surface detected" in finding.evidence


def test_default_model_cloud_detection(tmp_path):
    config = _low_noise_config()
    config.intelligence.default_model = "gpt-4o"

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["cloud-default-model-configured"].status == "warn"


def test_deep_research_cloud_engine_and_model(tmp_path):
    config = _low_noise_config()
    config.deep_research.engine = "openai"
    config.deep_research.model = "gpt-4o-mini"

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["deep-research-cloud-configured"].status == "warn"
    assert "deep_research.engine" in findings["deep-research-cloud-configured"].evidence
    assert "deep_research.model" in findings["deep-research-cloud-configured"].evidence


def test_security_bypass_warns_with_cloud_surface(tmp_path):
    config = _low_noise_config()
    config.intelligence.provider = "openai"
    config.security.local_engine_bypass = True
    config.security.local_tool_bypass = True

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["security-local-engine-bypass-enabled"].status == "warn"
    assert findings["security-local-tool-bypass-enabled"].status == "warn"


def test_security_profile_unset_is_info(tmp_path):
    config = _low_noise_config()
    config.security.profile = ""

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["security-profile-unset"].status == "info"
    assert "security.profile" in findings["security-profile-unset"].recommendation


def test_frontend_scope_note_appears_with_cloud_api_surface(
    tmp_path,
    monkeypatch,
):
    config = _low_noise_config()
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")

    report = build_data_boundary_report(config, tmp_path)

    assert "frontend-credential-storage-not-inspected" in _ids(report)


def test_config_root_error_returns_fail_without_local_store_scan(tmp_path):
    config = _low_noise_config()

    report = build_data_boundary_report(
        config,
        None,
        root_error="ConfigurationError: bad OPENJARVIS_HOME",
    )

    findings = {finding.id: finding for finding in report.findings}
    assert findings["config-root-error"].status == "fail"
    assert report.root == "<unresolved-openjarvis-home>"


def test_group_or_other_readable_local_store_warns(tmp_path):
    if os.name == "nt":
        import pytest

        pytest.skip("Unix permission bits are not checked on Windows")

    config = _low_noise_config()
    trace_db = tmp_path / "traces.db"
    trace_db.write_text("", encoding="utf-8")
    trace_db.chmod(0o644)

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["local-store-permissions-traces-db"].status == "warn"


def test_symlink_local_store_permission_warns(tmp_path):
    if os.name == "nt":
        import pytest

        pytest.skip("Symlink permission semantics differ on Windows")

    config = _low_noise_config()
    real_db = tmp_path / "real-traces.db"
    real_db.write_text("", encoding="utf-8")
    symlink = tmp_path / "traces.db"
    symlink.symlink_to(real_db)
    config.traces.db_path = str(symlink)

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["local-store-permissions-traces-db"].status == "warn"
    assert "symlink" in findings["local-store-permissions-traces-db"].evidence


def test_whatsapp_baileys_local_auth_dir_is_reported(tmp_path):
    config = _low_noise_config()
    auth_dir = tmp_path / "whatsapp_auth"
    auth_dir.mkdir()

    report = build_data_boundary_report(config, tmp_path)

    whatsapp_findings = [
        finding
        for finding in report.findings
        if finding.id.startswith("channel-local-credential-dir-whatsapp-baileys")
    ]
    assert len(whatsapp_findings) == 1
    assert whatsapp_findings[0].status == "info"


def test_whatsapp_dual_auth_dirs_both_reported(tmp_path):
    config = _low_noise_config()
    default_dir = tmp_path / "whatsapp_auth"
    default_dir.mkdir()
    custom_dir = tmp_path / "custom_whatsapp_auth"
    custom_dir.mkdir()
    config.channel.whatsapp_baileys.auth_dir = str(custom_dir)

    report = build_data_boundary_report(config, tmp_path)

    whatsapp_findings = [
        finding
        for finding in report.findings
        if finding.id.startswith("channel-local-credential-dir-whatsapp-baileys")
    ]
    assert len(whatsapp_findings) == 2
    ids = {finding.id for finding in whatsapp_findings}
    assert len(ids) == 2


def test_channel_enabled_without_endpoint_is_info(tmp_path):
    config = _low_noise_config()
    config.channel.enabled = True

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["channels-enabled"].status == "info"


def test_init_template_config_snapshot(tmp_path):
    init_like_toml = """
[server]
host = "0.0.0.0"

[telemetry]
enabled = true

[traces]
enabled = false

[agent]
context_from_memory = true

[memory]
enabled = false
"""
    config_path = tmp_path / "config.toml"
    config_path.write_text(init_like_toml, encoding="utf-8")
    config = load_config(config_path)

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["server-binds-all-interfaces"].status == "warn"
    assert findings["telemetry-enabled"].status == "warn"
    assert "traces-enabled" not in findings
    assert findings["memory-context-injection-enabled"].status == "info"
