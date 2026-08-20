from __future__ import annotations

import os

import pytest

from openjarvis.core.config import JarvisConfig, load_config
from openjarvis.security.data_boundary_audit import (
    API_KEY_ENV_VARS,
    BROWSER_TOOLS,
    CHANNEL_OUTBOUND_TOOLS,
    CHANNEL_REFERENCE_ENV_VARS,
    CHANNEL_SECRET_ENV_VARS,
    CLOUD_MEDIA_TOOLS,
    EXTERNAL_TOOL_SURFACES,
    GENERIC_CREDENTIAL_ENV_VARS,
    GENERIC_NETWORK_TOOLS,
    KNOWLEDGE_ENGINE_TOOLS,
    LOCAL_ACCESS_TOOLS,
    OUTBOUND_TOOL_SURFACES,
    RUNTIME_CREDENTIAL_ENV_KEYS,
    WEB_SEARCH_TOOLS,
    build_data_boundary_report,
)
from tests.tools.test_tool_registration import EXPECTED_TOOLS as EXPECTED_BUILTIN_TOOLS

EXPECTED_BROWSER_TOOLS = {
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_screenshot",
    "browser_extract",
}

EXPECTED_GENERIC_NETWORK_TOOLS = {"http_request"}
EXPECTED_CHANNEL_OUTBOUND_TOOLS = {"channel_send"}
EXPECTED_CLOUD_MEDIA_TOOLS = {
    "audio_transcribe",
    "image_generate",
    "text_to_speech",
}
EXPECTED_KNOWLEDGE_ENGINE_TOOLS = {"scan_chunks"}

EXPECTED_LOCAL_ACCESS_TOOLS = {
    "file_write",
    "apply_patch",
    "calendar_search",
    "calendar_upcoming",
    "docker_shell_exec",
    "db_query",
    "knowledge_sql",
    "memory_manage",
    "repl",
    "code_interpreter_docker",
    "git_status",
    "git_diff",
    "git_commit",
    "git_log",
    "retrieval",
    "memory_store",
    "memory_retrieve",
    "memory_search",
    "memory_index",
    "user_profile_manage",
    "skill_manage",
    "channel_list",
    "channel_status",
    "pdf_extract",
    "kg_add_entity",
    "kg_add_relation",
    "kg_query",
    "kg_neighbors",
}

# Built-in tools with no independent data-boundary surface beyond existing
# provider/engine/channel configuration findings.
EXPLICITLY_EXEMPT_TOOLS = {
    # Pure local arithmetic; no file, network, or credential egress.
    "calculator",
    # Local scratchpad/reasoning only; content stays in-process.
    "think",
    # Routes through the configured intelligence stack already audited via
    # provider/engine/model findings; classifying here would double-count.
    "llm",
}

CLASSIFIED_TOOLS = (
    WEB_SEARCH_TOOLS
    | BROWSER_TOOLS
    | GENERIC_NETWORK_TOOLS
    | CHANNEL_OUTBOUND_TOOLS
    | CLOUD_MEDIA_TOOLS
    | KNOWLEDGE_ENGINE_TOOLS
    | LOCAL_ACCESS_TOOLS
)


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
    config.agent.default_agent = "simple"
    config.skills.enabled = False
    config.digest.enabled = False
    config.channel.enabled = False
    config.learning.enabled = False
    config.learning.training_enabled = False
    config.learning.auto_update = False
    config.learning.spec_search.enabled = False
    config.learning.spec_search.teacher_engine = ""
    config.tools.enabled = ""
    config.tools.mcp.enabled = False
    config.tools.storage.enabled = False
    config.optimize.optimizer_provider = ""
    config.optimize.judge_model = ""
    config.server.host = "127.0.0.1"
    config.server.model = ""
    config.security.profile = "personal"
    config.intelligence.provider = ""
    config.intelligence.preferred_engine = ""
    config.intelligence.default_model = ""
    config.engine.default = "ollama"
    config.deep_research.engine = ""
    config.deep_research.model = ""
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


@pytest.mark.parametrize(
    "model",
    ["deepseek-r1:7b", "google/gemma-3-4b-it", "openai/gpt-oss-20b"],
)
def test_local_engine_vendor_model_names_are_not_cloud(tmp_path, model):
    config = _low_noise_config()
    config.engine.default = "ollama"
    config.intelligence.default_model = model
    config.agent.context_from_memory = True

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert "cloud-default-model-configured" not in findings
    assert "memory-context-to-cloud-risk" not in findings
    assert "frontend-credential-storage-not-inspected" not in findings
    assert findings["memory-context-injection-enabled"].status == "info"


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


@pytest.mark.parametrize("host", ["192.168.1.50", "203.0.113.5"])
def test_server_non_loopback_interface_is_warn(tmp_path, host):
    config = _low_noise_config()
    config.server.host = host

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    finding = findings["server-binds-non-loopback-interface"]
    assert finding.status == "warn"
    assert host in finding.evidence


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


def test_cartesia_digest_tts_and_credential_are_reported_without_leak(
    tmp_path,
    monkeypatch,
):
    config = _low_noise_config()
    config.digest.enabled = True
    config.digest.tts_backend = "cartesia"
    monkeypatch.setenv("CARTESIA_API_KEY", "secret-cartesia-key")

    report = build_data_boundary_report(config, tmp_path)
    payload = report.to_dict(show_paths=True)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["cloud-tts-backend-configured"].status == "warn"
    credential = findings["env-credential-cartesia_api_key"]
    assert credential.status == "warn"
    assert "CARTESIA_API_KEY is set" in credential.evidence
    assert "secret-cartesia-key" not in str(payload)
    assert report.verdict == "cloud-capable data boundaries configured"


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
    config.engine.default = "openai"
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
        root_error=(
            "ConfigurationError: bad OPENJARVIS_HOME at /Users/alice/private/openjarvis"
        ),
    )

    findings = {finding.id: finding for finding in report.findings}
    assert findings["config-root-error"].status == "fail"
    assert "bad OPENJARVIS_HOME" not in findings["config-root-error"].evidence
    assert "/Users/alice/private/openjarvis" not in str(report.to_dict())
    assert "path details were redacted" in findings["config-root-error"].evidence
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
    auth_dir = tmp_path / "whatsapp_baileys_bridge" / "auth"
    auth_dir.mkdir(parents=True)

    report = build_data_boundary_report(config, tmp_path)

    whatsapp_findings = [
        finding
        for finding in report.findings
        if finding.id.startswith("channel-local-credential-dir-whatsapp-baileys")
    ]
    assert len(whatsapp_findings) == 1
    assert whatsapp_findings[0].status == "info"
    assert whatsapp_findings[0].location == "whatsapp_baileys_bridge/auth"


def test_whatsapp_dual_auth_dirs_both_reported(tmp_path):
    config = _low_noise_config()
    default_dir = tmp_path / "whatsapp_baileys_bridge" / "auth"
    default_dir.mkdir(parents=True)
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
    locations = {finding.location for finding in whatsapp_findings}
    assert "whatsapp_baileys_bridge/auth" in locations
    assert "<redacted>" in locations


def test_channel_enabled_without_endpoint_is_info(tmp_path):
    config = _low_noise_config()
    config.channel.enabled = True

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["channels-enabled"].status == "info"


def test_default_channel_value_is_always_redacted(tmp_path):
    config = _low_noise_config()
    config.channel.enabled = True
    config.channel.default_channel = "telegram-secret-channel"

    report = build_data_boundary_report(config, tmp_path)
    payload = report.to_dict(show_paths=True)

    findings = {finding.id: finding for finding in report.findings}
    finding = findings["channels-enabled"]
    assert finding.status == "warn"
    assert "channel.default_channel is set; value redacted" in finding.evidence
    assert "telegram-secret-channel" not in finding.evidence
    assert "telegram-secret-channel" not in str(payload)


def test_required_registered_tool_names_are_classified():
    assert EXPECTED_BROWSER_TOOLS <= BROWSER_TOOLS
    assert EXPECTED_LOCAL_ACCESS_TOOLS <= LOCAL_ACCESS_TOOLS
    assert EXPECTED_GENERIC_NETWORK_TOOLS <= GENERIC_NETWORK_TOOLS
    assert EXPECTED_CHANNEL_OUTBOUND_TOOLS <= CHANNEL_OUTBOUND_TOOLS
    assert EXPECTED_CLOUD_MEDIA_TOOLS <= CLOUD_MEDIA_TOOLS
    assert EXPECTED_KNOWLEDGE_ENGINE_TOOLS <= KNOWLEDGE_ENGINE_TOOLS
    assert (
        EXPECTED_GENERIC_NETWORK_TOOLS
        | EXPECTED_CHANNEL_OUTBOUND_TOOLS
        | EXPECTED_CLOUD_MEDIA_TOOLS
        | EXPECTED_BROWSER_TOOLS
        | EXPECTED_KNOWLEDGE_ENGINE_TOOLS
    ) <= OUTBOUND_TOOL_SURFACES
    assert EXPECTED_KNOWLEDGE_ENGINE_TOOLS <= EXTERNAL_TOOL_SURFACES


def test_builtin_registry_tools_are_classified_or_explicitly_exempt():
    unclassified = EXPECTED_BUILTIN_TOOLS - CLASSIFIED_TOOLS - EXPLICITLY_EXEMPT_TOOLS
    assert not unclassified, (
        "Registered built-in tools lack a data-boundary classification or "
        f"documented exemption: {sorted(unclassified)}"
    )
    assert EXPECTED_BUILTIN_TOOLS <= CLASSIFIED_TOOLS | EXPLICITLY_EXEMPT_TOOLS
    # Exemptions must not silently absorb tools that are already classified.
    assert not (EXPLICITLY_EXEMPT_TOOLS & CLASSIFIED_TOOLS)


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_BROWSER_TOOLS))
def test_required_browser_tools_are_detected(tmp_path, tool_name):
    config = _low_noise_config()
    config.tools.enabled = tool_name

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["browser-tool-configured"].status == "warn"
    assert tool_name in findings["browser-tool-configured"].evidence


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_LOCAL_ACCESS_TOOLS))
def test_required_local_access_tools_are_detected(tmp_path, tool_name):
    config = _low_noise_config()
    config.tools.enabled = tool_name

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["local-access-tools-configured"].status == "info"
    assert tool_name in findings["local-access-tools-configured"].evidence


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_GENERIC_NETWORK_TOOLS))
def test_http_request_produces_outbound_warn(tmp_path, tool_name):
    config = _low_noise_config()
    config.tools.enabled = tool_name

    report = build_data_boundary_report(config, tmp_path)
    payload = report.to_dict(show_paths=True)

    findings = {finding.id: finding for finding in report.findings}
    finding = findings["generic-network-tool-configured"]
    assert finding.status == "warn"
    assert tool_name in finding.evidence
    assert "HTTP arguments, headers, and body" in finding.potential_data_path
    assert "external URL" in finding.potential_data_path
    assert "Authorization" not in str(payload)
    assert "https://" not in str(payload)


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_CHANNEL_OUTBOUND_TOOLS))
def test_channel_send_produces_outbound_warn(tmp_path, tool_name):
    config = _low_noise_config()
    config.tools.enabled = tool_name

    report = build_data_boundary_report(config, tmp_path)
    payload = report.to_dict(show_paths=True)

    findings = {finding.id: finding for finding in report.findings}
    finding = findings["channel-outbound-tool-configured"]
    assert finding.status == "warn"
    assert tool_name in finding.evidence
    assert "message content" in finding.potential_data_path
    assert "external messaging channel" in finding.potential_data_path
    assert "secret-message" not in str(payload)
    assert "telegram-secret-channel" not in str(payload)


def test_image_generate_produces_outbound_warn(tmp_path):
    config = _low_noise_config()
    config.tools.enabled = "image_generate"

    report = build_data_boundary_report(config, tmp_path)
    payload = report.to_dict(show_paths=True)

    findings = {finding.id: finding for finding in report.findings}
    finding = findings["cloud-media-tool-configured"]
    assert finding.status == "warn"
    assert "image_generate" in finding.evidence
    assert "image prompt" in finding.potential_data_path
    assert "external media provider" in finding.potential_data_path
    assert "a secret prompt about Alice" not in str(payload)


def test_audio_transcribe_produces_outbound_warn_for_local_audio(tmp_path):
    config = _low_noise_config()
    config.tools.enabled = "audio_transcribe"

    report = build_data_boundary_report(config, tmp_path)
    payload = report.to_dict(show_paths=True)

    findings = {finding.id: finding for finding in report.findings}
    finding = findings["cloud-media-tool-configured"]
    assert finding.status == "warn"
    assert "audio_transcribe" in finding.evidence
    assert "local audio file" in finding.potential_data_path
    assert "external media provider" in finding.potential_data_path
    assert "private-meeting.wav" not in str(payload)


def test_http_request_with_local_tool_bypass_warns(tmp_path):
    config = _low_noise_config()
    config.tools.enabled = "http_request"
    config.security.local_tool_bypass = True

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["generic-network-tool-configured"].status == "warn"
    assert findings["security-local-tool-bypass-enabled"].status == "warn"


@pytest.mark.parametrize(
    "tool_name",
    sorted(
        EXPECTED_GENERIC_NETWORK_TOOLS
        | EXPECTED_CHANNEL_OUTBOUND_TOOLS
        | EXPECTED_CLOUD_MEDIA_TOOLS
        | EXPECTED_BROWSER_TOOLS
    ),
)
def test_outbound_tools_with_bypass_are_external_surfaces(tmp_path, tool_name):
    config = _low_noise_config()
    config.tools.enabled = tool_name
    config.security.local_tool_bypass = True

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["security-local-tool-bypass-enabled"].status == "warn"


@pytest.mark.parametrize(
    "tool_name",
    sorted(EXPECTED_CLOUD_MEDIA_TOOLS | {"web_search"}),
)
def test_cloud_api_outbound_tools_emit_frontend_scope_note(tmp_path, tool_name):
    config = _low_noise_config()
    config.tools.enabled = tool_name

    report = build_data_boundary_report(config, tmp_path)

    assert "frontend-credential-storage-not-inspected" in _ids(report)


@pytest.mark.parametrize(
    "tool_name",
    [
        "code_interpreter_docker",
        "git_status",
        "git_diff",
        "git_commit",
        "git_log",
    ],
)
def test_docker_and_git_tools_are_local_access_info(tmp_path, tool_name):
    config = _low_noise_config()
    config.tools.enabled = tool_name

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["local-access-tools-configured"].status == "info"
    assert tool_name in findings["local-access-tools-configured"].evidence


@pytest.mark.parametrize("tool_name", sorted(BROWSER_TOOLS))
def test_registered_browser_tools_are_detected(tmp_path, tool_name):
    config = _low_noise_config()
    config.tools.enabled = tool_name

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["browser-tool-configured"].status == "warn"
    assert tool_name in findings["browser-tool-configured"].evidence


@pytest.mark.parametrize("tool_name", sorted(LOCAL_ACCESS_TOOLS))
def test_registered_local_sensitive_tools_are_detected(tmp_path, tool_name):
    config = _low_noise_config()
    config.tools.enabled = tool_name

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["local-access-tools-configured"].status == "info"
    assert tool_name in findings["local-access-tools-configured"].evidence


@pytest.mark.parametrize("tool_name", sorted(GENERIC_NETWORK_TOOLS))
def test_registered_generic_network_tools_are_detected(tmp_path, tool_name):
    config = _low_noise_config()
    config.tools.enabled = tool_name

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["generic-network-tool-configured"].status == "warn"
    assert tool_name in findings["generic-network-tool-configured"].evidence


@pytest.mark.parametrize("tool_name", sorted(CHANNEL_OUTBOUND_TOOLS))
def test_registered_channel_outbound_tools_are_detected(tmp_path, tool_name):
    config = _low_noise_config()
    config.tools.enabled = tool_name

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["channel-outbound-tool-configured"].status == "warn"
    assert tool_name in findings["channel-outbound-tool-configured"].evidence


@pytest.mark.parametrize("tool_name", sorted(CLOUD_MEDIA_TOOLS))
def test_registered_cloud_media_tools_are_detected(tmp_path, tool_name):
    config = _low_noise_config()
    config.tools.enabled = tool_name

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["cloud-media-tool-configured"].status == "warn"
    assert tool_name in findings["cloud-media-tool-configured"].evidence


def test_gemini_api_key_is_detected_without_value_leak(tmp_path, monkeypatch):
    config = _low_noise_config()
    config.intelligence.provider = "gemini"
    monkeypatch.setenv("GEMINI_API_KEY", "secret-gemini-key")

    report = build_data_boundary_report(config, tmp_path)
    payload = report.to_dict(show_paths=True)

    findings = {finding.id: finding for finding in report.findings}
    finding = findings["env-credential-gemini_api_key"]
    assert finding.status == "warn"
    assert "GEMINI_API_KEY is set" in finding.evidence
    assert "secret-gemini-key" not in str(payload)


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


def test_scan_chunks_is_classified():
    assert "scan_chunks" in KNOWLEDGE_ENGINE_TOOLS
    assert "scan_chunks" in CLASSIFIED_TOOLS
    assert "scan_chunks" in EXPECTED_BUILTIN_TOOLS


def test_scan_chunks_local_engine_is_warn_or_info(tmp_path):
    config = _low_noise_config()
    config.tools.enabled = "scan_chunks"
    config.engine.default = "ollama"
    config.deep_research.engine = ""
    config.deep_research.model = ""

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert "knowledge-chunks-to-cloud-risk" not in findings
    finding = findings["knowledge-engine-tool-configured"]
    assert finding.status in {"warn", "info"}
    assert "local knowledge-store chunks" in finding.potential_data_path


def test_knowledge_chunks_cloud_composition_is_fail(tmp_path):
    config = _low_noise_config()
    config.tools.enabled = "scan_chunks"
    config.engine.default = "openai"
    (tmp_path / "knowledge.db").write_text("", encoding="utf-8")

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    finding = findings["knowledge-chunks-to-cloud-risk"]
    assert finding.status == "fail"
    assert "knowledge.db chunks" in finding.potential_data_path
    assert "cloud inference" in finding.potential_data_path
    assert report.verdict == "local knowledge may be sent to cloud inference"


def test_knowledge_chunks_local_composition_is_not_fail(tmp_path):
    config = _low_noise_config()
    config.tools.enabled = "scan_chunks"
    config.engine.default = "ollama"
    config.intelligence.default_model = "qwen3.5:9b"
    (tmp_path / "knowledge.db").write_text("", encoding="utf-8")

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert "knowledge-chunks-to-cloud-risk" not in findings
    assert findings["knowledge-engine-tool-configured"].status in {"warn", "info"}
    assert findings["local-store-knowledge-db"].status == "warn"


def test_knowledge_db_is_reported(tmp_path):
    config = _low_noise_config()
    (tmp_path / "knowledge.db").write_text("", encoding="utf-8")

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["local-store-knowledge-db"].status == "warn"
    assert (
        "Knowledge and Deep Research database"
        in findings["local-store-knowledge-db"].title
    )


def test_knowledge_db_path_is_redacted(tmp_path):
    config = _low_noise_config()
    (tmp_path / "knowledge.db").write_text("", encoding="utf-8")

    report = build_data_boundary_report(config, tmp_path)
    payload = report.to_dict()
    payload_with_paths = report.to_dict(show_paths=True)

    assert str(tmp_path) not in str(payload)
    assert "knowledge.db" in str(payload)
    assert "knowledge.db" in str(payload_with_paths)


def test_knowledge_db_posix_permissions_checked(tmp_path):
    if os.name == "nt":
        pytest.skip("Unix permission bits are not checked on Windows")

    config = _low_noise_config()
    knowledge_db = tmp_path / "knowledge.db"
    knowledge_db.write_text("", encoding="utf-8")
    knowledge_db.chmod(0o644)

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["local-store-permissions-knowledge-db"].status == "warn"


def test_browser_resolver_tools_are_all_classified():
    from openjarvis.agents.tool_resolver import BROWSER_SUB_TOOLS

    assert set(BROWSER_SUB_TOOLS) <= BROWSER_TOOLS


def test_browser_axtree_is_warn(tmp_path):
    config = _low_noise_config()
    config.tools.enabled = "browser_axtree"

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["browser-tool-configured"].status == "warn"
    assert "browser_axtree" in findings["browser-tool-configured"].evidence


def test_credentials_toml_is_reported_without_reading_contents(tmp_path):
    config = _low_noise_config()
    creds = tmp_path / "credentials.toml"
    creds.write_text(
        'openai = { OPENAI_API_KEY = "super-secret-value" }\n', encoding="utf-8"
    )

    report = build_data_boundary_report(config, tmp_path)
    payload = report.to_dict(show_paths=True)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["local-store-credentials-toml"].status == "warn"
    assert "super-secret-value" not in str(payload)
    assert "OPENAI_API_KEY" not in findings["local-store-credentials-toml"].evidence


def test_credentials_toml_path_redacted(tmp_path):
    config = _low_noise_config()
    (tmp_path / "credentials.toml").write_text("", encoding="utf-8")

    report = build_data_boundary_report(config, tmp_path)
    payload = report.to_dict()

    assert str(tmp_path) not in str(payload)
    assert "credentials.toml" in str(payload)


def test_credentials_toml_permission_warning(tmp_path):
    if os.name == "nt":
        pytest.skip("Unix permission bits are not checked on Windows")

    config = _low_noise_config()
    creds = tmp_path / "credentials.toml"
    creds.write_text("", encoding="utf-8")
    creds.chmod(0o644)

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["local-store-permissions-credentials-toml"].status == "warn"


def test_runtime_credential_keys_are_all_covered():
    specialized = (
        set(API_KEY_ENV_VARS)
        | set(CHANNEL_SECRET_ENV_VARS)
        | set(CHANNEL_REFERENCE_ENV_VARS)
    )
    assert RUNTIME_CREDENTIAL_ENV_KEYS <= specialized | set(GENERIC_CREDENTIAL_ENV_VARS)


def test_runtime_credential_values_never_appear(tmp_path, monkeypatch):
    config = _low_noise_config()
    secret = "runtime-credential-secret-value-xyz"
    # Cover both specialized and generic keys.
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("ZULIP_API_KEY", secret)
    monkeypatch.setenv("LINE_CHANNEL_SECRET", secret)

    report = build_data_boundary_report(config, tmp_path)
    payload = report.to_dict(show_paths=True)
    blob = str(payload)

    assert secret not in blob
    findings = {finding.id: finding for finding in report.findings}
    assert "OPENAI_API_KEY is set" in findings["env-credential-openai_api_key"].evidence
    assert (
        "ZULIP_API_KEY is set"
        in findings["env-credential-generic-zulip_api_key"].evidence
    )
    assert (
        "LINE_CHANNEL_SECRET is set"
        in findings["env-credential-generic-line_channel_secret"].evidence
    )


def _clear_cloud_api_env(monkeypatch) -> None:
    for name in API_KEY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_external_surface_does_not_claim_cloud_inference_without_cloud(
    tmp_path,
    monkeypatch,
):
    _clear_cloud_api_env(monkeypatch)
    config = _low_noise_config()
    config.tools.enabled = "browser_navigate"
    config.security.local_tool_bypass = True

    report = build_data_boundary_report(config, tmp_path)
    payload = report.to_dict(show_paths=True)
    blob = str(payload).lower()

    findings = {finding.id: finding for finding in report.findings}
    assert findings["browser-tool-configured"].status == "warn"
    assert findings["security-local-tool-bypass-enabled"].status == "warn"
    assert "frontend-credential-storage-not-inspected" not in findings
    assert "cloud inference" not in blob


def test_browser_only_does_not_emit_cloud_api_key_claim(tmp_path, monkeypatch):
    _clear_cloud_api_env(monkeypatch)
    config = _low_noise_config()
    config.tools.enabled = "browser_axtree"

    report = build_data_boundary_report(config, tmp_path)
    payload = report.to_dict(show_paths=True)

    assert "frontend-credential-storage-not-inspected" not in _ids(report)
    assert "cloud API keys" not in str(payload)


def test_full_system_access_config_snapshot(tmp_path, monkeypatch):
    _clear_cloud_api_env(monkeypatch)
    profile = """
[engine]
default = "ollama"

[intelligence]
default_model = "qwen3.5:9b"

[agent]
default_agent = "orchestrator"
max_turns = 10

[tools]
enabled = [
    "shell_exec",
    "file_read",
    "file_write",
    "apply_patch",
    "code_interpreter",
    "git_status",
    "git_diff",
    "think",
    "calculator",
]
"""
    config_path = tmp_path / "config.toml"
    config_path.write_text(profile, encoding="utf-8")
    if os.name != "nt":
        config_path.chmod(0o600)
    config = load_config(config_path)
    # Mirror _low_noise_config store-path clearing so real home files are ignored.
    config.traces.db_path = ""
    config.telemetry.db_path = ""
    config.security.audit_log_path = ""
    config.security.vault_key_path = ""
    config.tools.storage.db_path = ""
    config.tools.storage.facts_path = ""
    config.sessions.db_path = ""
    config.agent_manager.db_path = ""
    config.optimize.db_path = ""
    config.optimize.optimizer_provider = ""
    config.optimize.judge_model = ""
    config.scheduler.db_path = ""
    config.skills.index_dir = ""
    config.analytics.enabled = False
    config.traces.enabled = False
    config.telemetry.enabled = False
    config.agent.context_from_memory = False
    config.skills.enabled = False
    config.digest.enabled = False
    config.channel.enabled = False
    config.server.host = "127.0.0.1"
    config.security.profile = "personal"
    config.learning.spec_search.enabled = False
    config.learning.enabled = False
    config.learning.training_enabled = False
    config.learning.auto_update = False

    report = build_data_boundary_report(config, tmp_path)

    findings = {finding.id: finding for finding in report.findings}
    assert findings["local-access-tools-configured"].status == "info"
    assert "shell_exec" in findings["local-access-tools-configured"].evidence
    assert "file_read" in findings["local-access-tools-configured"].evidence
    assert "knowledge-chunks-to-cloud-risk" not in findings
    assert "cloud-provider-configured" not in findings
    assert "frontend-credential-storage-not-inspected" not in findings
    assert report.verdict == "no fail or warn findings detected"
