"""Digest collection tool — fetches recent data from configured connectors."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry, ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# ---------------------------------------------------------------------------
# Section definitions: ordered list of (section_name, connector_ids)
# ---------------------------------------------------------------------------

_SECTION_ORDER: List[tuple] = [
    ("HEALTH", {"oura", "apple_health", "strava"}),
    (
        "MESSAGES",
        {
            "gmail",
            "gmail_imap",
            "google_tasks",
            "slack",
            "imessage",
            "whatsapp",
            "outlook",
            "notion",
            "github_notifications",
        },
    ),
    ("CALENDAR", {"gcalendar"}),
    ("WORLD", {"weather", "hackernews", "news_rss"}),
    ("MUSIC", {"spotify", "apple_music"}),
]

_CONNECTOR_TO_SECTION: Dict[str, str] = {}
for _section_name, _ids in _SECTION_ORDER:
    for _cid in _ids:
        _CONNECTOR_TO_SECTION[_cid] = _section_name


# ---------------------------------------------------------------------------
# Per-connector human-readable formatters
# ---------------------------------------------------------------------------


def _format_duration(seconds: float) -> str:
    """Format seconds as 'Xh Ym'."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def _time_ago(ts: datetime) -> str:
    """Return a human-readable relative time like '2h ago' or '15m ago'."""
    now = datetime.now()
    ts_naive = ts.replace(tzinfo=None) if ts.tzinfo else ts
    delta = now - ts_naive
    total_seconds = max(0, int(delta.total_seconds()))
    if total_seconds < 60:
        return "just now"
    if total_seconds < 3600:
        return f"{total_seconds // 60}m ago"
    if total_seconds < 86400:
        return f"{total_seconds // 3600}h ago"
    days = total_seconds // 86400
    return f"{days}d ago"


def _format_date(ts: datetime) -> str:
    """Format a datetime as 'April 1' style."""
    return ts.strftime("%B %-d") if hasattr(ts, "strftime") else str(ts)


def _format_time(ts: datetime) -> str:
    """Format a datetime as '10:30 AM' style."""
    return ts.strftime("%-I:%M %p") if hasattr(ts, "strftime") else str(ts)


def _parse_content_json(doc: Document) -> Dict[str, Any]:
    """Try to parse the document content as JSON; return {} on failure."""
    try:
        return json.loads(doc.content)
    except (json.JSONDecodeError, TypeError):
        return {}


def _format_oura(doc: Document) -> str:
    """Format an Oura Ring document into a readable line."""
    data = _parse_content_json(doc)
    data_type = doc.metadata.get("data_type", "")
    day = doc.metadata.get("day", "")
    day_str = day or _format_date(doc.timestamp)

    if data_type == "sleep":
        hr = data.get("average_heart_rate", "?")
        hrv = data.get("average_hrv", data.get("average_heart_rate_variability", "?"))
        total = data.get("total_sleep_duration")
        awake = data.get("awake_time")
        score = data.get("score")
        parts = []
        if score is not None:
            parts.append(f"score {score}")
        parts.append(f"avg HR {hr} bpm")
        if hrv != "?":
            parts.append(f"HRV {hrv}")
        if total is not None:
            parts.append(f"{_format_duration(total)} total sleep")
        if awake is not None:
            parts.append(f"awake {_format_duration(awake)}")
        return f"[oura] Sleep — {day_str}: {', '.join(parts)}"

    if data_type == "daily_readiness":
        score = data.get("score", "?")
        temp = data.get(
            "temperature_deviation",
            data.get("temperature_trend_deviation"),
        )
        line = f"[oura] Readiness — {day_str}: score {score}"
        if temp is not None:
            sign = "+" if temp >= 0 else ""
            line += f", temperature deviation {sign}{temp}"
        return line

    if data_type == "daily_activity":
        steps = data.get("steps", "?")
        cal = data.get("total_calories", data.get("active_calories", "?"))
        score = data.get("score")
        parts = []
        if score is not None:
            parts.append(f"score {score}")
        parts.append(f"steps {steps}")
        parts.append(f"calories {cal}")
        return f"[oura] Activity — {day_str}: {', '.join(parts)}"

    # Fallback for unknown Oura doc types
    return f"[oura] {doc.title}"


def _format_apple_health(doc: Document) -> str:
    """Format an Apple Health document."""
    return f"[apple_health] {doc.title}"


def _format_strava(doc: Document) -> str:
    """Format a Strava activity document."""
    return f"[strava] {doc.title}"


def _format_gmail(doc: Document) -> str:
    """Format a Gmail email document."""
    sender = doc.author or "Unknown"
    subject = doc.title or "(no subject)"
    ago = _time_ago(doc.timestamp)
    # Include body preview (first 150 chars, single line)
    body = doc.content.replace("\n", " ").strip()[:150] if doc.content else ""
    line = f'[gmail] From: {sender} — "{subject}" ({ago})'
    if body:
        line += f"\n  Preview: {body}"
    return line


def _format_gmail_imap(doc: Document) -> str:
    """Format a Gmail IMAP email document."""
    sender = doc.author or "Unknown"
    subject = doc.title or "(no subject)"
    ago = _time_ago(doc.timestamp)
    return f'[gmail] From: {sender} — "{subject}" ({ago})'


def _format_google_tasks(doc: Document) -> str:
    """Format a Google Tasks document."""
    title = doc.title or "Untitled Task"
    status = doc.metadata.get("status", "")
    due = doc.metadata.get("due", "")
    parts = [f"[google_tasks] {title}"]
    extras = []
    if due:
        extras.append(f"due {due}")
    if status == "completed":
        extras.append("completed")
    if extras:
        parts.append(f"({', '.join(extras)})")
    return " ".join(parts)


def _format_slack(doc: Document) -> str:
    """Format a Slack message document."""
    author = doc.author or "Unknown"
    channel = doc.metadata.get("channel", "")
    ago = _time_ago(doc.timestamp)
    snippet = doc.content[:150].replace("\n", " ").strip()
    content_preview = snippet if doc.content else ""
    prefix = f"[slack] #{channel}" if channel else "[slack]"
    line = f"{prefix} {author} ({ago})"
    if content_preview:
        line += f": {content_preview}"
    return line


def _format_imessage(doc: Document) -> str:
    """Format an iMessage document."""
    sender = doc.author or "Unknown"
    ago = _time_ago(doc.timestamp)
    snippet = doc.content[:150].replace("\n", " ").strip()
    content_preview = snippet if doc.content else ""
    line = f"[imessage] {sender} ({ago})"
    if content_preview:
        line += f": {content_preview}"
    return line


def _format_whatsapp(doc: Document) -> str:
    """Format a WhatsApp message document."""
    sender = doc.author or "Unknown"
    content_preview = doc.content[:80].replace("\n", " ").strip() if doc.content else ""
    return f"[whatsapp] {sender}: {content_preview}"


def _format_outlook(doc: Document) -> str:
    """Format an Outlook email document."""
    sender = doc.author or "Unknown"
    subject = doc.title or "(no subject)"
    ago = _time_ago(doc.timestamp)
    return f'[outlook] From: {sender} — "{subject}" ({ago})'


def _format_notion(doc: Document) -> str:
    """Format a Notion page document."""
    title = doc.title or "Untitled"
    ago = _time_ago(doc.timestamp)
    return f"[notion] {title} (updated {ago})"


def _format_gcalendar(doc: Document) -> str:
    """Format a Google Calendar event document."""
    title = doc.title or "(No title)"
    time_str = _format_time(doc.timestamp)
    # Try to extract duration from content
    duration_match = (
        re.search(r"When:\s*(.+?)$", doc.content, re.MULTILINE) if doc.content else None
    )
    time_range = ""
    if duration_match:
        when = duration_match.group(1).strip()
        # Extract just the times from the ISO strings
        parts = when.split(" – ")
        if len(parts) == 2:
            try:
                start_dt = datetime.fromisoformat(parts[0].replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(parts[1].replace("Z", "+00:00"))
                diff = end_dt - start_dt
                mins = int(diff.total_seconds() / 60)
                if mins >= 60:
                    hrs = mins // 60
                    remaining = mins % 60
                    duration = f"{hrs} hour" + ("s" if hrs > 1 else "")
                    if remaining:
                        duration += f" {remaining} min"
                else:
                    duration = f"{mins} min"
                time_range = f" ({duration})"
            except (ValueError, TypeError):
                pass
    return f"[gcalendar] {time_str} — {title}{time_range}"


def _format_spotify(doc: Document) -> str:
    """Format a Spotify recently-played track — returns 'Track — Artist'."""
    # doc.title is already "Track — Artist" from the connector
    return doc.title


def _format_apple_music(doc: Document) -> str:
    """Format an Apple Music track — returns 'Track — Artist'."""
    # doc.title is already "Track — Artist" from the connector
    return doc.title


def _format_weather(doc: Document) -> str:
    """Format a weather document."""
    data = _parse_content_json(doc)
    if doc.doc_type == "current":
        temp = data.get("temp_f", "?")
        cond = data.get("conditions", "?")
        humidity = data.get("humidity", "?")
        return f"[weather] Current: {temp}°F, {cond}, humidity {humidity}%"
    if doc.doc_type == "forecast":
        return f"[weather] Forecast: {doc.content[:200]}"
    return f"[weather] {doc.title}"


def _format_github_notifications(doc: Document) -> str:
    """Format a GitHub notification."""
    reason = doc.metadata.get("reason", "")
    repo = doc.metadata.get("repo", "")
    title = doc.title or "(no title)"
    ago = _time_ago(doc.timestamp)
    reason_str = f" ({reason})" if reason else ""
    repo_str = f" in {repo}" if repo else ""
    return f"[github] {title}{repo_str}{reason_str} ({ago})"


def _format_hackernews(doc: Document) -> str:
    """Format a Hacker News story."""
    score = doc.metadata.get("score", "?")
    comments = doc.metadata.get("descendants", "?")
    return f"[hackernews] {doc.title} (score {score}, {comments} comments)"


def _format_news_rss(doc: Document) -> str:
    """Format an RSS news item."""
    feed_name = doc.metadata.get("feed_name", "")
    prefix = f"[{feed_name}]" if feed_name else "[news]"
    description = doc.content[:150].replace("\n", " ").strip() if doc.content else ""
    line = f"{prefix} {doc.title}"
    if description:
        line += f" — {description}"
    return line


# Map connector IDs to their formatting functions
_FORMATTERS: Dict[str, Any] = {
    "oura": _format_oura,
    "apple_health": _format_apple_health,
    "strava": _format_strava,
    "gmail": _format_gmail,
    "gmail_imap": _format_gmail_imap,
    "google_tasks": _format_google_tasks,
    "slack": _format_slack,
    "imessage": _format_imessage,
    "whatsapp": _format_whatsapp,
    "outlook": _format_outlook,
    "notion": _format_notion,
    "gcalendar": _format_gcalendar,
    "weather": _format_weather,
    "github_notifications": _format_github_notifications,
    "hackernews": _format_hackernews,
    "news_rss": _format_news_rss,
    "spotify": _format_spotify,
    "apple_music": _format_apple_music,
}


def _format_doc(source: str, doc: Document) -> str:
    """Format a document using the source-specific formatter, with fallback."""
    formatter = _FORMATTERS.get(source)
    if formatter:
        try:
            return formatter(doc)
        except Exception:  # noqa: BLE001
            pass
    # Fallback: connector name + title
    return f"[{source}] {doc.title}"


def _format_music_section(
    collected_docs: Dict[str, List[Document]],
    music_connectors: set,
) -> List[str]:
    """Format music connectors as grouped lists instead of per-track lines."""
    lines: List[str] = []
    for source in sorted(music_connectors):
        docs = collected_docs.get(source, [])
        if not docs:
            continue
        tracks = []
        for doc in docs:
            tracks.append(doc.title)
        label = "Recently played" if source == "spotify" else "Library"
        lines.append(f"[{source}] {label}: {', '.join(tracks)}")
    return lines


@ToolRegistry.register("digest_collect")
class DigestCollectTool(BaseTool):
    """Collect recent data from multiple connectors for digest synthesis."""

    tool_id = "digest_collect"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="digest_collect",
            description=(
                "Fetch recent data from configured connectors (email, calendar, "
                "health, tasks, etc.) and return a structured, human-readable "
                "summary grouped by section (Health, Messages, Calendar, Music) "
                "for digest synthesis."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of connector IDs to fetch from "
                            "(e.g., ['gmail', 'oura', 'gcalendar'])."
                        ),
                    },
                    "hours_back": {
                        "type": "number",
                        "description": "How many hours back to look (default: 24).",
                    },
                },
                "required": ["sources"],
            },
            category="data",
            timeout_seconds=60.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        # Ensure connectors are registered
        import openjarvis.connectors  # noqa: F401

        sources: List[str] = params.get("sources", [])
        hours_back: float = params.get("hours_back", 24)
        since = datetime.now() - timedelta(hours=hours_back)

        # Collect raw documents per source
        collected_docs: Dict[str, List[Document]] = {}
        errors: List[str] = []

        for source in sources:
            if not ConnectorRegistry.contains(source):
                errors.append(f"Connector '{source}' not available")
                continue

            try:
                connector_cls = ConnectorRegistry.get(source)
                connector = connector_cls()

                if not connector.is_connected():
                    errors.append(
                        f"Connector '{source}' not connected (no credentials)"
                    )
                    continue

                # Cap per-source to avoid overwhelming the LLM context
                max_per_source = 15
                docs: List[Document] = []
                for d in connector.sync(since=since):
                    docs.append(d)
                    if len(docs) >= max_per_source:
                        break

                collected_docs[source] = docs
            except Exception as exc:
                errors.append(f"Error fetching from '{source}': {exc}")

        # Group by section and build human-readable output
        summary_parts: List[str] = []
        for section_name, section_connectors in _SECTION_ORDER:
            # Gather all sources that belong to this section and have data
            section_sources = [
                s for s in sources if s in section_connectors and s in collected_docs
            ]
            if not section_sources:
                continue

            section_lines: List[str] = []

            if section_name == "MUSIC":
                # Music gets special grouped formatting
                section_lines = _format_music_section(
                    collected_docs, section_connectors
                )
            else:
                for source in section_sources:
                    for doc in collected_docs[source]:
                        section_lines.append(_format_doc(source, doc))

            if section_lines:
                summary_parts.append(f"=== {section_name} ===")
                summary_parts.extend(section_lines)
                summary_parts.append("")  # blank line between sections

        # Handle any connectors not in a known section (fallback)
        known_connectors = set()
        for _, cids in _SECTION_ORDER:
            known_connectors |= cids

        uncategorized_sources = [
            s for s in sources if s not in known_connectors and s in collected_docs
        ]
        if uncategorized_sources:
            summary_parts.append("=== OTHER ===")
            for source in uncategorized_sources:
                for doc in collected_docs[source]:
                    summary_parts.append(_format_doc(source, doc))
            summary_parts.append("")

        # Errors at the end, not inline
        if errors:
            summary_parts.append("=== ERRORS ===")
            summary_parts.extend(errors)

        return ToolResult(
            tool_name="digest_collect",
            content="\n".join(summary_parts),
            success=True,
            metadata={
                "sources_queried": sources,
                "sources_ok": list(collected_docs.keys()),
                "sources_failed": errors,
                "total_items": sum(len(v) for v in collected_docs.values()),
            },
        )
