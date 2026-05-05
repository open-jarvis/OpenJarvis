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


__all__ = [
    "SerenaAnalyticsStatusTool",
    "SerenaAnalyticsEnvCheckTool",
    "SerenaAnalyticsPlanTool",
    "SerenaAnalyticsSourceListTool",
    "SerenaAnalyticsSourceInfoTool",
]
