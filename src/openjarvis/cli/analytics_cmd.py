
"""Serena Analytics Full Operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_analytics import (
    SerenaAnalyticsEnvCheckTool,
    SerenaAnalyticsPlanTool,
    SerenaAnalyticsSourceInfoTool,
    SerenaAnalyticsSourceListTool,
    SerenaAnalyticsStatusTool,
    SerenaAnalyticsBlockedSensitiveExportTool,
    SerenaAnalyticsBlockedUnapprovedPostingTool,
    SerenaAnalyticsBlockedTokenExposureTool,
    SerenaAnalyticsAuditTool,
    SerenaAnalyticsRecommendationsTool,
    SerenaAnalyticsContentPerformanceTool,
    SerenaAnalyticsMarketingFunnelTool,
    SerenaAnalyticsBusinessOverviewTool,
    SerenaAnalyticsSocialSummaryTool,
    SerenaAnalyticsFacebookPageSummaryTool,
    SerenaAnalyticsFacebookPagesTool,
    SerenaAnalyticsMetaEnvCheckTool,
    SerenaAnalyticsGBPKeywordsTool,
    SerenaAnalyticsGBPSummaryTool,
    SerenaAnalyticsGBPPlanTool,
    SerenaAnalyticsGBPEnvCheckTool,
    SerenaAnalyticsWebsiteSummaryTool,
    SerenaAnalyticsGA4PlanTool,
    SerenaAnalyticsWordpressSummaryTool,
    SerenaAnalyticsWordpressPlanTool,
    SerenaAnalyticsCompareTool,
    SerenaAnalyticsSnapshotTool,
    SerenaAnalyticsFromFolderTool,
    SerenaAnalyticsFromFileTool,
    SerenaAnalyticsFromJsonTool,
)


@click.group()
def analytics() -> None:
    """Native Serena Analytics operator tools."""


@analytics.command("status")
def status() -> None:
    """Show Analytics operator status."""
    console = Console()
    result = SerenaAnalyticsStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("env-check")
def env_check() -> None:
    """Check analytics environment configuration without exposing secrets."""
    console = Console()
    result = SerenaAnalyticsEnvCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("source-list")
def source_list() -> None:
    """List registered analytics sources."""
    console = Console()
    result = SerenaAnalyticsSourceListTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("source-info")
@click.option("--source", required=True, help="Source ID, e.g. wordpress, ga4, google-business-profile, facebook.")
def source_info(source: str) -> None:
    """Show details for one analytics source."""
    console = Console()
    result = SerenaAnalyticsSourceInfoTool().execute(source=source)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("plan")
@click.option("--goal", required=True, help="Analytics goal.")
@click.option("--source", default="serena-operator", help="Analytics source.")
@click.option("--date-range", default="last 30 days", help="Date range.")
@click.option("--business", default="General Business", help="Business/context.")
def plan(goal: str, source: str, date_range: str, business: str) -> None:
    """Create an analytics operation plan."""
    console = Console()
    result = SerenaAnalyticsPlanTool().execute(goal=goal, source=source, date_range=date_range, business=business)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("from-json")
@click.option("--json-text", required=True, help="Analytics JSON text.")
@click.option("--title", default="Serena Analytics JSON Snapshot", help="Snapshot title.")
@click.option("--source", default="provided-json", help="Analytics source.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
def from_json(json_text: str, title: str, source: str, business: str, date_range: str) -> None:
    """Create analytics snapshot from JSON text."""
    console = Console()
    result = SerenaAnalyticsFromJsonTool().execute(
        json_text=json_text,
        title=title,
        source=source,
        business=business,
        date_range=date_range,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("from-file")
@click.option("--path", required=True, help="Analytics JSON file path.")
@click.option("--title", default="Serena Analytics File Snapshot", help="Snapshot title.")
@click.option("--source", default="file", help="Analytics source.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
def from_file(path: str, title: str, source: str, business: str, date_range: str) -> None:
    """Create analytics snapshot from JSON file."""
    console = Console()
    result = SerenaAnalyticsFromFileTool().execute(
        path=path,
        title=title,
        source=source,
        business=business,
        date_range=date_range,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("from-folder")
@click.option("--folder", required=True, help="Folder containing JSON files.")
@click.option("--title", default="Serena Analytics Folder Snapshot", help="Snapshot title.")
@click.option("--source", default="folder", help="Analytics source.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
@click.option("--limit", default=10, type=int, help="Maximum files.")
def from_folder(folder: str, title: str, source: str, business: str, date_range: str, limit: int) -> None:
    """Create analytics snapshot from folder JSON files."""
    console = Console()
    result = SerenaAnalyticsFromFolderTool().execute(
        folder=folder,
        title=title,
        source=source,
        business=business,
        date_range=date_range,
        limit=limit,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("snapshot")
@click.option("--business", default="Serena Local Operator", help="Business/context.")
@click.option("--date-range", default="current local outputs", help="Date range.")
def snapshot(business: str, date_range: str) -> None:
    """Create Serena local operator analytics snapshot."""
    console = Console()
    result = SerenaAnalyticsSnapshotTool().execute(business=business, date_range=date_range)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("compare")
@click.option("--current-json", default="", help="Current JSON text.")
@click.option("--previous-json", default="", help="Previous JSON text.")
@click.option("--current-file", default="", help="Current JSON file.")
@click.option("--previous-file", default="", help="Previous JSON file.")
@click.option("--title", default="Serena Analytics Comparison", help="Comparison title.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--source", default="comparison", help="Analytics source.")
def compare(
    current_json: str,
    previous_json: str,
    current_file: str,
    previous_file: str,
    title: str,
    business: str,
    source: str,
) -> None:
    """Compare two analytics JSON payloads or files."""
    console = Console()
    result = SerenaAnalyticsCompareTool().execute(
        current_json=current_json,
        previous_json=previous_json,
        current_file=current_file,
        previous_file=previous_file,
        title=title,
        business=business,
        source=source,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("wordpress-plan")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="last 30 days", help="Date range.")
@click.option("--goal", default="Analyze WordPress website performance.", help="Analytics goal.")
def wordpress_plan(business: str, date_range: str, goal: str) -> None:
    """Create a WordPress analytics plan."""
    console = Console()
    result = SerenaAnalyticsWordpressPlanTool().execute(business=business, date_range=date_range, goal=goal)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("wordpress-summary")
@click.option("--metrics", required=True, help="WordPress/WooCommerce/Jetpack metrics as JSON or JSON-like text.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
@click.option("--notes", default="", help="Optional notes.")
def wordpress_summary(metrics: str, business: str, date_range: str, notes: str) -> None:
    """Create a WordPress analytics summary from metrics."""
    console = Console()
    result = SerenaAnalyticsWordpressSummaryTool().execute(metrics=metrics, business=business, date_range=date_range, notes=notes)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("ga4-plan")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="last 30 days", help="Date range.")
@click.option("--goal", default="Analyze GA4 website performance.", help="Analytics goal.")
def ga4_plan(business: str, date_range: str, goal: str) -> None:
    """Create a GA4 analytics plan."""
    console = Console()
    result = SerenaAnalyticsGA4PlanTool().execute(business=business, date_range=date_range, goal=goal)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("website-summary")
@click.option("--metrics", required=True, help="Website metrics as JSON or JSON-like text.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
@click.option("--source", default="website", help="Website analytics source.")
@click.option("--notes", default="", help="Optional notes.")
def website_summary(metrics: str, business: str, date_range: str, source: str, notes: str) -> None:
    """Create a website analytics summary from metrics."""
    console = Console()
    result = SerenaAnalyticsWebsiteSummaryTool().execute(
        metrics=metrics,
        business=business,
        date_range=date_range,
        source=source,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("gbp-env-check")
def gbp_env_check() -> None:
    """Check Google Business Profile analytics env configuration."""
    console = Console()
    result = SerenaAnalyticsGBPEnvCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("gbp-plan")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="last 30 days", help="Date range.")
@click.option("--goal", default="Analyze Google Business Profile performance.", help="Analytics goal.")
def gbp_plan(business: str, date_range: str, goal: str) -> None:
    """Create a Google Business Profile analytics plan."""
    console = Console()
    result = SerenaAnalyticsGBPPlanTool().execute(business=business, date_range=date_range, goal=goal)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("gbp-summary")
@click.option("--metrics", required=True, help="GBP metrics as JSON or JSON-like text.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
@click.option("--location", default="primary location", help="GBP location/profile.")
@click.option("--notes", default="", help="Optional notes.")
def gbp_summary(metrics: str, business: str, date_range: str, location: str, notes: str) -> None:
    """Create a Google Business Profile analytics summary."""
    console = Console()
    result = SerenaAnalyticsGBPSummaryTool().execute(
        metrics=metrics,
        business=business,
        date_range=date_range,
        location=location,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("gbp-keywords")
@click.option("--keywords", required=True, help="GBP keyword metrics as JSON or JSON-like text.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
@click.option("--location", default="primary location", help="GBP location/profile.")
def gbp_keywords(keywords: str, business: str, date_range: str, location: str) -> None:
    """Create a Google Business Profile keyword analytics summary."""
    console = Console()
    result = SerenaAnalyticsGBPKeywordsTool().execute(
        keywords=keywords,
        business=business,
        date_range=date_range,
        location=location,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("meta-env-check")
def meta_env_check() -> None:
    """Check Meta/Facebook analytics env configuration."""
    console = Console()
    result = SerenaAnalyticsMetaEnvCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("facebook-pages")
def facebook_pages() -> None:
    """Show configured Facebook Page analytics readiness."""
    console = Console()
    result = SerenaAnalyticsFacebookPagesTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("facebook-page-summary")
@click.option("--metrics", required=True, help="Facebook Page metrics as JSON or JSON-like text.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
@click.option("--page", default="facebook page", help="Facebook page label.")
@click.option("--notes", default="", help="Optional notes.")
def facebook_page_summary(metrics: str, business: str, date_range: str, page: str, notes: str) -> None:
    """Create a Facebook Page analytics summary."""
    console = Console()
    result = SerenaAnalyticsFacebookPageSummaryTool().execute(
        metrics=metrics,
        business=business,
        date_range=date_range,
        page=page,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("social-summary")
@click.option("--metrics", required=True, help="Social metrics as JSON or JSON-like text.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
@click.option("--source", default="social", help="Social analytics source.")
@click.option("--notes", default="", help="Optional notes.")
def social_summary(metrics: str, business: str, date_range: str, source: str, notes: str) -> None:
    """Create a combined social analytics summary."""
    console = Console()
    result = SerenaAnalyticsSocialSummaryTool().execute(
        metrics=metrics,
        business=business,
        date_range=date_range,
        source=source,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("business-overview")
@click.option("--metrics", required=True, help="Business analytics metrics as JSON or JSON-like text.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
@click.option("--source", default="multi-source", help="Analytics source.")
@click.option("--notes", default="", help="Optional notes.")
def business_overview(metrics: str, business: str, date_range: str, source: str, notes: str) -> None:
    """Create a business analytics overview."""
    console = Console()
    result = SerenaAnalyticsBusinessOverviewTool().execute(
        metrics=metrics,
        business=business,
        date_range=date_range,
        source=source,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("marketing-funnel")
@click.option("--metrics", required=True, help="Marketing funnel metrics as JSON or JSON-like text.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
@click.option("--source", default="marketing-funnel", help="Analytics source.")
@click.option("--notes", default="", help="Optional notes.")
def marketing_funnel(metrics: str, business: str, date_range: str, source: str, notes: str) -> None:
    """Analyze a marketing funnel."""
    console = Console()
    result = SerenaAnalyticsMarketingFunnelTool().execute(
        metrics=metrics,
        business=business,
        date_range=date_range,
        source=source,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("content-performance")
@click.option("--metrics", required=True, help="Content performance metrics as JSON or JSON-like text.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
@click.option("--source", default="content", help="Analytics source.")
@click.option("--notes", default="", help="Optional notes.")
def content_performance(metrics: str, business: str, date_range: str, source: str, notes: str) -> None:
    """Analyze content performance."""
    console = Console()
    result = SerenaAnalyticsContentPerformanceTool().execute(
        metrics=metrics,
        business=business,
        date_range=date_range,
        source=source,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("recommendations")
@click.option("--metrics", required=True, help="Analytics metrics as JSON or JSON-like text.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date-range", default="unspecified", help="Date range.")
@click.option("--source", default="multi-source", help="Analytics source.")
@click.option("--notes", default="", help="Optional notes.")
def recommendations(metrics: str, business: str, date_range: str, source: str, notes: str) -> None:
    """Create analytics recommendations."""
    console = Console()
    result = SerenaAnalyticsRecommendationsTool().execute(
        metrics=metrics,
        business=business,
        date_range=date_range,
        source=source,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("audit")
def audit() -> None:
    """Audit Analytics outputs, sources, env readiness, and safety posture."""
    console = Console()
    result = SerenaAnalyticsAuditTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("blocked-token-exposure")
@click.option("--action", default="expose analytics token", help="Requested action.")
@click.option("--reason", default="Token exposure requested.", help="Reason.")
def blocked_token_exposure(action: str, reason: str) -> None:
    """Deliberately blocked token/API secret exposure command."""
    console = Console()
    result = SerenaAnalyticsBlockedTokenExposureTool().execute(action=action, reason=reason)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("blocked-unapproved-posting")
@click.option("--action", default="post or modify page/campaign", help="Requested action.")
@click.option("--reason", default="Unapproved posting/modification requested.", help="Reason.")
def blocked_unapproved_posting(action: str, reason: str) -> None:
    """Deliberately blocked posting/page/campaign modification command."""
    console = Console()
    result = SerenaAnalyticsBlockedUnapprovedPostingTool().execute(action=action, reason=reason)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@analytics.command("blocked-sensitive-export")
@click.option("--action", default="export sensitive analytics", help="Requested action.")
@click.option("--reason", default="Sensitive analytics export requested.", help="Reason.")
def blocked_sensitive_export(action: str, reason: str) -> None:
    """Deliberately blocked sensitive analytics export command."""
    console = Console()
    result = SerenaAnalyticsBlockedSensitiveExportTool().execute(action=action, reason=reason)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["analytics"]
