"""Application data-boundary diagnostics for OpenJarvis.

The report builder intentionally limits itself to configuration values,
environment-key presence, and file existence. It never reads private user
content from connector credential files, memory files, trace databases, logs, or
other local runtime stores.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

Status = Literal["fail", "warn", "info"]

CLOUD_PROVIDER_KEYS = {
    "anthropic",
    "claude",
    "cloud",
    "codex",
    "deepseek",
    "gemini",
    "google",
    "litellm",
    "minimax",
    "openai",
    "openrouter",
}

LOCAL_ENGINE_KEYS = {
    "apple_fm",
    "exo",
    "gemma_cpp",
    "lemonade",
    "llamacpp",
    "lmstudio",
    "mlx",
    "nexa",
    "ollama",
    "sglang",
    "uzu",
    "vllm",
}

API_KEY_ENV_VARS = {
    "ANTHROPIC_API_KEY": ("Anthropic cloud inference", {"anthropic", "claude"}),
    "DEEPSEEK_API_KEY": ("DeepSeek cloud inference", {"deepseek"}),
    "GEMINI_API_KEY": ("Google/Gemini cloud inference", {"google", "gemini"}),
    "GOOGLE_API_KEY": ("Google/Gemini cloud inference", {"google", "gemini"}),
    "MINIMAX_API_KEY": ("MiniMax cloud inference", {"minimax"}),
    "OPENAI_API_KEY": ("OpenAI cloud inference", {"openai", "gpt"}),
    "OPENROUTER_API_KEY": ("OpenRouter cloud inference", {"openrouter"}),
    "TAVILY_API_KEY": ("Tavily web search", {"tavily", "web_search"}),
}

CHANNEL_SECRET_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("channel.telegram.bot_token", "Telegram bot token", "Telegram"),
    ("channel.discord.bot_token", "Discord bot token", "Discord"),
    ("channel.slack.bot_token", "Slack bot token", "Slack"),
    ("channel.slack.app_token", "Slack app token", "Slack"),
    ("channel.webhook.secret", "Webhook secret", "generic webhook"),
    ("channel.email.password", "Email password", "email"),
    ("channel.whatsapp.access_token", "WhatsApp access token", "WhatsApp"),
    ("channel.irc.password", "IRC password", "IRC"),
    ("channel.teams.app_password", "Teams app password", "Teams"),
    ("channel.matrix.access_token", "Matrix access token", "Matrix"),
    ("channel.mattermost.token", "Mattermost token", "Mattermost"),
    ("channel.feishu.app_secret", "Feishu app secret", "Feishu"),
    ("channel.bluebubbles.password", "BlueBubbles password", "BlueBubbles"),
)

CHANNEL_REFERENCE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("channel.webhook.url", "Webhook URL", "generic webhook"),
    ("channel.email.smtp_host", "Email SMTP host", "email"),
    ("channel.email.imap_host", "Email IMAP host", "email"),
    ("channel.email.username", "Email username", "email"),
    ("channel.whatsapp.phone_number_id", "WhatsApp phone number ID", "WhatsApp"),
    ("channel.signal.api_url", "Signal API URL", "Signal"),
    ("channel.signal.phone_number", "Signal phone number", "Signal"),
    ("channel.google_chat.webhook_url", "Google Chat webhook URL", "Google Chat"),
    ("channel.irc.server", "IRC server", "IRC"),
    ("channel.irc.nick", "IRC nick", "IRC"),
    ("channel.teams.app_id", "Teams app ID", "Teams"),
    ("channel.teams.service_url", "Teams service URL", "Teams"),
    ("channel.matrix.homeserver", "Matrix homeserver", "Matrix"),
    ("channel.mattermost.url", "Mattermost URL", "Mattermost"),
    ("channel.feishu.app_id", "Feishu app ID", "Feishu"),
    ("channel.bluebubbles.url", "BlueBubbles URL", "BlueBubbles"),
)

CHANNEL_SECRET_ENV_VARS = {
    "BLUEBUBBLES_PASSWORD": "BlueBubbles channel",
    "DISCORD_BOT_TOKEN": "Discord channel",
    "FEISHU_APP_SECRET": "Feishu channel",
    "MATTERMOST_TOKEN": "Mattermost channel",
    "MATRIX_ACCESS_TOKEN": "Matrix channel",
    "SLACK_APP_TOKEN": "Slack channel",
    "SLACK_BOT_TOKEN": "Slack channel",
    "TEAMS_APP_PASSWORD": "Teams channel",
    "TELEGRAM_BOT_TOKEN": "Telegram channel",
    "WHATSAPP_ACCESS_TOKEN": "WhatsApp channel",
}

CHANNEL_REFERENCE_ENV_VARS = {
    "BLUEBUBBLES_URL": "BlueBubbles channel",
    "FEISHU_APP_ID": "Feishu channel",
    "GOOGLE_CHAT_WEBHOOK_URL": "Google Chat channel",
    "MATTERMOST_URL": "Mattermost channel",
    "MATRIX_HOMESERVER": "Matrix channel",
    "SIGNAL_PHONE_NUMBER": "Signal channel",
    "TEAMS_APP_ID": "Teams channel",
    "WHATSAPP_PHONE_NUMBER_ID": "WhatsApp channel",
}

LOCAL_STORE_CANDIDATES: tuple[tuple[str, str, str, Status], ...] = (
    ("config-file", "Configuration file", "config.toml", "info"),
    ("memory-db", "Memory index database", "memory.db", "warn"),
    ("memory-facts", "Persistent memory facts", "memory_facts.jsonl", "warn"),
    ("traces-db", "Trace database", "traces.db", "warn"),
    ("telemetry-db", "Telemetry database", "telemetry.db", "info"),
    ("audit-db", "Security audit database", "audit.db", "info"),
    ("sessions-db", "Session database", "sessions.db", "warn"),
    ("agents-db", "Agent manager database", "agents.db", "warn"),
    ("optimize-db", "Optimization database", "optimize.db", "warn"),
    ("scheduler-db", "Scheduler database", "scheduler.db", "warn"),
    ("skill-index", "Skill index directory", "skill-index", "info"),
    ("vault-key", "Vault encryption key", ".vault_key", "warn"),
    ("embeddings-store", "Embeddings store", "embeddings", "warn"),
    ("soul-file", "SOUL memory file", "SOUL.md", "warn"),
    ("memory-file", "MEMORY memory file", "MEMORY.md", "warn"),
    ("user-file", "USER memory file", "USER.md", "warn"),
)

_CONFIG_STORE_PATHS: tuple[tuple[str, str, str, Status], ...] = (
    ("memory-db", "Memory index database", "tools.storage.db_path", "warn"),
    ("memory-facts", "Persistent memory facts", "tools.storage.facts_path", "warn"),
    ("traces-db", "Trace database", "traces.db_path", "warn"),
    ("telemetry-db", "Telemetry database", "telemetry.db_path", "info"),
    ("audit-db", "Security audit database", "security.audit_log_path", "info"),
    ("sessions-db", "Session database", "sessions.db_path", "warn"),
    ("agents-db", "Agent manager database", "agents.db_path", "warn"),
    ("optimize-db", "Optimization database", "optimize.db_path", "warn"),
    ("vault-key", "Vault encryption key", "security.vault_key_path", "warn"),
    ("scheduler-db", "Scheduler database", "scheduler.db_path", "warn"),
    ("skill-index", "Skill index directory", "skills.index_dir", "info"),
)

PERSONAL_DIGEST_SOURCES = {
    "apple_health",
    "dropbox",
    "gcalendar",
    "gcontacts",
    "gdrive",
    "github",
    "gmail",
    "google_tasks",
    "imessage",
    "notion",
    "obsidian",
    "oura",
    "outlook",
    "slack",
    "spotify",
    "strava",
    "whatsapp",
}

WEB_SEARCH_TOOLS = {"web_search", "search", "tavily_search"}
BROWSER_TOOLS = {
    "browser",
    "browser_click",
    "browser_extract",
    "browser_navigate",
    "browser_open",
    "browser_screenshot",
    "browser_search",
    "browser_type",
    "web_browser",
}
LOCAL_ACCESS_TOOLS = {
    "apply_patch",
    "code_interpreter",
    "db_query",
    "docker_shell_exec",
    "file_read",
    "file_write",
    "knowledge_sql",
    "memory_manage",
    "repl",
    "shell_exec",
}


@dataclass(frozen=True, slots=True)
class DataBoundaryFinding:
    """One application data-boundary finding."""

    id: str
    status: Status
    title: str
    potential_data_path: str
    evidence: str
    recommendation: str
    location: str = ""
    absolute_location: str = ""

    def to_dict(self, *, show_paths: bool = False) -> dict[str, str]:
        """Return a stable JSON-serializable representation.

        Absolute paths and connector basenames are redacted by default. When
        ``show_paths`` is true, the location field exposes the absolute path for
        local debugging.
        """
        payload = {
            "id": self.id,
            "status": self.status,
            "title": self.title,
            "potential_data_path": self.potential_data_path,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }
        if self.absolute_location:
            payload["location"] = (
                self.absolute_location if show_paths else self.location
            )
        elif self.location:
            payload["location"] = self.location
        return payload


@dataclass(frozen=True, slots=True)
class DataBoundaryReport:
    """Structured result returned by the data-boundary audit."""

    verdict: str
    root: str
    config_loaded: bool
    findings: tuple[DataBoundaryFinding, ...]

    def summary(self) -> dict[str, int]:
        """Count findings by status."""
        counts = {"fail": 0, "warn": 0, "info": 0}
        for finding in self.findings:
            counts[finding.status] += 1
        return counts

    def to_dict(self, *, show_paths: bool = False) -> dict[str, Any]:
        """Return a stable JSON-serializable representation."""
        return {
            "schema_version": 1,
            "verdict": self.verdict,
            "root": self.root if show_paths else _redact_root(self.root),
            "config_loaded": self.config_loaded,
            "summary": self.summary(),
            "findings": [
                finding.to_dict(show_paths=show_paths) for finding in self.findings
            ],
        }


class _FindingBuilder:
    """Small helper that preserves insertion order and deduplicates by id."""

    def __init__(self) -> None:
        self._findings: list[DataBoundaryFinding] = []
        self._seen: set[str] = set()

    def add(
        self,
        *,
        finding_id: str,
        status: Status,
        title: str,
        potential_data_path: str,
        evidence: str,
        recommendation: str,
        location: str = "",
        absolute_location: str = "",
    ) -> None:
        if finding_id in self._seen:
            return
        self._seen.add(finding_id)
        self._findings.append(
            DataBoundaryFinding(
                id=finding_id,
                status=status,
                title=title,
                potential_data_path=potential_data_path,
                evidence=evidence,
                recommendation=recommendation,
                location=location,
                absolute_location=absolute_location,
            )
        )

    def build(self) -> tuple[DataBoundaryFinding, ...]:
        return tuple(self._findings)


def build_data_boundary_report(
    config: Any,
    root: Path | None,
    *,
    config_loaded: bool = True,
    config_error: str = "",
    root_error: str = "",
) -> DataBoundaryReport:
    """Build a data-boundary report from config and runtime paths.

    The function is side-effect-free. It uses defensive ``getattr`` access so
    the command remains robust across configuration additions.
    """

    builder = _FindingBuilder()
    root_path: Path | None = None
    root_label = "<unresolved-openjarvis-home>"
    if root is not None:
        try:
            root_path = root.expanduser().resolve()
            root_label = str(root_path)
        except Exception as exc:  # pragma: no cover - defensive path handling
            root_error = f"{type(exc).__name__}: {exc}"

    if root_error:
        builder.add(
            finding_id="config-root-error",
            status="fail",
            title="OpenJarvis home directory could not be resolved",
            potential_data_path="runtime state root -> local store checks",
            evidence=_truncate(root_error),
            recommendation=(
                "Fix OPENJARVIS_HOME or XDG_DATA_HOME before relying on "
                "local-store data-boundary checks."
            ),
        )

    if config_error:
        builder.add(
            finding_id="config-load-error",
            status="fail",
            title="OpenJarvis config could not be loaded",
            potential_data_path="config.toml -> data-boundary report",
            evidence=_truncate(config_error),
            recommendation=(
                "Fix the configuration file before relying on config-derived "
                "data-boundary checks. Local store and environment checks still run."
            ),
        )
    elif config_loaded:
        _audit_outbound_settings(config, builder)
        _audit_telemetry_settings(config, builder)
        _audit_memory_cloud_composition(config, builder)
        _audit_memory_service(config, builder)
        _audit_deep_research_settings(config, builder)
        _audit_trace_and_learning_settings(config, builder)
        _audit_tool_surfaces(config, builder)
        _audit_server_exposure(config, builder)
        _audit_channel_settings(config, builder)
        _audit_skills_and_digest(config, builder)
        _audit_speech_settings(config, builder)
    elif not root_error:
        builder.add(
            finding_id="config-file-missing",
            status="info",
            title="OpenJarvis config file was not found",
            potential_data_path="configuration defaults -> data-boundary report",
            evidence="config_loaded = false",
            recommendation=(
                "Run `jarvis init` before relying on config-derived checks. "
                "Local store and environment checks still run."
            ),
        )

    active_tools = (
        _configured_tools(config) if config_loaded and not config_error else set()
    )
    active_config = config if config_loaded and not config_error else None
    if active_config is not None:
        _audit_security_settings(
            active_config,
            builder,
            has_cloud_surface=_has_cloud_or_api_surface(active_config, active_tools),
        )

    if root_path is not None:
        _audit_local_stores(root_path, builder, config=active_config)
        _audit_connector_credentials(root_path, builder)
        if active_config is not None:
            _audit_local_channel_credential_dirs(active_config, root_path, builder)
    _audit_environment_credentials(
        active_config,
        builder,
        active_tools=active_tools,
    )
    _audit_channel_environment_credentials(active_config, builder)
    if _has_cloud_or_api_surface(active_config, active_tools):
        _audit_frontend_storage_scope(builder)

    findings = builder.build()
    return DataBoundaryReport(
        verdict=_derive_verdict(findings),
        root=root_label,
        config_loaded=config_loaded and not bool(config_error),
        findings=findings,
    )


def _audit_outbound_settings(config: Any, builder: _FindingBuilder) -> None:
    if bool(_get(config, "analytics.enabled", False)):
        builder.add(
            finding_id="analytics-enabled",
            status="info",
            title="Outbound usage analytics are enabled",
            potential_data_path="runtime usage events -> analytics endpoint",
            evidence="analytics.enabled = true",
            recommendation=(
                "Set analytics.enabled = false for no outbound usage analytics. "
                "This finding does not assert that prompt content is sent."
            ),
        )

    provider = _get(config, "intelligence.provider", "")
    if _is_cloud_value(provider):
        builder.add(
            finding_id="cloud-provider-configured",
            status="warn",
            title="Cloud model provider configured",
            potential_data_path=(
                "prompts, memory context, and tool outputs -> cloud provider"
            ),
            evidence=f"intelligence.provider = {_quote(provider)}",
            recommendation=(
                "Review what context is sent before enabling cloud inference, "
                "or use a local provider for local-only operation."
            ),
        )

    default_model = _get(config, "intelligence.default_model", "")
    if _looks_like_cloud_model(default_model):
        builder.add(
            finding_id="cloud-default-model-configured",
            status="warn",
            title="Cloud default model configured",
            potential_data_path="model requests -> default cloud model",
            evidence=f"intelligence.default_model = {_quote(default_model)}",
            recommendation=("Use a local default model for local-only operation."),
        )

    preferred_engine = _get(config, "intelligence.preferred_engine", "")
    if _is_cloud_value(preferred_engine):
        builder.add(
            finding_id="cloud-preferred-engine-configured",
            status="warn",
            title="Cloud preferred engine configured",
            potential_data_path="model requests -> preferred cloud engine",
            evidence=f"intelligence.preferred_engine = {_quote(preferred_engine)}",
            recommendation="Use a local preferred engine for local-only operation.",
        )

    default_engine = _get(config, "engine.default", "")
    if _is_cloud_value(default_engine):
        builder.add(
            finding_id="cloud-default-engine-configured",
            status="warn",
            title="Cloud default engine configured",
            potential_data_path="model requests -> default cloud engine",
            evidence=f"engine.default = {_quote(default_engine)}",
            recommendation="Use a local default engine for local-only operation.",
        )

    optimize_provider = _get(config, "optimize.optimizer_provider", "")
    if _is_cloud_value(optimize_provider):
        builder.add(
            finding_id="cloud-optimizer-provider-configured",
            status="info",
            title="Cloud optimizer provider is configured",
            potential_data_path="optimization context -> optimizer provider",
            evidence=f"optimize.optimizer_provider = {_quote(optimize_provider)}",
            recommendation=(
                "Before running optimization, review whether examples, traces, "
                "or prompts may be sent to this provider."
            ),
        )

    judge_model = _get(config, "optimize.judge_model", "")
    if _looks_like_cloud_model(judge_model):
        builder.add(
            finding_id="cloud-judge-model-configured",
            status="info",
            title="Cloud judge model appears configured",
            potential_data_path="optimization examples/results -> judge model",
            evidence=f"optimize.judge_model = {_quote(judge_model)}",
            recommendation="Use a local judge model for local-only optimization.",
        )


def _audit_telemetry_settings(config: Any, builder: _FindingBuilder) -> None:
    if bool(_get(config, "telemetry.enabled", False)):
        builder.add(
            finding_id="telemetry-enabled",
            status="warn",
            title="Telemetry capture is enabled",
            potential_data_path=(
                "runtime metrics and inference events -> telemetry database"
            ),
            evidence="telemetry.enabled = true",
            recommendation=(
                "Disable telemetry when local-only metrics collection is not "
                "needed. Treat telemetry.db as sensitive when enabled."
            ),
        )


def _audit_memory_service(config: Any, builder: _FindingBuilder) -> None:
    if not bool(_get(config, "tools.storage.enabled", False)):
        return
    cloud_signals = [
        _get(config, "intelligence.provider", ""),
        _get(config, "intelligence.preferred_engine", ""),
        _get(config, "engine.default", ""),
        _get(config, "intelligence.default_model", ""),
    ]
    has_cloud = any(
        _is_cloud_value(value) or _looks_like_cloud_model(value)
        for value in cloud_signals
    )
    evidence = "tools.storage.enabled = true"
    if has_cloud:
        evidence += "; cloud inference surface detected"
    builder.add(
        finding_id="memory-service-enabled",
        status="warn",
        title="Automatic memory service is enabled",
        potential_data_path=(
            "conversation content -> extracted facts -> local memory store"
        ),
        evidence=evidence,
        recommendation=(
            "Review what conversations are persisted before enabling the "
            "background memory service on sensitive workloads."
        ),
    )


def _audit_deep_research_settings(config: Any, builder: _FindingBuilder) -> None:
    engine = _get(config, "deep_research.engine", "")
    model = _get(config, "deep_research.model", "")
    cloud_engine = _is_cloud_value(engine)
    cloud_model = _looks_like_cloud_model(model)
    if not cloud_engine and not cloud_model:
        return
    evidence_parts = []
    if cloud_engine:
        evidence_parts.append(f"deep_research.engine = {_quote(engine)}")
    if cloud_model:
        evidence_parts.append(f"deep_research.model = {_quote(model)}")
    builder.add(
        finding_id="deep-research-cloud-configured",
        status="warn",
        title="Cloud deep-research engine or model configured",
        potential_data_path="research planner context -> cloud engine/model",
        evidence="; ".join(evidence_parts),
        recommendation=(
            "Use local deep-research engine and model settings for local-only "
            "operation."
        ),
    )


def _audit_security_settings(
    config: Any,
    builder: _FindingBuilder,
    *,
    has_cloud_surface: bool,
) -> None:
    profile = str(_get(config, "security.profile", "") or "").strip()
    if not profile:
        builder.add(
            finding_id="security-profile-unset",
            status="info",
            title="Security profile is not set",
            potential_data_path="security defaults -> guardrails and server posture",
            evidence="security.profile is empty",
            recommendation=(
                "Set security.profile to personal, shared, or server to apply "
                "a documented guardrails preset."
            ),
        )

    if not has_cloud_surface:
        return

    if bool(_get(config, "security.local_engine_bypass", False)):
        builder.add(
            finding_id="security-local-engine-bypass-enabled",
            status="warn",
            title="Local engine guardrail bypass is enabled with cloud surfaces",
            potential_data_path=(
                "cloud-bound prompts/outputs -> guardrails bypass for local engines"
            ),
            evidence=(
                "security.local_engine_bypass = true with cloud-capable settings"
            ),
            recommendation=(
                "Disable local_engine_bypass unless the cloud surface is intentional "
                "and reviewed."
            ),
        )

    if bool(_get(config, "security.local_tool_bypass", False)):
        builder.add(
            finding_id="security-local-tool-bypass-enabled",
            status="warn",
            title="Local tool guardrail bypass is enabled with cloud surfaces",
            potential_data_path=(
                "cloud-bound tool arguments/results -> guardrails bypass"
            ),
            evidence=("security.local_tool_bypass = true with cloud-capable settings"),
            recommendation=(
                "Disable local_tool_bypass unless the cloud surface is intentional "
                "and reviewed."
            ),
        )


def _audit_memory_cloud_composition(
    config: Any,
    builder: _FindingBuilder,
) -> None:
    context_from_memory = bool(_get(config, "agent.context_from_memory", False))
    cloud_signals = [
        _get(config, "intelligence.provider", ""),
        _get(config, "intelligence.preferred_engine", ""),
        _get(config, "engine.default", ""),
        _get(config, "intelligence.default_model", ""),
    ]
    active_cloud = [
        str(value)
        for value in cloud_signals
        if _is_cloud_value(value) or _looks_like_cloud_model(value)
    ]

    if context_from_memory and active_cloud:
        builder.add(
            finding_id="memory-context-to-cloud-risk",
            status="fail",
            title="Local memory may be injected into cloud-bound prompts",
            potential_data_path=(
                "indexed local memory -> prompt context -> cloud inference provider"
            ),
            evidence=(
                "agent.context_from_memory = true; cloud setting(s) = "
                + ", ".join(active_cloud)
            ),
            recommendation=(
                "Disable agent.context_from_memory before using cloud inference, "
                "or use local engines when indexed memory contains sensitive data."
            ),
        )
    elif context_from_memory:
        builder.add(
            finding_id="memory-context-injection-enabled",
            status="info",
            title="Memory context injection is enabled",
            potential_data_path="indexed local memory -> future prompt context",
            evidence="agent.context_from_memory = true",
            recommendation=(
                "Keep indexed memory scoped to data that may safely appear in future "
                "prompts, especially if cloud engines are enabled later."
            ),
        )


def _audit_trace_and_learning_settings(
    config: Any,
    builder: _FindingBuilder,
) -> None:
    if bool(_get(config, "traces.enabled", False)):
        builder.add(
            finding_id="traces-enabled",
            status="warn",
            title="Trace capture is enabled",
            potential_data_path=(
                "prompts, outputs, tool calls, and tool results -> traces database"
            ),
            evidence="traces.enabled = true",
            recommendation=(
                "Disable traces when debugging or trace-driven learning is not "
                "needed. Treat traces.db as sensitive when enabled."
            ),
        )

    if bool(_get(config, "learning.enabled", False)):
        builder.add(
            finding_id="learning-enabled",
            status="warn",
            title="Learning from local runtime data is enabled",
            potential_data_path=(
                "local traces/telemetry/feedback -> routing, agent, skill, or "
                "model updates"
            ),
            evidence="learning.enabled = true",
            recommendation=(
                "Review active learning sub-policies before using sensitive traces."
            ),
        )

    if bool(_get(config, "learning.training_enabled", False)):
        builder.add(
            finding_id="training-enabled",
            status="warn",
            title="Training pipeline is enabled",
            potential_data_path="trace-derived examples -> model adapters",
            evidence="learning.training_enabled = true",
            recommendation=(
                "Disable training unless trace reuse for model updates is intentional."
            ),
        )

    if bool(_get(config, "learning.auto_update", False)):
        builder.add(
            finding_id="learning-auto-update-enabled",
            status="warn",
            title="Automatic learning updates are enabled",
            potential_data_path="runtime feedback/traces -> automatic updates",
            evidence="learning.auto_update = true",
            recommendation=(
                "Use manual updates when explicit review is needed before "
                "trace-derived changes."
            ),
        )

    spec_search_enabled = bool(_get(config, "learning.spec_search.enabled", False))
    teacher_engine = _get(config, "learning.spec_search.teacher_engine", "")
    teacher_model = _get(config, "learning.spec_search.teacher_model", "")
    if spec_search_enabled and _is_cloud_value(teacher_engine):
        builder.add(
            finding_id="spec-search-cloud-teacher-enabled",
            status="fail",
            title="LLM-guided spec search uses a cloud teacher engine",
            potential_data_path=(
                "diagnostics/spec-search context -> cloud teacher model"
            ),
            evidence=(
                "learning.spec_search.enabled = true; "
                f"teacher_engine = {_quote(teacher_engine)}; "
                f"teacher_model = {_quote(teacher_model)}"
            ),
            recommendation=(
                "Use a local teacher engine/model or keep spec search disabled for "
                "local-only operation."
            ),
        )


def _audit_tool_surfaces(config: Any, builder: _FindingBuilder) -> None:
    tools = _configured_tools(config)

    if tools & WEB_SEARCH_TOOLS:
        builder.add(
            finding_id="web-search-tool-configured",
            status="warn",
            title="Web search tool is configured",
            potential_data_path="user or agent search query -> external search service",
            evidence=f"configured tool(s) = {_format_tools(tools & WEB_SEARCH_TOOLS)}",
            recommendation=(
                "Review search queries before using web search with sensitive prompts."
            ),
        )

    if tools & BROWSER_TOOLS:
        builder.add(
            finding_id="browser-tool-configured",
            status="warn",
            title="Browser automation tool is configured",
            potential_data_path="agent browser actions -> external web pages",
            evidence=f"configured tool(s) = {_format_tools(tools & BROWSER_TOOLS)}",
            recommendation=(
                "Use browser automation only when web interactions are intentional."
            ),
        )

    local_access = tools & LOCAL_ACCESS_TOOLS
    if local_access:
        builder.add(
            finding_id="local-access-tools-configured",
            status="info",
            title="Local file, shell, or code tools are configured",
            potential_data_path="local files/process output -> agent context",
            evidence=f"configured tool(s) = {_format_tools(local_access)}",
            recommendation=(
                "Review tool permissions and prompts before giving the agent access "
                "to sensitive local files or command output."
            ),
        )

    mcp_enabled = bool(_get(config, "tools.mcp.enabled", False))
    mcp_servers = str(_get(config, "tools.mcp.servers", "") or "").strip()
    if mcp_enabled and mcp_servers:
        builder.add(
            finding_id="mcp-servers-configured",
            status="warn",
            title="External MCP servers are configured",
            potential_data_path="agent tool calls/context -> configured MCP servers",
            evidence="tools.mcp.enabled = true; tools.mcp.servers is non-empty",
            recommendation=(
                "Review MCP server trust, transport, and tool schemas before sending "
                "sensitive prompts or tool arguments."
            ),
        )


def _iter_local_store_targets(
    root: Path,
    config: Any | None,
) -> Iterable[tuple[str, str, Path, str, Status]]:
    """Yield store targets as (finding_id, title, path, location_label, status)."""
    targets: dict[str, tuple[str, Path, str, Status]] = {}

    for finding_id, title, relative_path, status in LOCAL_STORE_CANDIDATES:
        targets[finding_id] = (title, root / relative_path, relative_path, status)

    if config is not None:
        for finding_id, title, dotted_path, status in _CONFIG_STORE_PATHS:
            raw = str(_get(config, dotted_path, "") or "").strip()
            if not raw:
                if finding_id == "scheduler-db":
                    path = root / "scheduler.db"
                    location = "scheduler.db"
                else:
                    continue
            else:
                path = Path(raw).expanduser()
                if not path.is_absolute():
                    path = root / path
                try:
                    resolved_path = path.resolve()
                except OSError:
                    resolved_path = path
                location = _location_label(resolved_path, root)

            existing = targets.get(finding_id)
            if existing is not None and existing[1].exists() and not path.exists():
                continue
            targets[finding_id] = (title, path, location, status)

    seen_resolved: set[str] = set()
    for finding_id, (title, path, location, status) in targets.items():
        try:
            resolved_key = str(path.resolve())
        except OSError:
            resolved_key = str(path)
        if resolved_key in seen_resolved:
            continue
        seen_resolved.add(resolved_key)
        yield finding_id, title, path, location, status


def _audit_local_stores(
    root: Path,
    builder: _FindingBuilder,
    *,
    config: Any | None = None,
) -> None:
    if not root.exists():
        return
    for finding_id, title, path, location, status in _iter_local_store_targets(
        root,
        config,
    ):
        if not path.exists():
            continue
        builder.add(
            finding_id=f"local-store-{finding_id}",
            status=status,
            title=f"{title} exists locally",
            potential_data_path=f"local runtime state -> {location}",
            evidence=f"path exists: {location}",
            recommendation=(
                "Review retention, backups, and filesystem permissions for this "
                "local store."
            ),
            location=location,
            absolute_location=str(path),
        )
        permission_note = _permission_note(path)
        if permission_note:
            builder.add(
                finding_id=f"local-store-permissions-{finding_id}",
                status="warn",
                title=f"{title} permissions need review",
                potential_data_path=f"local runtime state -> {location}",
                evidence=permission_note,
                recommendation=(
                    "Restrict this file or directory to the current user before "
                    "storing sensitive data."
                ),
                location=location,
                absolute_location=str(path),
            )


def _audit_connector_credentials(root: Path, builder: _FindingBuilder) -> None:
    connectors_dir = root / "connectors"
    if not connectors_dir.exists():
        return
    for path in sorted(connectors_dir.glob("*.json")):
        digest = hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:8]
        builder.add(
            finding_id=f"connector-token-{digest}",
            status="info",
            title="Connector credential file is present",
            potential_data_path="connector OAuth/API credentials -> local file",
            evidence="credential file exists under connectors/*.json",
            recommendation=(
                "This audit did not read the file contents. Use --show-paths for "
                "local debugging, and review account scopes and token rotation."
            ),
            location="connectors/<redacted>.json",
            absolute_location=str(path),
        )


def _audit_environment_credentials(
    config: Any | None,
    builder: _FindingBuilder,
    *,
    active_tools: set[str],
) -> None:
    active_values: set[str] = set(active_tools)
    if config is not None:
        active_values.update(
            {
                str(_get(config, "intelligence.provider", "")).lower(),
                str(_get(config, "intelligence.preferred_engine", "")).lower(),
                str(_get(config, "engine.default", "")).lower(),
                str(_get(config, "intelligence.default_model", "")).lower(),
            }
        )

    for env_name, (purpose, aliases) in sorted(API_KEY_ENV_VARS.items()):
        if not os.environ.get(env_name):
            continue
        active = any(alias in value for alias in aliases for value in active_values)
        status: Status = "warn" if active else "info"
        builder.add(
            finding_id=f"env-credential-{env_name.lower()}",
            status=status,
            title=f"Cloud/API credential available in environment: {env_name}",
            potential_data_path=f"process environment -> {purpose}",
            evidence=f"{env_name} is set; value was not read or printed",
            recommendation=(
                "Unset this variable for local-only operation. The audit reports "
                "only presence and never prints credential values."
            ),
        )


def _audit_server_exposure(config: Any, builder: _FindingBuilder) -> None:
    host = str(_get(config, "server.host", "") or "")
    if host in {"0.0.0.0", "::"}:
        builder.add(
            finding_id="server-binds-all-interfaces",
            status="warn",
            title="Server is configured to bind all network interfaces",
            potential_data_path="OpenJarvis HTTP server -> local network interfaces",
            evidence=f"server.host = {_quote(host)}",
            recommendation=(
                "Use server.host = '127.0.0.1' unless LAN exposure is intentional."
            ),
        )

    a2a_enabled = bool(_get(config, "a2a.enabled", False))
    a2a_token = str(_get(config, "a2a.auth_token", "") or "")
    if a2a_enabled and not a2a_token:
        builder.add(
            finding_id="a2a-enabled-without-auth-token",
            status="fail",
            title="A2A server is enabled without an auth token",
            potential_data_path="inbound A2A requests -> OpenJarvis agent runtime",
            evidence="a2a.enabled = true; a2a.auth_token is empty",
            recommendation=(
                "Set a2a.auth_token or disable A2A unless the network is trusted."
            ),
        )


def _audit_channel_settings(config: Any, builder: _FindingBuilder) -> None:
    channel_enabled = bool(_get(config, "channel.enabled", False))
    default_channel = str(_get(config, "channel.default_channel", "") or "")
    configured_secrets = _non_empty_paths(config, CHANNEL_SECRET_FIELDS)
    configured_refs = _non_empty_paths(config, CHANNEL_REFERENCE_FIELDS)

    if channel_enabled:
        evidence = "channel.enabled = true"
        if default_channel:
            evidence += "; channel.default_channel is set; value redacted"
        has_channel_surface = bool(
            default_channel or configured_secrets or configured_refs
        )
        status: Status = "warn" if has_channel_surface else "info"
        builder.add(
            finding_id="channels-enabled",
            status=status,
            title="Messaging channels are enabled",
            potential_data_path=(
                "user messages and assistant replies -> configured channel services"
            ),
            evidence=evidence,
            recommendation=(
                "Review active channel credentials and account scopes before "
                "routing sensitive conversations through external services."
            ),
        )

    for dotted_path, label, service in configured_secrets:
        status = "warn" if channel_enabled else "info"
        normalized = dotted_path.replace(".", "-").replace("_", "-")
        builder.add(
            finding_id=f"channel-secret-{normalized}",
            status=status,
            title=f"Channel secret configured: {label}",
            potential_data_path=f"OpenJarvis channel messages -> {service}",
            evidence=f"{dotted_path} is non-empty; value was not printed",
            recommendation=(
                "Use dedicated bot/service credentials and rotate them after tests. "
                "The audit reports only presence and never prints secret values."
            ),
        )

    for dotted_path, label, service in configured_refs:
        status = "warn" if channel_enabled else "info"
        normalized = dotted_path.replace(".", "-").replace("_", "-")
        builder.add(
            finding_id=f"channel-reference-{normalized}",
            status=status,
            title=f"Channel endpoint or identifier configured: {label}",
            potential_data_path=f"OpenJarvis channel messages -> {service}",
            evidence=f"{dotted_path} is non-empty; value was not printed",
            recommendation=(
                "Review configured channel endpoints and identifiers before "
                "routing sensitive conversations through external services."
            ),
        )


def _audit_channel_environment_credentials(
    config: Any | None,
    builder: _FindingBuilder,
) -> None:
    channel_enabled = bool(_get(config, "channel.enabled", False)) if config else False
    for env_name, purpose in sorted(CHANNEL_SECRET_ENV_VARS.items()):
        if not os.environ.get(env_name):
            continue
        status: Status = "warn" if channel_enabled else "info"
        builder.add(
            finding_id=f"channel-env-secret-{env_name.lower()}",
            status=status,
            title=f"Channel secret available in environment: {env_name}",
            potential_data_path=f"process environment -> {purpose}",
            evidence=f"{env_name} is set; value was not read or printed",
            recommendation=(
                "Unset channel secrets when external messaging is not in use. "
                "The audit reports only presence and never prints secret values."
            ),
        )

    for env_name, purpose in sorted(CHANNEL_REFERENCE_ENV_VARS.items()):
        if not os.environ.get(env_name):
            continue
        status = "warn" if channel_enabled else "info"
        builder.add(
            finding_id=f"channel-env-reference-{env_name.lower()}",
            status=status,
            title=f"Channel endpoint or identifier in environment: {env_name}",
            potential_data_path=f"process environment -> {purpose}",
            evidence=f"{env_name} is set; value was not read or printed",
            recommendation=(
                "Unset channel endpoint variables when external messaging is not "
                "in use. The audit reports only presence."
            ),
        )


def _audit_local_channel_credential_dirs(
    config: Any,
    root: Path,
    builder: _FindingBuilder,
) -> None:
    auth_dir_value = str(
        _get(config, "channel.whatsapp_baileys.auth_dir", "") or ""
    ).strip()
    candidates: list[tuple[Path, str]] = []
    if auth_dir_value:
        candidates.append((Path(auth_dir_value).expanduser(), "<redacted>"))
    candidates.append(
        (root / "whatsapp_baileys_bridge" / "auth", "whatsapp_baileys_bridge/auth")
    )

    seen_resolved: set[str] = set()
    for path, location in candidates:
        try:
            resolved = path.resolve()
            resolved_key = str(resolved)
        except OSError:
            resolved = path
            resolved_key = str(path)
        if resolved_key in seen_resolved or not path.exists():
            continue
        seen_resolved.add(resolved_key)
        path_digest = hashlib.sha256(resolved_key.encode("utf-8")).hexdigest()[:8]
        builder.add(
            finding_id=f"channel-local-credential-dir-whatsapp-baileys-{path_digest}",
            status="info",
            title="WhatsApp Baileys credential directory is present",
            potential_data_path="WhatsApp session credentials -> local directory",
            evidence="credential directory exists; contents were not inspected",
            recommendation=(
                "Review permissions and retention for local messaging session "
                "credentials."
            ),
            location=location,
            absolute_location=resolved_key,
        )


def _audit_frontend_storage_scope(builder: _FindingBuilder) -> None:
    builder.add(
        finding_id="frontend-credential-storage-not-inspected",
        status="info",
        title="Frontend credential storage is outside this CLI scan",
        potential_data_path="desktop/web frontend storage -> cloud API keys",
        evidence="CLI scan cannot inspect browser localStorage or Tauri storage",
        recommendation=(
            "Review frontend credential-storage work separately. This finding is "
            "a scope note for cloud/API-key deployments, not a detected leak."
        ),
    )


def _audit_skills_and_digest(config: Any, builder: _FindingBuilder) -> None:
    if bool(_get(config, "skills.enabled", False)):
        builder.add(
            finding_id="skills-enabled",
            status="info",
            title="Skills are enabled",
            potential_data_path="agent-selected skills -> local files and tools",
            evidence="skills.enabled = true",
            recommendation=(
                "Review installed skills, especially skills with file, shell, "
                "browser, or network access."
            ),
        )

    if bool(_get(config, "skills.auto_sync", False)):
        builder.add(
            finding_id="skills-auto-sync-enabled",
            status="warn",
            title="Skill auto-sync is enabled",
            potential_data_path="configured skill source -> local skill directory",
            evidence="skills.auto_sync = true",
            recommendation="Review external skill sources before enabling auto-sync.",
        )

    if bool(_get(config, "digest.enabled", False)):
        sources = sorted(set(_iter_digest_sources(config)) & PERSONAL_DIGEST_SOURCES)
        builder.add(
            finding_id="digest-enabled",
            status="warn",
            title="Morning digest is enabled",
            potential_data_path="personal connectors -> digest generation context",
            evidence=(
                "digest.enabled = true; sources = "
                + (", ".join(sources) or "configured sections")
            ),
            recommendation=(
                "Review digest sources and connector scopes before enabling "
                "personal-data digests."
            ),
        )


def _audit_speech_settings(config: Any, builder: _FindingBuilder) -> None:
    speech_backend = str(_get(config, "speech.backend", "") or "").lower()
    if speech_backend in {"openai", "deepgram"}:
        builder.add(
            finding_id="cloud-speech-backend-configured",
            status="warn",
            title="Cloud speech backend configured",
            potential_data_path="speech audio or transcripts -> cloud speech provider",
            evidence=f"speech.backend = {_quote(speech_backend)}",
            recommendation=(
                "Use a local speech backend for local-only audio processing."
            ),
        )


def _has_cloud_or_api_surface(config: Any | None, active_tools: set[str]) -> bool:
    if any(os.environ.get(name) for name in API_KEY_ENV_VARS):
        return True
    if active_tools & WEB_SEARCH_TOOLS:
        return True
    if config is None:
        return False
    values = [
        _get(config, "intelligence.provider", ""),
        _get(config, "intelligence.preferred_engine", ""),
        _get(config, "engine.default", ""),
        _get(config, "intelligence.default_model", ""),
        _get(config, "deep_research.engine", ""),
        _get(config, "deep_research.model", ""),
        _get(config, "learning.spec_search.teacher_engine", ""),
        _get(config, "optimize.optimizer_provider", ""),
        _get(config, "optimize.judge_model", ""),
        _get(config, "speech.backend", ""),
    ]
    return any(
        _is_cloud_value(value) or _looks_like_cloud_model(value) for value in values
    )


def _derive_verdict(findings: Iterable[DataBoundaryFinding]) -> str:
    finding_ids = {finding.id for finding in findings}
    statuses = {finding.status for finding in findings}

    if "memory-context-to-cloud-risk" in finding_ids:
        return "local memory may be sent to cloud inference"
    if "config-root-error" in finding_ids:
        return "OpenJarvis home must be fixed before full data-boundary review"
    if "config-load-error" in finding_ids:
        return "configuration must be fixed before full data-boundary review"
    if "fail" in statuses:
        return "attention required for application data boundaries"
    if any(
        fid in finding_ids
        for fid in {
            "cloud-provider-configured",
            "cloud-preferred-engine-configured",
            "cloud-default-engine-configured",
            "cloud-default-model-configured",
            "cloud-speech-backend-configured",
            "deep-research-cloud-configured",
        }
    ):
        return "cloud-capable data boundaries configured"
    if "warn" in statuses:
        return "local sensitive stores or optional data flows detected"
    return "no fail or warn findings detected"


def _configured_tools(config: Any) -> set[str]:
    values: list[Any] = [
        _get(config, "tools.enabled", ""),
        _get(config, "agent.tools", ""),
    ]
    tools: set[str] = set()
    for value in values:
        if isinstance(value, str):
            raw_items = value.split(",")
        elif isinstance(value, Iterable):
            raw_items = list(value)
        else:
            raw_items = []
        for item in raw_items:
            normalized = str(item).strip().lower().replace("-", "_")
            if normalized:
                tools.add(normalized)
    return tools


def _get(obj: Any, dotted_path: str, default: Any = None) -> Any:
    current = obj
    for part in dotted_path.split("."):
        if current is None:
            return default
        current = getattr(current, part, default)
    return current


def _is_cloud_value(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    if not text or text in LOCAL_ENGINE_KEYS:
        return False
    return any(key in text for key in CLOUD_PROVIDER_KEYS)


def _looks_like_cloud_model(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    if not text:
        return False
    return any(key in text for key in CLOUD_PROVIDER_KEYS) or text.startswith("gpt-")


def _iter_digest_sources(config: Any) -> Iterable[str]:
    digest = _get(config, "digest", None)
    if digest is None:
        return []
    sections = _get(digest, "sections", []) or []
    optional_sections = _get(digest, "optional_sections", []) or []
    names = list(sections) + list(optional_sections)
    sources: list[str] = []
    for name in names:
        section = getattr(digest, str(name), None)
        if section is None:
            continue
        section_sources = getattr(section, "sources", []) or []
        sources.extend(str(source) for source in section_sources)
    return sources


def _non_empty_paths(
    config: Any,
    fields: tuple[tuple[str, str, str], ...],
) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    for dotted_path, label, service in fields:
        value = _get(config, dotted_path, "")
        if str(value or "").strip():
            results.append((dotted_path, label, service))
    return results


def _location_label(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return "<redacted>"


def _permission_note(path: Path) -> str:
    try:
        if path.is_symlink():
            return "path is a symlink"
        if os.name == "nt":
            return ""
        mode = path.stat().st_mode & 0o777
    except OSError:
        return "could not read filesystem metadata"
    if mode & 0o077:
        return f"permissions are {mode:03o}; group/other access is present"
    return ""


def _format_tools(tools: Iterable[str]) -> str:
    return ", ".join(sorted(tools))


def _quote(value: Any) -> str:
    return repr(str(value))


def _redact_root(root: str) -> str:
    if root.startswith("<"):
        return root
    path = Path(root)
    if path.name == ".openjarvis":
        return "~/.openjarvis"
    if path.name == "openjarvis":
        return "<xdg-data-home>/openjarvis"
    return "<openjarvis-home>"


def _truncate(text: str, limit: int = 240) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"
