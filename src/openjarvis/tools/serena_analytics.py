"""Native Serena Analytics Full Operator tools.

Serena Analytics Full Operator v1 foundation:
- status
- env-check
- plan
- source-list
- source-info
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools._stubs import BaseTool, ToolResult, ToolSpec


ANALYTICS_OUTPUT_ROOT = Path("outputs/analytics")


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_slug(value: str) -> str:
    import re
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or "analytics"


def _analytics_root() -> Path:
    ANALYTICS_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for child in ["reports", "snapshots", "exports", "sources", "handoff"]:
        (ANALYTICS_OUTPUT_ROOT / child).mkdir(parents=True, exist_ok=True)
    return ANALYTICS_OUTPUT_ROOT


def _save_json(kind: str, name: str, payload: dict[str, Any]) -> Path:
    root = _analytics_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _hub_adapter_contract() -> dict[str, Any]:
    return {
        "hub_adapter_status": "pending_future_dashboard",
        "future_widgets": [
            "analytics_overview_widget",
            "website_analytics_widget",
            "facebook_page_analytics_widget",
            "google_business_profile_widget",
            "content_performance_widget",
            "marketing_funnel_widget",
            "recommendations_widget",
            "analytics_export_status_widget",
        ],
        "future_events": [
            "analytics_snapshot_created",
            "analytics_report_created",
            "analytics_warning_created",
            "analytics_export_blocked",
            "analytics_source_connected",
            "analytics_audit_completed",
        ],
        "operator_state": [
            "current_business_id",
            "current_analytics_source",
            "current_asset_id",
            "current_date_range",
            "current_metric_set",
            "current_report_path",
            "current_required_approval",
        ],
    }


def _safety_policy() -> dict[str, Any]:
    return {
        "allowed": [
            "Read analytics data.",
            "Summarize analytics data.",
            "Compare periods.",
            "Create local analytics snapshots.",
            "Create reports.",
            "Recommend actions.",
            "Hand off summaries to Reporting, Google Docs, or Google Drive with approval.",
        ],
        "guarded": [
            "Analytics involving patient/client/health/financial data.",
            "Exports of business-sensitive metrics.",
            "Combining analytics with CRM or revenue data.",
            "Public sharing of business analytics.",
        ],
        "blocked": [
            "Exposing access tokens or API secrets.",
            "Modifying campaigns/pages/posts.",
            "Posting content.",
            "Deleting analytics data.",
            "Altering tracking settings.",
            "Unapproved external exports.",
            "Final financial/legal/clinical conclusions.",
        ],
    }


def _analytics_sources() -> dict[str, dict[str, Any]]:
    return {
        "wordpress": {
            "name": "WordPress / WooCommerce / Jetpack",
            "status": "planned",
            "role": "Website, content, traffic, WooCommerce, and post/page performance analytics.",
            "metrics": [
                "page_views",
                "visitors",
                "top_pages",
                "top_posts",
                "referrers",
                "clicks",
                "downloads",
                "countries",
                "woocommerce_orders",
                "woocommerce_revenue",
                "conversion_signals",
            ],
            "required_env": [
                "WORDPRESS_SITE_URL",
                "WORDPRESS_USERNAME",
                "WORDPRESS_APP_PASSWORD",
                "WOOCOMMERCE_CONSUMER_KEY",
                "WOOCOMMERCE_CONSUMER_SECRET",
                "JETPACK_SITE_ID",
            ],
            "notes": [
                "Exact metrics depend on installed WordPress analytics stack.",
                "Jetpack/WordPress.com Stats, WooCommerce, GA4, or plugins may expose different metrics.",
            ],
        },
        "ga4": {
            "name": "Google Analytics 4",
            "status": "planned",
            "role": "Website traffic, events, conversions, acquisition, and campaign analytics.",
            "metrics": [
                "sessions",
                "users",
                "page_views",
                "events",
                "conversions",
                "traffic_source",
                "landing_pages",
                "device_category",
                "country",
            ],
            "required_env": [
                "GOOGLE_CLIENT_ID",
                "GOOGLE_CLIENT_SECRET",
                "GOOGLE_REFRESH_TOKEN",
                "GA4_PROPERTY_ID",
            ],
            "notes": [
                "Requires analytics scope/token later.",
                "Current shared Google token may not include GA4 scope.",
            ],
        },
        "google-business-profile": {
            "name": "Google Business Profile",
            "status": "planned",
            "role": "Business profile visibility, searches, calls, directions, website clicks, and keyword performance.",
            "metrics": [
                "search_impressions",
                "map_impressions",
                "website_clicks",
                "calls",
                "directions",
                "bookings",
                "messages",
                "keyword_impressions",
            ],
            "required_env": [
                "GOOGLE_CLIENT_ID",
                "GOOGLE_CLIENT_SECRET",
                "GOOGLE_REFRESH_TOKEN",
                "GBP_ACCOUNT_ID",
                "GBP_LOCATION_IDS",
            ],
            "notes": [
                "Requires Google Business Profile access and correct API scopes.",
                "May need separate approval/quota access.",
            ],
        },
        "facebook": {
            "name": "Meta / Facebook Pages",
            "status": "planned",
            "role": "Facebook page reach, impressions, engagement, followers, posts, and campaign performance.",
            "metrics": [
                "page_reach",
                "page_impressions",
                "post_reach",
                "post_engagement",
                "followers",
                "link_clicks",
                "messages",
                "leads",
                "ad_metrics_later",
            ],
            "required_env": [
                "META_APP_ID",
                "META_APP_SECRET",
                "META_ACCESS_TOKEN",
                "FACEBOOK_PAGE_IDS",
            ],
            "notes": [
                "Requires Meta app/page permissions and page access token.",
                "Posting/modifying pages is blocked in Analytics v1.",
            ],
        },
        "serena-operator": {
            "name": "Serena Operator Analytics",
            "status": "active_local",
            "role": "Analyze local Serena activity, reports, blocked actions, approvals, and outputs.",
            "metrics": [
                "reports_created",
                "exports_created",
                "handoffs_created",
                "safe_blocks",
                "operator_outputs",
                "approval_requirements",
            ],
            "required_env": [],
            "notes": [
                "Uses local outputs folders.",
                "Available without external API credentials.",
            ],
        },
    }


def _env_status() -> dict[str, Any]:
    sources = _analytics_sources()
    env = {}
    for source_id, source in sources.items():
        required = source.get("required_env", [])
        env[source_id] = {
            "required": [
                {
                    "name": name,
                    "present": bool(os.getenv(name)),
                    "length": len(os.getenv(name, "")),
                }
                for name in required
            ],
            "configured": all(bool(os.getenv(name)) for name in required) if required else True,
        }
    return env


class _AnalyticsBaseTool(BaseTool):
    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=getattr(self, "tool_id", self.__class__.__name__),
            success=success,
            content=content,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_analytics_status")
class SerenaAnalyticsStatusTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show Serena Analytics Full Operator status.",
            parameters={"type": "object", "properties": {}},
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = _analytics_root()
        sources = _analytics_sources()
        env = _env_status()

        active_local = [sid for sid, item in sources.items() if item["status"] == "active_local"]
        configured_external = [sid for sid, item in env.items() if item["configured"] and sources[sid]["required_env"]]

        return self._result(
            "Serena Analytics status\n\n"
            "- Status: active\n"
            "- Role: multi-source analytics, business intelligence, marketing insight, and recommendation operator\n"
            f"- Sources registered: {len(sources)}\n"
            f"- Active local sources: {len(active_local)}\n"
            f"- Configured external sources: {len(configured_external)}\n"
            "- WordPress analytics: planned\n"
            "- Google Analytics 4: planned\n"
            "- Google Business Profile: planned\n"
            "- Meta/Facebook Pages: planned\n"
            "- Serena local operator analytics: active\n"
            "- Posting/modifying campaigns/pages: blocked in Analytics v1\n"
            "- Token/secret exposure: blocked\n"
            "- Secret values exposed: no\n"
            f"- Output root: {root}\n"
            f"- Reports: {root / 'reports'}\n"
            f"- Snapshots: {root / 'snapshots'}\n"
            f"- Exports: {root / 'exports'}\n"
            f"- Sources: {root / 'sources'}\n"
            f"- Handoff: {root / 'handoff'}\n"
            "- Hub adapter: pending future dashboard",
            metadata={
                "sources": sources,
                "env_status": env,
                "safety_policy": _safety_policy(),
                "hub_adapter": _hub_adapter_contract(),
                "secret_values_exposed": False,
            },
        )


@ToolRegistry.register("serena_analytics_env_check")
class SerenaAnalyticsEnvCheckTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_env_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check analytics environment configuration without exposing secrets.",
            parameters={"type": "object", "properties": {}},
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        env = _env_status()
        payload = {
            "report_type": "serena_analytics_env_check",
            "created_at": _timestamp(),
            "env_status": env,
            "changes_made": False,
            "secret_values_exposed": False,
        }
        report_path = _save_json("reports", "env-check", payload)

        lines = [
            "Serena Analytics env check",
            "",
            f"- Report: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "",
            "Sources:",
        ]

        for source_id, item in env.items():
            lines.append(f"- {source_id} | configured={'yes' if item['configured'] else 'no'}")
            for var in item["required"]:
                lines.append(f"  - {var['name']} | present={'yes' if var['present'] else 'no'} | length={var['length']}")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_analytics_source_list")
class SerenaAnalyticsSourceListTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_source_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List registered Serena Analytics sources.",
            parameters={"type": "object", "properties": {}},
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        sources = _analytics_sources()
        payload = {
            "report_type": "serena_analytics_source_list",
            "created_at": _timestamp(),
            "sources": sources,
            "changes_made": False,
            "secret_values_exposed": False,
        }
        report_path = _save_json("sources", "source-list", payload)

        lines = [
            "Serena Analytics source list",
            "",
            f"- Sources registered: {len(sources)}",
            f"- Snapshot: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "",
            "Sources:",
        ]

        for source_id, source in sources.items():
            lines.append(f"- {source_id} | {source['name']} | status={source['status']} | metrics={len(source['metrics'])}")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_analytics_source_info")
class SerenaAnalyticsSourceInfoTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_source_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show details for one analytics source.",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                },
                "required": ["source"],
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        source_id = str(params.get("source") or "").strip()
        sources = _analytics_sources()

        if source_id not in sources:
            return self._result(
                "Serena Analytics source-info failed\n\n"
                f"- Source: {source_id}\n"
                "- Error: source not found\n"
                "- Changes made: no",
                success=False,
            )

        source = sources[source_id]
        env = _env_status().get(source_id, {})
        payload = {
            "report_type": "serena_analytics_source_info",
            "created_at": _timestamp(),
            "source_id": source_id,
            "source": source,
            "env_status": env,
            "changes_made": False,
            "secret_values_exposed": False,
        }
        report_path = _save_json("sources", f"source-info-{source_id}", payload)

        lines = [
            "Serena Analytics source info",
            "",
            f"- Source: {source_id}",
            f"- Name: {source['name']}",
            f"- Status: {source['status']}",
            f"- Role: {source['role']}",
            f"- Metrics: {len(source['metrics'])}",
            f"- Required env vars: {len(source['required_env'])}",
            f"- Snapshot: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "",
            "Metrics:",
        ]

        lines.extend(f"- {metric}" for metric in source["metrics"])

        lines.extend(["", "Required env:"])
        if source["required_env"]:
            for item in env.get("required", []):
                lines.append(f"- {item['name']} | present={'yes' if item['present'] else 'no'} | length={item['length']}")
        else:
            lines.append("- none")

        lines.extend(["", "Notes:"])
        lines.extend(f"- {note}" for note in source["notes"])

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_analytics_plan")
class SerenaAnalyticsPlanTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create an analytics operation plan without calling external APIs.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "source": {"type": "string"},
                    "date_range": {"type": "string"},
                    "business": {"type": "string"},
                },
                "required": ["goal"],
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        goal = str(params.get("goal") or "").strip()
        source = str(params.get("source") or "serena-operator").strip()
        date_range = str(params.get("date_range") or "last 30 days").strip()
        business = str(params.get("business") or "General Business").strip()

        sources = _analytics_sources()
        source_known = source in sources

        plan = {
            "report_type": "serena_analytics_plan",
            "created_at": _timestamp(),
            "goal": goal,
            "source": source,
            "source_known": source_known,
            "date_range": date_range,
            "business": business,
            "safety_policy": _safety_policy(),
            "hub_adapter": _hub_adapter_contract(),
            "steps": [
                "Identify business and analytics source.",
                "Verify source credentials or local source availability.",
                "Define date range and metric set.",
                "Collect or load analytics data.",
                "Create local snapshot.",
                "Compare against previous period where possible.",
                "Identify trends, wins, losses, anomalies, and recommendations.",
                "Create analytics report.",
                "Hand off externally only with approval and compliance review.",
            ],
            "external_api_called": False,
            "snapshot_created": False,
            "changes_made": False,
            "secret_values_exposed": False,
        }
        report_path = _save_json("reports", goal or "analytics-plan", plan)

        return self._result(
            "Serena Analytics operation plan\n\n"
            f"- Goal: {goal}\n"
            f"- Business: {business}\n"
            f"- Source: {source}\n"
            f"- Source known: {'yes' if source_known else 'no'}\n"
            f"- Date range: {date_range}\n"
            f"- Plan: {report_path}\n"
            "- External API called: no\n"
            "- Snapshot created: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in plan["steps"]),
            metadata={**plan, "report_path": str(report_path)},
        )



def _parse_jsonish(text: str) -> Any:
    """Parse strict JSON first, then tolerate common PowerShell/pasted object forms."""
    raw = str(text or "").strip()

    if not raw:
        raise ValueError("empty JSON text")

    try:
        return json.loads(raw)
    except Exception:
        pass

    # Common PowerShell result after quote loss:
    # {page_reach:1200,page_impressions:3400}
    import re
    fixed = raw

    # Quote unquoted object keys after { or ,
    fixed = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_\-]*)(\s*:)', r'\1"\2"\3', fixed)

    # Convert single quotes to double quotes when used as string delimiters
    fixed = fixed.replace("'", '"')

    try:
        return json.loads(fixed)
    except Exception as exc:
        raise ValueError(f"could not parse JSON or relaxed JSON-like text: {exc}") from exc

def _numeric_values_from_obj(obj: Any, prefix: str = "") -> dict[str, float]:
    values: dict[str, float] = {}

    if isinstance(obj, dict):
        for key, value in obj.items():
            next_key = f"{prefix}.{key}" if prefix else str(key)
            values.update(_numeric_values_from_obj(value, next_key))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            next_key = f"{prefix}[{idx}]" if prefix else f"[{idx}]"
            values.update(_numeric_values_from_obj(value, next_key))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        values[prefix or "value"] = float(obj)

    return values


def _summarize_analytics_payload(data: Any, source: str, business: str, date_range: str) -> dict[str, Any]:
    metrics = _numeric_values_from_obj(data)
    top_metrics = sorted(metrics.items(), key=lambda item: abs(item[1]), reverse=True)[:20]

    recommendations = []
    if not metrics:
        recommendations.append("No numeric metrics detected. Add structured metric fields for stronger analysis.")
    else:
        recommendations.append("Review the top metrics and compare against previous period.")
        recommendations.append("Create a Reporting summary if this snapshot should be shared.")
        recommendations.append("Run Compliance before external export if business-sensitive, patient/client, or financial data is present.")

    return {
        "business": business,
        "source": source,
        "date_range": date_range,
        "metric_count": len(metrics),
        "top_metrics": [{"metric": key, "value": value} for key, value in top_metrics],
        "recommendations": recommendations,
    }


def _analytics_report_markdown(title: str, summary: dict[str, Any], raw_source_label: str) -> str:
    lines = [
        f"# {title}",
        "",
        "Created by: Serena Analytics Full Operator v1",
        f"Created at: {_timestamp()}",
        "",
        "## Scope",
        "",
        f"- Business: {summary.get('business')}",
        f"- Source: {summary.get('source')}",
        f"- Date range: {summary.get('date_range')}",
        f"- Source evidence: {raw_source_label}",
        "",
        "## Metric Summary",
        "",
        f"- Numeric metrics detected: {summary.get('metric_count')}",
        "",
        "## Top Metrics",
        "",
    ]

    top_metrics = summary.get("top_metrics") or []
    if top_metrics:
        for item in top_metrics:
            lines.append(f"- {item['metric']}: {item['value']}")
    else:
        lines.append("- No numeric metrics detected.")

    lines.extend([
        "",
        "## Recommendations",
        "",
    ])

    for rec in summary.get("recommendations") or []:
        lines.append(f"- {rec}")

    lines.extend([
        "",
        "## Safety",
        "",
        "- Analytics snapshot generated locally.",
        "- External API was not called unless explicitly stated in metadata.",
        "- Tokens/secrets were not exposed.",
        "- External export should require approval and Compliance review.",
        "",
    ])

    return "\n".join(lines)


def _save_analytics_snapshot(
    title: str,
    data: Any,
    source: str,
    business: str,
    date_range: str,
    raw_source_label: str,
    report_name: str,
) -> ToolResult:
    summary = _summarize_analytics_payload(data, source=source, business=business, date_range=date_range)
    markdown = _analytics_report_markdown(title, summary, raw_source_label=raw_source_label)

    snapshot_payload = {
        "report_type": "serena_analytics_snapshot",
        "created_at": _timestamp(),
        "title": title,
        "business": business,
        "source": source,
        "date_range": date_range,
        "summary": summary,
        "raw_data": data,
        "raw_source_label": raw_source_label,
        "external_api_called": False,
        "snapshot_created": True,
        "report_created": True,
        "export_performed": False,
        "delete_performed": False,
        "changes_made": True,
        "secret_values_exposed": False,
        "hub_adapter": _hub_adapter_contract(),
    }

    snapshot_path = _save_json("snapshots", report_name, snapshot_payload)

    report_path = ANALYTICS_OUTPUT_ROOT / "reports" / f"{_timestamp()}-{_safe_slug(report_name)}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(markdown, encoding="utf-8")

    metadata = {
        **snapshot_payload,
        "snapshot_path": str(snapshot_path),
        "report_path": str(report_path),
    }

    return ToolResult(
        tool_name=f"serena_analytics_{report_name}",
        success=True,
        content=(
            f"{title} created\n\n"
            f"- Business: {business}\n"
            f"- Source: {source}\n"
            f"- Date range: {date_range}\n"
            f"- Metrics detected: {summary['metric_count']}\n"
            f"- Snapshot: {snapshot_path}\n"
            f"- Report: {report_path}\n"
            "- External API called: no\n"
            "- Snapshot created: yes\n"
            "- Report created: yes\n"
            "- Export performed: no\n"
            "- Delete performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard"
        ),
        metadata=metadata,
    )


def _read_json_file(path_value: str) -> tuple[Path, Any]:
    path = Path(path_value)
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"JSON file not found: {path}")
    text = path.read_text(encoding="utf-8", errors="ignore")
    return path, json.loads(text)


@ToolRegistry.register("serena_analytics_from_json")
class SerenaAnalyticsFromJsonTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_from_json"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local analytics snapshot/report from JSON text.",
            parameters={
                "type": "object",
                "properties": {
                    "json_text": {"type": "string"},
                    "title": {"type": "string"},
                    "source": {"type": "string"},
                    "business": {"type": "string"},
                    "date_range": {"type": "string"},
                },
                "required": ["json_text"],
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        json_text = str(params.get("json_text") or "")
        title = str(params.get("title") or "Serena Analytics JSON Snapshot").strip()
        source = str(params.get("source") or "provided-json").strip()
        business = str(params.get("business") or "General Business").strip()
        date_range = str(params.get("date_range") or "unspecified").strip()

        try:
            data = _parse_jsonish(json_text)
            return _save_analytics_snapshot(title, data, source, business, date_range, "provided JSON text", f"from-json-{title}")
        except Exception as exc:
            return self._result(
                "Serena Analytics from-json failed\n\n"
                f"- Error: {exc}\n"
                "- Snapshot created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )


@ToolRegistry.register("serena_analytics_from_file")
class SerenaAnalyticsFromFileTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_from_file"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local analytics snapshot/report from a JSON file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "title": {"type": "string"},
                    "source": {"type": "string"},
                    "business": {"type": "string"},
                    "date_range": {"type": "string"},
                },
                "required": ["path"],
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        path_value = str(params.get("path") or "").strip()
        title = str(params.get("title") or "Serena Analytics File Snapshot").strip()
        source = str(params.get("source") or "file").strip()
        business = str(params.get("business") or "General Business").strip()
        date_range = str(params.get("date_range") or "unspecified").strip()

        try:
            path, data = _read_json_file(path_value)
            return _save_analytics_snapshot(title, data, source, business, date_range, str(path), f"from-file-{path.stem}")
        except Exception as exc:
            return self._result(
                "Serena Analytics from-file failed\n\n"
                f"- Path: {path_value}\n"
                f"- Error: {exc}\n"
                "- Snapshot created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )


@ToolRegistry.register("serena_analytics_from_folder")
class SerenaAnalyticsFromFolderTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_from_folder"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a combined analytics snapshot/report from recent JSON files in a folder.",
            parameters={
                "type": "object",
                "properties": {
                    "folder": {"type": "string"},
                    "title": {"type": "string"},
                    "source": {"type": "string"},
                    "business": {"type": "string"},
                    "date_range": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["folder"],
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        folder_value = str(params.get("folder") or "").strip()
        title = str(params.get("title") or "Serena Analytics Folder Snapshot").strip()
        source = str(params.get("source") or "folder").strip()
        business = str(params.get("business") or "General Business").strip()
        date_range = str(params.get("date_range") or "unspecified").strip()
        limit = int(params.get("limit") or 10)

        try:
            folder = Path(folder_value)
            if not folder.exists() or not folder.is_dir():
                raise RuntimeError(f"Folder not found or not directory: {folder}")

            files = sorted(
                [path for path in folder.rglob("*.json") if path.is_file()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:limit]

            combined = {"folder": str(folder), "files": []}
            for path in files:
                try:
                    combined["files"].append({
                        "path": str(path),
                        "data": json.loads(path.read_text(encoding="utf-8", errors="ignore")),
                    })
                except Exception as exc:
                    combined["files"].append({"path": str(path), "error": str(exc)})

            return _save_analytics_snapshot(title, combined, source, business, date_range, str(folder), f"from-folder-{folder.name}")
        except Exception as exc:
            return self._result(
                "Serena Analytics from-folder failed\n\n"
                f"- Folder: {folder_value}\n"
                f"- Error: {exc}\n"
                "- Snapshot created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )


@ToolRegistry.register("serena_analytics_snapshot")
class SerenaAnalyticsSnapshotTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_snapshot"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local Serena operator analytics snapshot from local outputs.",
            parameters={
                "type": "object",
                "properties": {
                    "business": {"type": "string"},
                    "date_range": {"type": "string"},
                },
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        business = str(params.get("business") or "Serena Local Operator").strip()
        date_range = str(params.get("date_range") or "current local outputs").strip()

        root = Path("outputs")
        counts: dict[str, int] = {}
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file():
                    parts = path.parts
                    key = parts[1] if len(parts) > 1 else "root"
                    counts[key] = counts.get(key, 0) + 1

        data = {
            "business": business,
            "date_range": date_range,
            "output_file_counts": counts,
            "total_output_files": sum(counts.values()),
            "available_operators": sorted(counts.keys()),
        }

        return _save_analytics_snapshot(
            "Serena Local Operator Analytics Snapshot",
            data,
            "serena-operator",
            business,
            date_range,
            "outputs folder",
            "operator-snapshot",
        )


@ToolRegistry.register("serena_analytics_compare")
class SerenaAnalyticsCompareTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_compare"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Compare two analytics JSON payloads or snapshot files.",
            parameters={
                "type": "object",
                "properties": {
                    "current_json": {"type": "string"},
                    "previous_json": {"type": "string"},
                    "current_file": {"type": "string"},
                    "previous_file": {"type": "string"},
                    "title": {"type": "string"},
                    "business": {"type": "string"},
                    "source": {"type": "string"},
                },
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        title = str(params.get("title") or "Serena Analytics Comparison").strip()
        business = str(params.get("business") or "General Business").strip()
        source = str(params.get("source") or "comparison").strip()

        try:
            if params.get("current_file"):
                current_path, current_data = _read_json_file(str(params.get("current_file")))
                current_label = str(current_path)
            else:
                current_data = _parse_jsonish(str(params.get("current_json") or "{}"))
                current_label = "current JSON text"

            if params.get("previous_file"):
                previous_path, previous_data = _read_json_file(str(params.get("previous_file")))
                previous_label = str(previous_path)
            else:
                previous_data = _parse_jsonish(str(params.get("previous_json") or "{}"))
                previous_label = "previous JSON text"

            current_metrics = _numeric_values_from_obj(current_data)
            previous_metrics = _numeric_values_from_obj(previous_data)

            comparisons = []
            for metric, current_value in sorted(current_metrics.items()):
                if metric in previous_metrics:
                    prev = previous_metrics[metric]
                    change = current_value - prev
                    pct = None if prev == 0 else (change / prev) * 100
                    comparisons.append({
                        "metric": metric,
                        "current": current_value,
                        "previous": prev,
                        "change": change,
                        "percent_change": pct,
                    })

            comparisons = sorted(comparisons, key=lambda item: abs(item["change"]), reverse=True)[:50]

            data = {
                "current_label": current_label,
                "previous_label": previous_label,
                "matched_metric_count": len(comparisons),
                "comparisons": comparisons,
            }

            return _save_analytics_snapshot(title, data, source, business, "comparison", f"{previous_label} -> {current_label}", f"compare-{title}")
        except Exception as exc:
            return self._result(
                "Serena Analytics compare failed\n\n"
                f"- Error: {exc}\n"
                "- Snapshot created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )


def _source_plan_response(
    title: str,
    source_id: str,
    business: str,
    date_range: str,
    goal: str,
    extra_steps: list[str] | None = None,
) -> ToolResult:
    sources = _analytics_sources()
    source = sources.get(source_id, {})
    env = _env_status().get(source_id, {})
    configured = bool(env.get("configured"))

    steps = [
        f"Confirm the business context: {business}.",
        f"Confirm the date range: {date_range}.",
        f"Check {source.get('name', source_id)} credentials without exposing secrets.",
        "Identify available metrics and missing credentials.",
        "Collect source data only when credentials and permissions are ready.",
        "Create a local analytics snapshot.",
        "Compare against previous period when possible.",
        "Create recommendations and hand off to Reporting/Docs/Drive only with approval.",
    ]

    if extra_steps:
        steps.extend(extra_steps)

    plan = {
        "report_type": f"serena_analytics_{source_id}_plan",
        "created_at": _timestamp(),
        "title": title,
        "source_id": source_id,
        "source": source,
        "business": business,
        "date_range": date_range,
        "goal": goal,
        "configured": configured,
        "env_status": env,
        "steps": steps,
        "external_api_called": False,
        "snapshot_created": False,
        "changes_made": False,
        "secret_values_exposed": False,
        "hub_adapter": _hub_adapter_contract(),
    }
    report_path = _save_json("reports", f"{source_id}-plan-{business}", plan)

    lines = [
        title,
        "",
        f"- Business: {business}",
        f"- Source: {source_id}",
        f"- Source name: {source.get('name', source_id)}",
        f"- Date range: {date_range}",
        f"- Configured: {'yes' if configured else 'no'}",
        f"- Plan: {report_path}",
        "- External API called: no",
        "- Snapshot created: no",
        "- Changes made: no",
        "- Secret values exposed: no",
        "- Hub adapter: pending future dashboard",
        "",
        "Required environment:",
    ]

    required = env.get("required", [])
    if required:
        for item in required:
            lines.append(f"- {item['name']} | present={'yes' if item['present'] else 'no'} | length={item['length']}")
    else:
        lines.append("- none")

    lines.extend(["", "Metric targets:"])
    for metric in source.get("metrics", []):
        lines.append(f"- {metric}")

    lines.extend(["", "Steps:"])
    for step in steps:
        lines.append(f"- {step}")

    return ToolResult(
        tool_name=f"serena_analytics_{source_id}_plan",
        success=True,
        content="\n".join(lines),
        metadata={**plan, "report_path": str(report_path)},
    )


def _website_summary_data(
    business: str,
    date_range: str,
    source: str,
    metrics: dict[str, Any],
    notes: str = "",
) -> dict[str, Any]:
    return {
        "business": business,
        "date_range": date_range,
        "source": source,
        "metrics": metrics,
        "notes": notes,
        "analysis_focus": [
            "traffic",
            "content performance",
            "engagement",
            "conversion signals",
            "revenue signals",
            "recommendations",
        ],
    }


@ToolRegistry.register("serena_analytics_wordpress_plan")
class SerenaAnalyticsWordpressPlanTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_wordpress_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a WordPress/WooCommerce/Jetpack analytics collection plan without external API calls.",
            parameters={
                "type": "object",
                "properties": {
                    "business": {"type": "string"},
                    "date_range": {"type": "string"},
                    "goal": {"type": "string"},
                },
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        business = str(params.get("business") or "General Business").strip()
        date_range = str(params.get("date_range") or "last 30 days").strip()
        goal = str(params.get("goal") or "Analyze WordPress website performance.").strip()
        return _source_plan_response(
            "Serena WordPress analytics plan",
            "wordpress",
            business,
            date_range,
            goal,
            [
                "Check whether WordPress uses Jetpack Stats, GA4, WooCommerce, or another analytics plugin.",
                "Collect top pages/posts, referrers, clicks, downloads, countries, and WooCommerce revenue if available.",
                "Connect content performance to future WordPress/content strategy.",
            ],
        )


@ToolRegistry.register("serena_analytics_wordpress_summary")
class SerenaAnalyticsWordpressSummaryTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_wordpress_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a WordPress analytics summary from provided or pasted metrics.",
            parameters={
                "type": "object",
                "properties": {
                    "metrics": {"type": "string"},
                    "business": {"type": "string"},
                    "date_range": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["metrics"],
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        metrics_text = str(params.get("metrics") or "")
        business = str(params.get("business") or "General Business").strip()
        date_range = str(params.get("date_range") or "unspecified").strip()
        notes = str(params.get("notes") or "").strip()

        try:
            metrics = _parse_jsonish(metrics_text)
            data = _website_summary_data(business, date_range, "wordpress", metrics, notes)
            return _save_analytics_snapshot(
                "Serena WordPress Analytics Summary",
                data,
                "wordpress",
                business,
                date_range,
                "provided WordPress/WooCommerce/Jetpack metrics",
                "wordpress-summary",
            )
        except Exception as exc:
            return self._result(
                "Serena WordPress analytics summary failed\n\n"
                f"- Error: {exc}\n"
                "- Snapshot created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )


@ToolRegistry.register("serena_analytics_ga4_plan")
class SerenaAnalyticsGA4PlanTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_ga4_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a GA4 analytics collection plan without external API calls.",
            parameters={
                "type": "object",
                "properties": {
                    "business": {"type": "string"},
                    "date_range": {"type": "string"},
                    "goal": {"type": "string"},
                },
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        business = str(params.get("business") or "General Business").strip()
        date_range = str(params.get("date_range") or "last 30 days").strip()
        goal = str(params.get("goal") or "Analyze GA4 website performance.").strip()
        return _source_plan_response(
            "Serena GA4 analytics plan",
            "ga4",
            business,
            date_range,
            goal,
            [
                "Confirm GA4 property ID and Google token scopes.",
                "Collect sessions, users, page views, events, conversions, acquisition source, landing pages, countries, and devices.",
                "Compare against the previous period and identify conversion bottlenecks.",
            ],
        )


@ToolRegistry.register("serena_analytics_website_summary")
class SerenaAnalyticsWebsiteSummaryTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_website_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a combined website analytics summary from pasted WordPress/GA4/website metrics.",
            parameters={
                "type": "object",
                "properties": {
                    "metrics": {"type": "string"},
                    "business": {"type": "string"},
                    "date_range": {"type": "string"},
                    "source": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["metrics"],
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        metrics_text = str(params.get("metrics") or "")
        business = str(params.get("business") or "General Business").strip()
        date_range = str(params.get("date_range") or "unspecified").strip()
        source = str(params.get("source") or "website").strip()
        notes = str(params.get("notes") or "").strip()

        try:
            metrics = _parse_jsonish(metrics_text)
            data = _website_summary_data(business, date_range, source, metrics, notes)
            return _save_analytics_snapshot(
                "Serena Website Analytics Summary",
                data,
                source,
                business,
                date_range,
                "provided website analytics metrics",
                "website-summary",
            )
        except Exception as exc:
            return self._result(
                "Serena website analytics summary failed\n\n"
                f"- Error: {exc}\n"
                "- Snapshot created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )


@ToolRegistry.register("serena_analytics_gbp_env_check")
class SerenaAnalyticsGBPEnvCheckTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_gbp_env_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check Google Business Profile analytics environment without exposing secrets.",
            parameters={"type": "object", "properties": {}},
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        env = _env_status().get("google-business-profile", {})
        required = env.get("required", [])
        configured = bool(env.get("configured"))

        payload = {
            "report_type": "serena_analytics_gbp_env_check",
            "created_at": _timestamp(),
            "source": "google-business-profile",
            "configured": configured,
            "env_status": env,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", "gbp-env-check", payload)

        lines = [
            "Serena Google Business Profile analytics env check",
            "",
            f"- Configured: {'yes' if configured else 'no'}",
            f"- Report: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Required environment:",
        ]

        for item in required:
            lines.append(f"- {item['name']} | present={'yes' if item['present'] else 'no'} | length={item['length']}")

        lines.extend([
            "",
            "Notes:",
            "- GOOGLE_REFRESH_TOKEN is now present, but GBP_ACCOUNT_ID and GBP_LOCATION_IDS are still needed before live GBP analytics can run.",
            "- Google Business Profile API access/permissions may still require account-level access and API quota approval.",
            "- Analytics v1 does not modify business profiles.",
        ])

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_analytics_gbp_plan")
class SerenaAnalyticsGBPPlanTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_gbp_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Google Business Profile analytics collection plan without external API calls.",
            parameters={
                "type": "object",
                "properties": {
                    "business": {"type": "string"},
                    "date_range": {"type": "string"},
                    "goal": {"type": "string"},
                },
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        business = str(params.get("business") or "General Business").strip()
        date_range = str(params.get("date_range") or "last 30 days").strip()
        goal = str(params.get("goal") or "Analyze Google Business Profile performance.").strip()

        return _source_plan_response(
            "Serena Google Business Profile analytics plan",
            "google-business-profile",
            business,
            date_range,
            goal,
            [
                "Confirm the correct Google Business Profile account ID.",
                "Confirm one or more location IDs for the business profiles Serena must manage.",
                "Collect search impressions, map impressions, website clicks, calls, directions, messages, bookings, and keyword impressions when available.",
                "Compare location performance if multiple profiles exist.",
                "Connect GBP results to website, Facebook, calendar bookings, and future CRM leads.",
            ],
        )


@ToolRegistry.register("serena_analytics_gbp_summary")
class SerenaAnalyticsGBPSummaryTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_gbp_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Google Business Profile analytics summary from provided metrics.",
            parameters={
                "type": "object",
                "properties": {
                    "metrics": {"type": "string"},
                    "business": {"type": "string"},
                    "date_range": {"type": "string"},
                    "location": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["metrics"],
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        metrics_text = str(params.get("metrics") or "")
        business = str(params.get("business") or "General Business").strip()
        date_range = str(params.get("date_range") or "unspecified").strip()
        location = str(params.get("location") or "primary location").strip()
        notes = str(params.get("notes") or "").strip()

        try:
            metrics = _parse_jsonish(metrics_text)
            data = {
                "business": business,
                "date_range": date_range,
                "source": "google-business-profile",
                "location": location,
                "metrics": metrics,
                "notes": notes,
                "analysis_focus": [
                    "search visibility",
                    "map visibility",
                    "calls",
                    "website clicks",
                    "directions",
                    "messages",
                    "bookings",
                    "keyword demand",
                    "local conversion signals",
                ],
            }
            return _save_analytics_snapshot(
                "Serena Google Business Profile Analytics Summary",
                data,
                "google-business-profile",
                business,
                date_range,
                "provided GBP metrics",
                "gbp-summary",
            )
        except Exception as exc:
            return self._result(
                "Serena Google Business Profile analytics summary failed\n\n"
                f"- Error: {exc}\n"
                "- Snapshot created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )


@ToolRegistry.register("serena_analytics_gbp_keywords")
class SerenaAnalyticsGBPKeywordsTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_gbp_keywords"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Analyze Google Business Profile keyword/search-term performance from provided metrics.",
            parameters={
                "type": "object",
                "properties": {
                    "keywords": {"type": "string"},
                    "business": {"type": "string"},
                    "date_range": {"type": "string"},
                    "location": {"type": "string"},
                },
                "required": ["keywords"],
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        keyword_text = str(params.get("keywords") or "")
        business = str(params.get("business") or "General Business").strip()
        date_range = str(params.get("date_range") or "unspecified").strip()
        location = str(params.get("location") or "primary location").strip()

        try:
            keywords = _parse_jsonish(keyword_text)
            data = {
                "business": business,
                "date_range": date_range,
                "source": "google-business-profile-keywords",
                "location": location,
                "keywords": keywords,
                "analysis_focus": [
                    "highest impression search terms",
                    "local intent",
                    "content opportunities",
                    "service page opportunities",
                    "Google Business Profile post ideas",
                    "website SEO alignment",
                ],
            }
            return _save_analytics_snapshot(
                "Serena Google Business Profile Keyword Analytics",
                data,
                "google-business-profile-keywords",
                business,
                date_range,
                "provided GBP keyword metrics",
                "gbp-keywords",
            )
        except Exception as exc:
            return self._result(
                "Serena Google Business Profile keyword analytics failed\n\n"
                f"- Error: {exc}\n"
                "- Snapshot created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )


@ToolRegistry.register("serena_analytics_meta_env_check")
class SerenaAnalyticsMetaEnvCheckTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_meta_env_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check Meta/Facebook analytics environment without exposing secrets.",
            parameters={"type": "object", "properties": {}},
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        env = _env_status().get("facebook", {})
        required = env.get("required", [])
        configured = bool(env.get("configured"))

        payload = {
            "report_type": "serena_analytics_meta_env_check",
            "created_at": _timestamp(),
            "source": "facebook",
            "configured": configured,
            "env_status": env,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", "meta-env-check", payload)

        lines = [
            "Serena Meta/Facebook analytics env check",
            "",
            f"- Configured: {'yes' if configured else 'no'}",
            f"- Report: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Required environment:",
        ]

        for item in required:
            lines.append(f"- {item['name']} | present={'yes' if item['present'] else 'no'} | length={item['length']}")

        lines.extend([
            "",
            "Notes:",
            "- META_ACCESS_TOKEN and FACEBOOK_PAGE_IDS are required before live Facebook Page analytics can run.",
            "- Meta app/page permissions and page access token are required.",
            "- Analytics v1 reads/analyzes only. Posting, editing, campaign changes, and page modifications are blocked.",
        ])

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_analytics_facebook_pages")
class SerenaAnalyticsFacebookPagesTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_facebook_pages"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show configured Facebook Page IDs and readiness without calling Meta APIs.",
            parameters={"type": "object", "properties": {}},
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        page_ids_raw = os.getenv("FACEBOOK_PAGE_IDS", "").strip()
        page_ids = [item.strip() for item in page_ids_raw.split(",") if item.strip()]
        env = _env_status().get("facebook", {})

        payload = {
            "report_type": "serena_analytics_facebook_pages",
            "created_at": _timestamp(),
            "configured": bool(env.get("configured")),
            "page_count": len(page_ids),
            "page_id_lengths": [len(item) for item in page_ids],
            "external_api_called": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("sources", "facebook-pages", payload)

        lines = [
            "Serena Facebook Pages analytics readiness",
            "",
            f"- Configured: {'yes' if env.get('configured') else 'no'}",
            f"- Page IDs configured: {len(page_ids)}",
            f"- Snapshot: {report_path}",
            "- External API called: no",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Pages:",
        ]

        if page_ids:
            for index, page_id in enumerate(page_ids, start=1):
                lines.append(f"- page {index} | id length={len(page_id)}")
        else:
            lines.append("- none configured")

        lines.extend([
            "",
            "Next setup:",
            "- Add META_APP_ID, META_APP_SECRET, META_ACCESS_TOKEN, and FACEBOOK_PAGE_IDS.",
            "- Use page IDs only in reports; do not expose page access tokens.",
        ])

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_analytics_facebook_page_summary")
class SerenaAnalyticsFacebookPageSummaryTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_facebook_page_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create Facebook Page analytics summary from provided metrics.",
            parameters={
                "type": "object",
                "properties": {
                    "metrics": {"type": "string"},
                    "business": {"type": "string"},
                    "date_range": {"type": "string"},
                    "page": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["metrics"],
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        metrics_text = str(params.get("metrics") or "")
        business = str(params.get("business") or "General Business").strip()
        date_range = str(params.get("date_range") or "unspecified").strip()
        page = str(params.get("page") or "facebook page").strip()
        notes = str(params.get("notes") or "").strip()

        try:
            metrics = _parse_jsonish(metrics_text)
            data = {
                "business": business,
                "date_range": date_range,
                "source": "facebook-page",
                "page": page,
                "metrics": metrics,
                "notes": notes,
                "analysis_focus": [
                    "reach",
                    "impressions",
                    "post engagement",
                    "followers",
                    "link clicks",
                    "messages",
                    "leads",
                    "content performance",
                    "audience response",
                ],
            }
            return _save_analytics_snapshot(
                "Serena Facebook Page Analytics Summary",
                data,
                "facebook",
                business,
                date_range,
                "provided Facebook Page metrics",
                "facebook-page-summary",
            )
        except Exception as exc:
            return self._result(
                "Serena Facebook Page analytics summary failed\n\n"
                f"- Error: {exc}\n"
                "- Snapshot created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )


@ToolRegistry.register("serena_analytics_social_summary")
class SerenaAnalyticsSocialSummaryTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_social_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a combined social analytics summary from provided metrics.",
            parameters={
                "type": "object",
                "properties": {
                    "metrics": {"type": "string"},
                    "business": {"type": "string"},
                    "date_range": {"type": "string"},
                    "source": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["metrics"],
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        metrics_text = str(params.get("metrics") or "")
        business = str(params.get("business") or "General Business").strip()
        date_range = str(params.get("date_range") or "unspecified").strip()
        source = str(params.get("source") or "social").strip()
        notes = str(params.get("notes") or "").strip()

        try:
            metrics = _parse_jsonish(metrics_text)
            data = {
                "business": business,
                "date_range": date_range,
                "source": source,
                "metrics": metrics,
                "notes": notes,
                "analysis_focus": [
                    "cross-channel reach",
                    "impressions",
                    "engagement",
                    "audience growth",
                    "clicks",
                    "messages",
                    "lead signals",
                    "best-performing content",
                    "next content actions",
                ],
            }
            return _save_analytics_snapshot(
                "Serena Social Analytics Summary",
                data,
                source,
                business,
                date_range,
                "provided social metrics",
                "social-summary",
            )
        except Exception as exc:
            return self._result(
                "Serena social analytics summary failed\n\n"
                f"- Error: {exc}\n"
                "- Snapshot created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )


def _analytics_insight_payload(
    kind: str,
    business: str,
    date_range: str,
    metrics_text: str,
    source: str,
    notes: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics = _parse_jsonish(metrics_text)
    numeric = _numeric_values_from_obj(metrics)

    top_metrics = sorted(numeric.items(), key=lambda item: abs(item[1]), reverse=True)[:15]

    wins = []
    risks = []
    opportunities = []
    next_actions = []

    lower_source = source.lower()

    if numeric:
        opportunities.append("Compare these metrics against the previous period to confirm growth or decline.")
        next_actions.append("Create a Reporting summary if this insight should be shared with Kyle or Dr Piet.")
    else:
        risks.append("No numeric metrics detected, so trend analysis is limited.")

    metric_keys = " ".join(numeric.keys()).lower()

    if any(term in metric_keys for term in ["lead", "booking", "call", "message", "conversion"]):
        wins.append("Lead or conversion signals are present.")
        next_actions.append("Connect these metrics to Calendar/CRM once Serena Hub is available.")

    if any(term in metric_keys for term in ["reach", "impression", "views", "sessions", "users", "traffic"]):
        opportunities.append("Traffic and visibility signals are present; evaluate which channels convert best.")

    if any(term in metric_keys for term in ["click", "website_click", "link_click"]):
        opportunities.append("Click metrics are present; review landing pages and calls-to-action.")

    if any(term in metric_keys for term in ["revenue", "orders", "sales"]):
        opportunities.append("Revenue/order metrics are present; finance/accounting linkage should be added later.")
        risks.append("Revenue metrics are business-sensitive and should be guarded before external export.")

    if "facebook" in lower_source or "social" in lower_source:
        next_actions.append("Identify best-performing posts and create future content ideas from them.")

    if "gbp" in lower_source or "business-profile" in lower_source or "google-business" in lower_source:
        next_actions.append("Use high-intent GBP keywords to guide service-page SEO and Google Business posts.")

    if "website" in lower_source or "wordpress" in lower_source or "ga4" in lower_source:
        next_actions.append("Review landing pages, referral sources, and booking/call-to-action flow.")

    if not wins:
        wins.append("Snapshot created successfully for analysis.")
    if not risks:
        risks.append("No immediate analytics risk detected from provided metrics.")
    if not opportunities:
        opportunities.append("Add more structured metrics for stronger insight generation.")
    if not next_actions:
        next_actions.append("Collect more source data and compare against previous period.")

    summary = {
        "kind": kind,
        "business": business,
        "date_range": date_range,
        "source": source,
        "notes": notes,
        "metric_count": len(numeric),
        "top_metrics": [{"metric": key, "value": value} for key, value in top_metrics],
        "wins": wins,
        "risks": risks,
        "opportunities": opportunities,
        "next_actions": next_actions,
    }

    data = {
        "business": business,
        "date_range": date_range,
        "source": source,
        "kind": kind,
        "metrics": metrics,
        "summary": summary,
        "analysis_focus": [
            "wins",
            "risks",
            "opportunities",
            "next actions",
            "business impact",
            "future Serena Hub integration",
        ],
    }

    return data, summary


@ToolRegistry.register("serena_analytics_business_overview")
class SerenaAnalyticsBusinessOverviewTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_business_overview"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a business analytics overview from multi-source metrics.",
            parameters={
                "type": "object",
                "properties": {
                    "metrics": {"type": "string"},
                    "business": {"type": "string"},
                    "date_range": {"type": "string"},
                    "source": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["metrics"],
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            data, _summary = _analytics_insight_payload(
                kind="business-overview",
                business=str(params.get("business") or "General Business").strip(),
                date_range=str(params.get("date_range") or "unspecified").strip(),
                metrics_text=str(params.get("metrics") or ""),
                source=str(params.get("source") or "multi-source").strip(),
                notes=str(params.get("notes") or "").strip(),
            )
            return _save_analytics_snapshot(
                "Serena Business Analytics Overview",
                data,
                data["source"],
                data["business"],
                data["date_range"],
                "provided business analytics metrics",
                "business-overview",
            )
        except Exception as exc:
            return self._result(
                "Serena business analytics overview failed\n\n"
                f"- Error: {exc}\n"
                "- Snapshot created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )


@ToolRegistry.register("serena_analytics_marketing_funnel")
class SerenaAnalyticsMarketingFunnelTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_marketing_funnel"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Analyze marketing funnel metrics from awareness to leads/bookings/revenue.",
            parameters={
                "type": "object",
                "properties": {
                    "metrics": {"type": "string"},
                    "business": {"type": "string"},
                    "date_range": {"type": "string"},
                    "source": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["metrics"],
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            metrics_text = str(params.get("metrics") or "")
            business = str(params.get("business") or "General Business").strip()
            date_range = str(params.get("date_range") or "unspecified").strip()
            source = str(params.get("source") or "marketing-funnel").strip()
            notes = str(params.get("notes") or "").strip()

            metrics = _parse_jsonish(metrics_text)
            numeric = _numeric_values_from_obj(metrics)

            funnel = {
                "awareness": {
                    "terms": ["reach", "impressions", "views", "sessions", "users"],
                    "metrics": {},
                },
                "engagement": {
                    "terms": ["engagement", "clicks", "link_clicks", "website_clicks"],
                    "metrics": {},
                },
                "lead_capture": {
                    "terms": ["leads", "messages", "calls", "form", "booking_clicks"],
                    "metrics": {},
                },
                "conversion": {
                    "terms": ["bookings", "orders", "sales", "revenue", "conversions"],
                    "metrics": {},
                },
            }

            for metric, value in numeric.items():
                lower = metric.lower()
                for stage, stage_info in funnel.items():
                    if any(term in lower for term in stage_info["terms"]):
                        stage_info["metrics"][metric] = value

            data = {
                "business": business,
                "date_range": date_range,
                "source": source,
                "metrics": metrics,
                "funnel": funnel,
                "notes": notes,
                "analysis_focus": [
                    "awareness",
                    "engagement",
                    "lead capture",
                    "conversion",
                    "bottlenecks",
                    "next actions",
                ],
            }

            return _save_analytics_snapshot(
                "Serena Marketing Funnel Analytics",
                data,
                source,
                business,
                date_range,
                "provided marketing funnel metrics",
                "marketing-funnel",
            )
        except Exception as exc:
            return self._result(
                "Serena marketing funnel analytics failed\n\n"
                f"- Error: {exc}\n"
                "- Snapshot created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )


@ToolRegistry.register("serena_analytics_content_performance")
class SerenaAnalyticsContentPerformanceTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_content_performance"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Analyze content performance metrics from posts/pages/social/website data.",
            parameters={
                "type": "object",
                "properties": {
                    "metrics": {"type": "string"},
                    "business": {"type": "string"},
                    "date_range": {"type": "string"},
                    "source": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["metrics"],
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            metrics = _parse_jsonish(str(params.get("metrics") or ""))
            business = str(params.get("business") or "General Business").strip()
            date_range = str(params.get("date_range") or "unspecified").strip()
            source = str(params.get("source") or "content").strip()
            notes = str(params.get("notes") or "").strip()

            data = {
                "business": business,
                "date_range": date_range,
                "source": source,
                "metrics": metrics,
                "notes": notes,
                "analysis_focus": [
                    "top content",
                    "weak content",
                    "engagement",
                    "click-through",
                    "lead generation",
                    "repurposing opportunities",
                    "next content ideas",
                ],
            }

            return _save_analytics_snapshot(
                "Serena Content Performance Analytics",
                data,
                source,
                business,
                date_range,
                "provided content performance metrics",
                "content-performance",
            )
        except Exception as exc:
            return self._result(
                "Serena content performance analytics failed\n\n"
                f"- Error: {exc}\n"
                "- Snapshot created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )


@ToolRegistry.register("serena_analytics_recommendations")
class SerenaAnalyticsRecommendationsTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_recommendations"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create analytics recommendations from provided metrics.",
            parameters={
                "type": "object",
                "properties": {
                    "metrics": {"type": "string"},
                    "business": {"type": "string"},
                    "date_range": {"type": "string"},
                    "source": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["metrics"],
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            data, summary = _analytics_insight_payload(
                kind="recommendations",
                business=str(params.get("business") or "General Business").strip(),
                date_range=str(params.get("date_range") or "unspecified").strip(),
                metrics_text=str(params.get("metrics") or ""),
                source=str(params.get("source") or "multi-source").strip(),
                notes=str(params.get("notes") or "").strip(),
            )

            data["recommendation_summary"] = {
                "wins": summary["wins"],
                "risks": summary["risks"],
                "opportunities": summary["opportunities"],
                "next_actions": summary["next_actions"],
            }

            return _save_analytics_snapshot(
                "Serena Analytics Recommendations",
                data,
                data["source"],
                data["business"],
                data["date_range"],
                "provided analytics metrics",
                "recommendations",
            )
        except Exception as exc:
            return self._result(
                "Serena analytics recommendations failed\n\n"
                f"- Error: {exc}\n"
                "- Snapshot created: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )


@ToolRegistry.register("serena_analytics_audit")
class SerenaAnalyticsAuditTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_audit"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Audit Serena Analytics outputs, sources, env readiness, and safety posture.",
            parameters={"type": "object", "properties": {}},
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = _analytics_root()
        sources = _analytics_sources()
        env = _env_status()
        safety = _safety_policy()
        hub = _hub_adapter_contract()

        counts = {}
        for folder_name in ["reports", "snapshots", "exports", "sources", "handoff"]:
            folder = root / folder_name
            counts[folder_name] = len([p for p in folder.glob("*") if p.is_file()]) if folder.exists() else 0

        configured = [source_id for source_id, item in env.items() if item.get("configured")]
        external_configured = [
            source_id for source_id in configured
            if source_id != "serena-operator"
        ]

        issues = []
        recommendations = []

        if not external_configured:
            recommendations.append("No external analytics sources fully configured yet. Continue with pasted/exported metrics until credentials are added.")

        if not env.get("google-business-profile", {}).get("configured"):
            recommendations.append("Set GBP_ACCOUNT_ID and GBP_LOCATION_IDS later for live Google Business Profile analytics.")

        if not env.get("facebook", {}).get("configured"):
            recommendations.append("Set META_APP_ID, META_APP_SECRET, META_ACCESS_TOKEN, and FACEBOOK_PAGE_IDS later for live Facebook Page analytics.")

        if not env.get("wordpress", {}).get("configured"):
            recommendations.append("Set WordPress/WooCommerce/Jetpack credentials later for live website analytics.")

        recommendations.extend([
            "Use analytics summaries as inputs to Reporting for shareable reports.",
            "Run Compliance before external export if analytics includes patient/client/financial/business-sensitive data.",
            "Keep Analytics read-only; posting/editing belongs to future social/WordPress operator skills.",
            "Keep Hub adapter pending until Serena Hub dashboard/event bus exists.",
        ])

        payload = {
            "report_type": "serena_analytics_audit",
            "created_at": _timestamp(),
            "source_count": len(sources),
            "configured_sources": configured,
            "external_configured_sources": external_configured,
            "artifact_counts": counts,
            "env_status": env,
            "safety_policy": safety,
            "hub_adapter": hub,
            "issues": issues,
            "recommendations": recommendations,
            "external_api_called": False,
            "changes_made": False,
            "delete_performed": False,
            "secret_values_exposed": False,
        }
        report_path = _save_json("reports", "analytics-audit", payload)

        lines = [
            "Serena Analytics audit",
            "",
            f"- Sources registered: {len(sources)}",
            f"- Configured sources: {len(configured)}",
            f"- Configured external sources: {len(external_configured)}",
            f"- Reports: {counts['reports']}",
            f"- Snapshots: {counts['snapshots']}",
            f"- Source records: {counts['sources']}",
            f"- Exports: {counts['exports']}",
            f"- Handoff records: {counts['handoff']}",
            f"- Audit report: {report_path}",
            "- External API called: no",
            "- Changes made: no",
            "- Delete performed: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Issues:",
        ]

        lines.extend(f"- {item}" for item in issues) if issues else lines.append("- none")

        lines.extend(["", "Recommendations:"])
        lines.extend(f"- {item}" for item in recommendations)

        lines.extend(["", "Blocked operations:"])
        for item in safety["blocked"]:
            lines.append(f"- {item}")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


def _blocked_analytics_response(
    title: str,
    action: str,
    reason: str,
    blocked_reason: str,
    report_name: str,
) -> ToolResult:
    payload = {
        "report_type": f"serena_analytics_{report_name}",
        "created_at": _timestamp(),
        "action": action,
        "reason": reason,
        "blocked_reason": blocked_reason,
        "risk_level": "BLOCKED",
        "allowed_to_continue": False,
        "approval_required": True,
        "owner_review_required": True,
        "external_api_called": False,
        "snapshot_created": False,
        "report_created": False,
        "export_performed": False,
        "delete_performed": False,
        "changes_made": False,
        "secret_values_exposed": False,
        "hub_adapter": _hub_adapter_contract(),
    }
    report_path = _save_json("reports", report_name, payload)

    return ToolResult(
        tool_name=f"serena_analytics_{report_name}",
        success=False,
        content=(
            f"{title}\n\n"
            f"- Action: {action}\n"
            f"- Reason: {reason}\n"
            f"- Blocked reason: {blocked_reason}\n"
            "- Risk level: BLOCKED\n"
            "- Allowed to continue: no\n"
            "- Approval required: yes\n"
            "- Owner review required: yes\n"
            f"- Report: {report_path}\n"
            "- External API called: no\n"
            "- Snapshot created: no\n"
            "- Report created: no\n"
            "- Export performed: no\n"
            "- Delete performed: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard"
        ),
        metadata={**payload, "report_path": str(report_path)},
    )


@ToolRegistry.register("serena_analytics_blocked_token_exposure")
class SerenaAnalyticsBlockedTokenExposureTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_blocked_token_exposure"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Deliberately blocked token/API secret exposure command.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        return _blocked_analytics_response(
            "Analytics token exposure blocked by Serena Analytics v1 policy",
            str(params.get("action") or "expose analytics token").strip(),
            str(params.get("reason") or "Token exposure requested.").strip(),
            "Serena Analytics may check whether tokens exist, but may never display access tokens, API secrets, refresh tokens, or page tokens.",
            "blocked-token-exposure",
        )


@ToolRegistry.register("serena_analytics_blocked_unapproved_posting")
class SerenaAnalyticsBlockedUnapprovedPostingTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_blocked_unapproved_posting"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Deliberately blocked posting/editing/campaign modification command from Analytics.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        return _blocked_analytics_response(
            "Posting or page/campaign modification blocked by Serena Analytics v1 policy",
            str(params.get("action") or "post or modify page/campaign").strip(),
            str(params.get("reason") or "Unapproved posting/modification requested.").strip(),
            "Analytics v1 is read/analyze/report only. Posting, editing pages, changing campaigns, and altering tracking settings belong to future approved operator workflows.",
            "blocked-unapproved-posting",
        )


@ToolRegistry.register("serena_analytics_blocked_sensitive_export")
class SerenaAnalyticsBlockedSensitiveExportTool(_AnalyticsBaseTool):
    tool_id = "serena_analytics_blocked_sensitive_export"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Deliberately blocked sensitive analytics export command.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
            category="serena_analytics",
        )

    def execute(self, **params: Any) -> ToolResult:
        return _blocked_analytics_response(
            "Sensitive analytics export blocked by Serena Analytics v1 policy",
            str(params.get("action") or "export sensitive analytics").strip(),
            str(params.get("reason") or "Sensitive analytics export requested.").strip(),
            "Serena may not export business-sensitive, financial, patient/client, or combined CRM/revenue analytics externally without explicit approval and Compliance review.",
            "blocked-sensitive-export",
        )


__all__ = [
    "SerenaAnalyticsStatusTool",
    "SerenaAnalyticsEnvCheckTool",
    "SerenaAnalyticsPlanTool",
    "SerenaAnalyticsSourceListTool",
    "SerenaAnalyticsSourceInfoTool",
    "SerenaAnalyticsCompareTool",
    "SerenaAnalyticsWebsiteSummaryTool",
    "SerenaAnalyticsGBPKeywordsTool",
    "SerenaAnalyticsSocialSummaryTool",
    "SerenaAnalyticsRecommendationsTool",
    "SerenaAnalyticsBlockedSensitiveExportTool",
    "SerenaAnalyticsBlockedUnapprovedPostingTool",
    "SerenaAnalyticsBlockedTokenExposureTool",
    "SerenaAnalyticsAuditTool",
    "SerenaAnalyticsContentPerformanceTool",
    "SerenaAnalyticsMarketingFunnelTool",
    "SerenaAnalyticsBusinessOverviewTool",
    "SerenaAnalyticsFacebookPageSummaryTool",
    "SerenaAnalyticsFacebookPagesTool",
    "SerenaAnalyticsMetaEnvCheckTool",
    "SerenaAnalyticsGBPSummaryTool",
    "SerenaAnalyticsGBPPlanTool",
    "SerenaAnalyticsGBPEnvCheckTool",
    "SerenaAnalyticsGA4PlanTool",
    "SerenaAnalyticsWordpressSummaryTool",
    "SerenaAnalyticsWordpressPlanTool",
    "SerenaAnalyticsSnapshotTool",
    "SerenaAnalyticsFromFolderTool",
    "SerenaAnalyticsFromFileTool",
    "SerenaAnalyticsFromJsonTool",
]
