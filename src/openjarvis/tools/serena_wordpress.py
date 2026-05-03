"""Serena WordPress native tools.

Converted and upgraded from legacy Serena `13-wordpress.js`.

These tools use WordPress REST API with Application Password authentication.
They keep the UX natural-language first and apply safe defaults:
drafts by default, explicit approval for publishing/live updates.
"""

from __future__ import annotations

import base64
from datetime import datetime
import html
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import requests

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bool_env(name: str, default: bool = False) -> bool:
    value = _env(name)
    if not value:
        return default
    return value.lower() in ("1", "true", "yes", "y", "on")


def _site_key(site_key: str | None = None) -> str:
    raw = (site_key or _env("WORDPRESS_DEFAULT_SITE") or "drpiet").strip().lower()
    return re.sub(r"[^a-z0-9_]+", "", raw) or "drpiet"


def _site_prefix(site_key: str | None = None) -> str:
    return "WORDPRESS_SITE_" + _site_key(site_key).upper() + "_"


def _available_sites() -> list[str]:
    raw = _env("WORDPRESS_SITES", _env("WORDPRESS_DEFAULT_SITE", "drpiet"))
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


def _config(site_key: str | None = None) -> dict[str, Any]:
    key = _site_key(site_key)
    prefix = _site_prefix(key)

    # Multi-site env first.
    site_url = _env(prefix + "SITE_URL")
    rest_base = _env(prefix + "REST_BASE_URL")
    username = _env(prefix + "USERNAME")
    app_password = _env(prefix + "APPLICATION_PASSWORD")

    # Legacy/global fallback.
    if not site_url:
        site_url = _env("WORDPRESS_SITE_URL") or _env("WORDPRESS_URL") or _env("SERENA_WP_URL")
    if not rest_base:
        rest_base = _env("WORDPRESS_REST_BASE_URL")
    if not username:
        username = _env("WORDPRESS_USERNAME") or _env("SERENA_WP_USERNAME")
    if not app_password:
        app_password = (
            _env("WORDPRESS_APPLICATION_PASSWORD")
            or _env("WORDPRESS_APP_PASSWORD")
            or _env("SERENA_WP_APP_PASSWORD")
        )

    if not rest_base and site_url:
        rest_base = site_url.rstrip("/") + "/wp-json/wp/v2"

    return {
        "site_key": key,
        "site_url": site_url.rstrip("/"),
        "rest_base_url": rest_base.rstrip("/"),
        "username": username,
        "app_password": app_password,
        "default_post_status": _env(prefix + "DEFAULT_POST_STATUS", _env("SERENA_WP_DEFAULT_STATUS", "draft")) or "draft",
        "default_page_status": _env(prefix + "DEFAULT_PAGE_STATUS", "draft") or "draft",
        "default_author_id": _env(prefix + "DEFAULT_AUTHOR_ID"),
        "default_category_id": _env(prefix + "DEFAULT_CATEGORY_ID"),
        "default_category_name": _env(prefix + "DEFAULT_CATEGORY_NAME"),
        "default_tags": _env(prefix + "DEFAULT_TAGS"),
        "default_featured_media_id": _env(prefix + "DEFAULT_FEATURED_MEDIA_ID"),
        "default_comment_status": _env(prefix + "DEFAULT_COMMENT_STATUS", "open") or "open",
        "default_ping_status": _env(prefix + "DEFAULT_PING_STATUS", "closed") or "closed",
        "artifact_dir": _env("SERENA_WP_ARTIFACT_DIR", _env("WORDPRESS_ARTIFACT_DIR", "outputs/wordpress")),
        "timeout": int(_env("WORDPRESS_TIMEOUT_MS", "20000") or "20000") / 1000,
        "enabled": _bool_env("WORDPRESS_ENABLED", True),
        "auto_slugify": _bool_env("WORDPRESS_AUTO_SLUGIFY", True),
        "auto_excerpt": _bool_env("WORDPRESS_AUTO_EXCERPT", True),
        "auto_seo_title": _bool_env("WORDPRESS_AUTO_SEO_TITLE", True),
        "auto_assign_featured_image": _bool_env("WORDPRESS_AUTO_ASSIGN_FEATURED_IMAGE", False),
        "primary_cta": _env("WORDPRESS_SITE_PRIMARY_CTA", "Book your consultation"),
        "booking_url": _env("WORDPRESS_BOOKING_URL"),
        "membership_url": _env("WORDPRESS_MEMBERSHIP_URL"),
        "lead_magnet_url": _env("WORDPRESS_LEAD_MAGNET_URL"),
        "corporate_wellness_url": _env("WORDPRESS_CORPORATE_WELLNESS_URL"),
        "mcp_enabled": _bool_env("WORDPRESS_MCP_ENABLED", False),
        "mcp_preferred_for_search": _bool_env("WORDPRESS_MCP_PREFERRED_FOR_SEARCH", True),
        "mcp_preferred_for_summaries": _bool_env("WORDPRESS_MCP_PREFERRED_FOR_SUMMARIES", True),
        "mcp_preferred_for_content_planning": _bool_env("WORDPRESS_MCP_PREFERRED_FOR_CONTENT_PLANNING", True),
        "mcp_preferred_for_create": _bool_env("WORDPRESS_MCP_PREFERRED_FOR_CREATE", False),
        "mcp_preferred_for_update": _bool_env("WORDPRESS_MCP_PREFERRED_FOR_UPDATE", False),
        "mcp_preferred_for_delete": _bool_env("WORDPRESS_MCP_PREFERRED_FOR_DELETE", False),
        "mcp_preferred_for_publish": _bool_env("WORDPRESS_MCP_PREFERRED_FOR_PUBLISH", False),
        "mcp_preferred_for_media": _bool_env("WORDPRESS_MCP_PREFERRED_FOR_MEDIA", False),
    }


def _configured(site_key: str | None = None) -> tuple[bool, str]:
    cfg = _config(site_key)
    if not cfg["enabled"]:
        return False, "WORDPRESS_ENABLED is false."
    missing = []
    if not cfg.get("site_url"):
        missing.append(f"{_site_prefix(site_key)}SITE_URL")
    if not cfg.get("rest_base_url"):
        missing.append(f"{_site_prefix(site_key)}REST_BASE_URL")
    if not cfg.get("username"):
        missing.append(f"{_site_prefix(site_key)}USERNAME")
    if not cfg.get("app_password"):
        missing.append(f"{_site_prefix(site_key)}APPLICATION_PASSWORD")
    if missing:
        return False, "Missing WordPress configuration: " + ", ".join(missing)
    return True, ""


def _base_url(site_key: str | None = None) -> str:
    return _config(site_key)["rest_base_url"].rstrip("/") + "/"


def _headers(site_key: str | None = None) -> dict[str, str]:
    cfg = _config(site_key)
    token = base64.b64encode(f"{cfg['username']}:{cfg['app_password']}".encode("utf-8")).decode("ascii")
    return {
        "Authorization": f"Basic {token}",
        "User-Agent": "SerenaLocalOperator/1.0",
    }


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug or "serena-draft"


def _rendered(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("rendered", "")
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return html.unescape(text).strip()


def _request(method: str, endpoint: str, site_key: str | None = None, **kwargs: Any) -> dict[str, Any] | list[Any]:
    ok, msg = _configured(site_key)
    if not ok:
        raise RuntimeError(msg)

    headers = kwargs.pop("headers", None) or _headers(site_key)
    timeout = _config(site_key).get("timeout", 30)

    url = urljoin(_base_url(site_key), endpoint.lstrip("/"))
    response = requests.request(
        method,
        url,
        headers=headers,
        timeout=timeout,
        **kwargs,
    )

    if not response.ok:
        try:
            details = response.json()
        except Exception:
            details = response.text
        raise RuntimeError(f"WordPress API error {response.status_code}: {details}")

    if not response.text:
        return {}

    return response.json()


def _save_artifact(kind: str, data: dict[str, Any], content: str = "") -> str:
    cfg = _config()
    out_dir = Path(cfg["artifact_dir"]) / kind
    out_dir.mkdir(parents=True, exist_ok=True)

    title = _rendered(data.get("title")) or str(data.get("slug") or data.get("id") or "wordpress-item")
    safe = _slugify(title)
    item_id = data.get("id", "unknown")
    folder = out_dir / f"{item_id}-{safe}"
    folder.mkdir(parents=True, exist_ok=True)

    (folder / "metadata.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    if content:
        (folder / "content.html").write_text(content, encoding="utf-8")

    return str(folder)




def _content_library_dir(site_key: str | None = None) -> Path:
    """Return the approved local WordPress content-library folder for a site."""
    cfg = _config(site_key)
    site = cfg.get("site_key") or _site_key(site_key)
    path = Path(cfg.get("artifact_dir", "outputs/wordpress")) / "content-library" / site
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_content_filename(title: str, suffix: str = ".html") -> str:
    return _slugify(title) + suffix



def _content_library_media_dir(site_key: str | None = None) -> Path:
    """Return the approved local WordPress media folder for a site."""
    folder = _content_library_dir(site_key) / "media"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _assert_content_library_media_path(site_key: str | None, file_path: Path) -> Path:
    """Ensure media uploads come from the approved local media folder."""
    resolved = file_path.resolve()
    media_dir = _content_library_media_dir(site_key).resolve()

    try:
        resolved.relative_to(media_dir)
    except ValueError as exc:
        raise RuntimeError(
            f"Media file must be inside Serena's approved WordPress media library for this site: {media_dir}"
        ) from exc

    if not resolved.exists() or not resolved.is_file():
        raise RuntimeError(f"Media file not found: {resolved}")

    return resolved


def _copy_media_to_content_library(site_key: str | None, source_path: Path, title: str = "") -> str:
    """Copy an existing local media file into Serena's approved media folder."""
    if not source_path.exists() or not source_path.is_file():
        raise RuntimeError(f"Source media file not found: {source_path}")

    media_dir = _content_library_media_dir(site_key)
    suffix = source_path.suffix.lower() or ".bin"
    base = _slugify(title or source_path.stem)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = media_dir / f"{timestamp}-{base}{suffix}"

    target.write_bytes(source_path.read_bytes())
    return str(target)



def _write_content_library_file(
    site_key: str | None,
    title: str,
    content: str,
    content_type: str = "page",
    topic: str = "",
    seo_title: str = "",
    meta_description: str = "",
) -> str:
    """Store generated website content locally before upload/build."""
    out_dir = _content_library_dir(site_key)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{timestamp}-{_safe_content_filename(title)}"
    html_path = out_dir / filename
    meta_path = out_dir / filename.replace(".html", ".json")

    html_path.write_text(content, encoding="utf-8")

    metadata = {
        "site_key": _config(site_key).get("site_key"),
        "site_url": _config(site_key).get("site_url"),
        "title": title,
        "topic": topic,
        "content_type": content_type,
        "seo_title": seo_title,
        "meta_description": meta_description,
        "created_at": timestamp,
        "source": "serena_wordpress_content_library",
        "html_file": str(html_path),
    }

    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return str(html_path)


def _assert_content_library_path(site_key: str | None, file_path: Path) -> Path:
    """Ensure uploads/builds come from the approved local content library."""
    resolved = file_path.resolve()
    library = _content_library_dir(site_key).resolve()

    try:
        resolved.relative_to(library)
    except ValueError as exc:
        raise RuntimeError(
            f"File must be inside the approved WordPress content library for this site: {library}"
        ) from exc

    if not resolved.exists() or not resolved.is_file():
        raise RuntimeError(f"Content-library file not found: {resolved}")

    return resolved

def _snapshot_content(site_key: str | None, endpoint: str, content_id: int, reason: str) -> str:
    """Save a rollback snapshot before update/trash operations."""
    cfg = _config(site_key)
    site = cfg.get("site_key") or _site_key(site_key)
    out_dir = Path(cfg.get("artifact_dir", "outputs/wordpress")) / "rollback" / site
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    snapshot_path = out_dir / f"{timestamp}-{endpoint}-{content_id}-{_slugify(reason)}.json"

    item = _request("GET", f"{endpoint}/{content_id}?context=edit", site_key=site_key)
    if not isinstance(item, dict):
        raise RuntimeError("Could not snapshot WordPress content before operation.")

    content = str((item.get("content") or {}).get("rendered") or "")

    snapshot = {
        "snapshot_reason": reason,
        "snapshot_timestamp": timestamp,
        "site_key": site,
        "site_url": cfg.get("site_url"),
        "content_type": endpoint,
        "content_id": content_id,
        "title": _rendered(item.get("title")),
        "status": item.get("status"),
        "slug": item.get("slug"),
        "link": item.get("link"),
        "modified": item.get("modified") or item.get("modified_gmt"),
        "content_rendered": content,
        "raw": item,
    }

    snapshot_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return str(snapshot_path)

def _format_item(item: dict[str, Any]) -> str:
    title = _rendered(item.get("title"))
    return f"- {title or '(untitled)'} | ID {item.get('id')} | {item.get('status', '')} | {item.get('link', '')}"


class _WordPressBaseTool(BaseTool):
    is_local = False

    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=self.tool_id,
            content=content,
            success=success,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_wordpress_status")
class SerenaWordPressStatusTool(_WordPressBaseTool):
    tool_id = "serena_wordpress_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check whether Serena WordPress configuration is present and whether the WordPress REST API is reachable.",
            parameters={"type": "object", "properties": {"site_key": {"type": "string", "description": "WordPress site key, e.g. drpiet or serena."}}},
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        cfg = _config(site_key)
        ok, msg = _configured(site_key)
        if not ok:
            return self._result(
                "WordPress is not configured.\n" + msg,
                success=False,
                metadata={"configured": False, "missing": msg},
            )

        try:
            data = _request("GET", "users/me", site_key=site_key)
            content = (
                "WordPress status\n\n"
                f"- Site: {cfg.get('site_url') or cfg.get('rest_base_url') or 'not configured'}\n"
                f"- User: {_rendered(data.get('name')) or data.get('slug') or cfg['username']}\n"
                "- REST API: reachable\n"
                "- Auth: Application Password\n"
            )
            return self._result(content, metadata={"configured": True, "site": cfg.get("site_url"), "site_key": cfg.get("site_key")})
        except Exception as exc:
            return self._result(
                f"WordPress configured but unreachable or authentication failed: {exc}",
                success=False,
                metadata={"configured": True, "site": cfg.get("site_url"), "site_key": cfg.get("site_key"), "error": str(exc)},
            )


@ToolRegistry.register("serena_wordpress_list_posts")
class SerenaWordPressListPostsTool(_WordPressBaseTool):
    tool_id = "serena_wordpress_list_posts"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List recent WordPress posts from the configured WordPress site.",
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {"type": "string", "description": "WordPress site key, e.g. drpiet or serena. Defaults to WORDPRESS_DEFAULT_SITE."},
                    "limit": {"type": "integer", "description": "Number of posts to list."},
                    "status": {"type": "string", "description": "Post status filter, e.g. publish, draft, any."},
                    "search": {"type": "string", "description": "Optional search query."},
                },
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        site_key = str(params.get("site_key") or "").strip() or None
        limit = int(params.get("limit") or 10)
        status = str(params.get("status") or "any")
        search = str(params.get("search") or "").strip()
        query = f"posts?per_page={max(1, min(limit, 100))}&status={quote(status)}"
        if search:
            query += f"&search={quote(search)}"
        try:
            items = _request("GET", query, site_key=site_key)
            lines = [_format_item(item) for item in items] if isinstance(items, list) else []
            return self._result("WordPress posts\n\n" + ("\n".join(lines) or "No posts found."), metadata={"count": len(lines)})
        except Exception as exc:
            return self._result(f"Failed to list WordPress posts: {exc}", success=False)


@ToolRegistry.register("serena_wordpress_list_pages")
class SerenaWordPressListPagesTool(SerenaWordPressListPostsTool):
    tool_id = "serena_wordpress_list_pages"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List recent WordPress pages from the configured WordPress site.",
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {"type": "string", "description": "WordPress site key, e.g. drpiet or serena. Defaults to WORDPRESS_DEFAULT_SITE."},
                    "limit": {"type": "integer", "description": "Number of pages to list."},
                    "status": {"type": "string", "description": "Page status filter, e.g. publish, draft, any."},
                    "search": {"type": "string", "description": "Optional search query."},
                },
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        limit = int(params.get("limit") or 10)
        status = str(params.get("status") or "any")
        search = str(params.get("search") or "").strip()
        query = f"pages?per_page={max(1, min(limit, 100))}&status={quote(status)}"
        if search:
            query += f"&search={quote(search)}"
        try:
            items = _request("GET", query, site_key=site_key)
            lines = [_format_item(item) for item in items] if isinstance(items, list) else []
            return self._result("WordPress pages\n\n" + ("\n".join(lines) or "No pages found."), metadata={"count": len(lines)})
        except Exception as exc:
            return self._result(f"Failed to list WordPress pages: {exc}", success=False)


def _create_content(kind: str, title: str, content: str, status: str, slug: str = "", site_key: str | None = None) -> dict[str, Any]:
    cfg = _config(site_key)
    payload = {
        "title": title,
        "content": content,
        "status": status or "draft",
        "slug": slug or _slugify(title),
        "comment_status": cfg.get("default_comment_status", "open"),
        "ping_status": cfg.get("default_ping_status", "closed"),
    }

    if cfg.get("default_author_id"):
        payload["author"] = int(cfg["default_author_id"])
    if kind == "posts" and cfg.get("default_category_id"):
        payload["categories"] = [int(cfg["default_category_id"])]
    if cfg.get("default_featured_media_id"):
        payload["featured_media"] = int(cfg["default_featured_media_id"])
    endpoint = "posts" if kind == "posts" else "pages"
    result = _request("POST", endpoint, site_key=site_key, json=payload)
    if not isinstance(result, dict):
        raise RuntimeError("Unexpected WordPress response.")
    _save_artifact(endpoint, result, content=content)
    return result


@ToolRegistry.register("serena_wordpress_create_draft")
class SerenaWordPressCreateDraftTool(_WordPressBaseTool):
    tool_id = "serena_wordpress_create_draft"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a WordPress post draft. Use this for natural requests to draft a WordPress post. Publishing requires explicit separate approval.",
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {"type": "string", "description": "WordPress site key, e.g. drpiet or serena. Defaults to WORDPRESS_DEFAULT_SITE."},
                    "title": {"type": "string", "description": "Post title."},
                    "content": {"type": "string", "description": "HTML or plain content."},
                    "slug": {"type": "string", "description": "Optional slug."},
                },
                "required": ["title", "content"],
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        cfg = _config(site_key)
        title = str(params.get("title") or "").strip()
        content = str(params.get("content") or "").strip()
        slug = str(params.get("slug") or "").strip()
        if not title or not content:
            return self._result("Title and content are required to create a WordPress draft.", success=False)
        try:
            item = _create_content("posts", title, content, cfg.get("default_post_status", "draft"), slug, site_key=site_key)
            return self._result(
                "WordPress draft created\n\n" + _format_item(item),
                metadata={"id": item.get("id"), "link": item.get("link"), "status": item.get("status")},
            )
        except Exception as exc:
            return self._result(f"Failed to create WordPress draft: {exc}", success=False)


@ToolRegistry.register("serena_wordpress_create_page")
class SerenaWordPressCreatePageTool(SerenaWordPressCreateDraftTool):
    tool_id = "serena_wordpress_create_page"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a WordPress page, draft by default. Publishing requires explicit approval.",
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {"type": "string", "description": "WordPress site key, e.g. drpiet or serena. Defaults to WORDPRESS_DEFAULT_SITE."},
                    "title": {"type": "string", "description": "Page title."},
                    "content": {"type": "string", "description": "HTML or plain content."},
                    "status": {"type": "string", "description": "Status, default draft. Use publish only after explicit approval."},
                    "slug": {"type": "string", "description": "Optional slug."},
                },
                "required": ["title", "content"],
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        cfg = _config(site_key)
        title = str(params.get("title") or "").strip()
        content = str(params.get("content") or "").strip()
        status = str(params.get("status") or cfg.get("default_page_status", "draft")).strip()
        slug = str(params.get("slug") or "").strip()
        if status == "publish" and not bool(params.get("approved", False)):
            return self._result("Publishing a WordPress page requires explicit approval. Create as draft or pass approved=true after confirmation.", success=False)
        if not title or not content:
            return self._result("Title and content are required to create a WordPress page.", success=False)
        try:
            item = _create_content("pages", title, content, status, slug, site_key=site_key)
            return self._result("WordPress page created\n\n" + _format_item(item), metadata={"id": item.get("id"), "status": item.get("status")})
        except Exception as exc:
            return self._result(f"Failed to create WordPress page: {exc}", success=False)


@ToolRegistry.register("serena_wordpress_update_content")
class SerenaWordPressUpdateContentTool(_WordPressBaseTool):
    tool_id = "serena_wordpress_update_content"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Update an existing WordPress post or page. Requires approval for live/public content updates.",
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {"type": "string", "description": "WordPress site key, e.g. drpiet or serena. Defaults to WORDPRESS_DEFAULT_SITE."},
                    "content_id": {"type": "integer", "description": "WordPress post/page ID."},
                    "content_type": {"type": "string", "description": "posts or pages."},
                    "title": {"type": "string", "description": "Optional title."},
                    "content": {"type": "string", "description": "Optional content."},
                    "status": {"type": "string", "description": "Optional status."},
                    "approved": {"type": "boolean", "description": "True only after explicit user approval."},
                },
                "required": ["content_id"],
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        content_id = int(params.get("content_id") or 0)
        content_type = str(params.get("content_type") or "posts").strip()
        approved = bool(params.get("approved", False))
        if not content_id:
            return self._result("content_id is required.", success=False)
        # Trusted operator mode:
        # Updates are allowed without extra approval.
        # Publishing still requires explicit approval.

        payload: dict[str, Any] = {}
        for key in ("title", "content", "status"):
            value = params.get(key)
            if value:
                payload[key] = value

        if not payload:
            return self._result("No update fields provided.", success=False)

        if str(payload.get("status", "")).lower() == "publish" and not approved:
            return self._result(
                "Publishing requires explicit approval. Re-run with approved=true only after the user confirms publishing.",
                success=False,
            )

        endpoint = "pages" if content_type == "pages" else "posts"
        try:
            snapshot_path = _snapshot_content(site_key, endpoint, content_id, "before-update")
            item = _request("POST", f"{endpoint}/{content_id}", site_key=site_key, json=payload)
            if isinstance(item, dict):
                _save_artifact(endpoint, item, content=str(payload.get("content") or ""))
                return self._result(
                    "WordPress content updated\n\n" + _format_item(item) + f"\n\nRollback snapshot: {snapshot_path}",
                    metadata={"id": item.get("id"), "rollback_snapshot": snapshot_path},
                )
            return self._result("Unexpected WordPress response.", success=False)
        except Exception as exc:
            return self._result(f"Failed to update WordPress content: {exc}", success=False)


@ToolRegistry.register("serena_wordpress_search")
class SerenaWordPressSearchTool(_WordPressBaseTool):
    tool_id = "serena_wordpress_search"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Search WordPress posts and pages by text query.",
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {"type": "string", "description": "WordPress site key, e.g. drpiet or serena. Defaults to WORDPRESS_DEFAULT_SITE."},
                    "query": {"type": "string", "description": "Search query."},
                    "limit": {"type": "integer", "description": "Max results per content type."},
                },
                "required": ["query"],
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        query = str(params.get("query") or "").strip()
        limit = int(params.get("limit") or 5)
        if not query:
            return self._result("Search query is required.", success=False)
        try:
            posts = _request("GET", f"posts?per_page={limit}&status=any&search={quote(query)}", site_key=site_key)
            pages = _request("GET", f"pages?per_page={limit}&status=any&search={quote(query)}", site_key=site_key)
            lines = ["Posts:"]
            lines += [_format_item(item) for item in posts] if isinstance(posts, list) else []
            lines += ["", "Pages:"]
            lines += [_format_item(item) for item in pages] if isinstance(pages, list) else []
            return self._result("WordPress search results\n\n" + "\n".join(lines))
        except Exception as exc:
            return self._result(f"Failed to search WordPress: {exc}", success=False)


@ToolRegistry.register("serena_wordpress_upload_media")
class SerenaWordPressUploadMediaTool(_WordPressBaseTool):
    tool_id = "serena_wordpress_upload_media"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Upload a media file to WordPress after explicit approval.",
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {"type": "string", "description": "WordPress site key, e.g. drpiet or serena. Defaults to WORDPRESS_DEFAULT_SITE."},
                    "path": {"type": "string", "description": "Local media file path."},
                    "title": {"type": "string", "description": "Optional media title."},
                    "alt_text": {"type": "string", "description": "Optional alt text."},
                    "approved": {"type": "boolean", "description": "True only after explicit user approval."},
                },
                "required": ["path"],
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        # Trusted operator mode: media upload from approved local/content-library paths is allowed.
        try:
            file_path = _assert_content_library_media_path(site_key, Path(str(params.get("path") or "")))
        except Exception as exc:
            return self._result(f"Media upload blocked: {exc}", success=False)

        headers = _headers(site_key)
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        headers.update(
            {
                "Content-Disposition": f'attachment; filename="{file_path.name}"',
                "Content-Type": content_type,
                "Accept": "application/json",
            }
        )

        try:
            data = file_path.read_bytes()
            item = _request("POST", "media", site_key=site_key, headers=headers, data=data)
            if isinstance(item, dict):
                updates = {}
                if params.get("title"):
                    updates["title"] = params.get("title")
                if params.get("alt_text"):
                    updates["alt_text"] = params.get("alt_text")
                if updates and item.get("id"):
                    item = _request("POST", f"media/{item['id']}", site_key=site_key, json=updates)
                return self._result("WordPress media uploaded\n\n" + _format_item(item), metadata={"id": item.get("id"), "link": item.get("link")})
            return self._result("Unexpected WordPress response.", success=False)
        except Exception as exc:
            return self._result(f"Failed to upload media: {exc}", success=False)


@ToolRegistry.register("serena_wordpress_audit_content")
class SerenaWordPressAuditContentTool(_WordPressBaseTool):
    tool_id = "serena_wordpress_audit_content"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Perform a lightweight SEO/readability/compliance audit of proposed WordPress content without publishing.",
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {"type": "string", "description": "WordPress site key, e.g. drpiet or serena. Defaults to WORDPRESS_DEFAULT_SITE."},
                    "title": {"type": "string", "description": "Content title."},
                    "content": {"type": "string", "description": "Content body."},
                    "keyword": {"type": "string", "description": "Optional target keyword."},
                    "healthcare": {"type": "boolean", "description": "Whether this is healthcare/medical content."},
                },
                "required": ["title", "content"],
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        cfg = _config(site_key)
        title = str(params.get("title") or "")
        content = str(params.get("content") or "")
        keyword = str(params.get("keyword") or "").lower().strip()
        healthcare = bool(params.get("healthcare", True))

        words = re.findall(r"\b\w+\b", content)
        word_count = len(words)
        title_len = len(title)
        keyword_hits = content.lower().count(keyword) if keyword else 0

        findings = []
        if title_len < 25:
            findings.append("- Title may be too short for SEO clarity.")
        if title_len > 70:
            findings.append("- Title may be too long for search snippets.")
        if word_count < 300:
            findings.append("- Content is short; consider expanding if this is intended as a full article.")
        if keyword and keyword_hits == 0:
            findings.append(f"- Target keyword '{keyword}' does not appear in the body.")
        if healthcare:
            findings.append("- Healthcare content should be reviewed by Dr Piet/clinician before publishing.")
            findings.append("- Avoid unsupported clinical claims and include appropriate disclaimers where needed.")

        if not findings:
            findings.append("- No major lightweight audit issues found.")

        content_out = (
            "WordPress content audit\n\n"
            f"- Title length: {title_len}\n"
            f"- Word count: {word_count}\n"
            f"- Site: {cfg.get('site_key')} ({cfg.get('site_url')})\n"
            f"- Primary CTA: {cfg.get('primary_cta') or 'not configured'}\n"
            f"- Booking URL: {cfg.get('booking_url') or 'not configured'}\n"
            f"- Target keyword hits: {keyword_hits if keyword else 'not provided'}\n\n"
            "Findings:\n" + "\n".join(findings)
        )

        return self._result(content_out, metadata={"word_count": word_count, "title_length": title_len, "keyword_hits": keyword_hits})


@ToolRegistry.register("serena_wordpress_build_page_plan")
class SerenaWordPressBuildPagePlanTool(_WordPressBaseTool):
    tool_id = "serena_wordpress_build_page_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Build a WordPress page or landing-page blueprint before creating content. "
                "Use for website-building requests, service pages, landing pages, SEO page plans, "
                "and medical/practice website content planning."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {
                        "type": "string",
                        "description": "WordPress site key, e.g. drpiet or serena. Defaults to WORDPRESS_DEFAULT_SITE.",
                    },
                    "page_type": {
                        "type": "string",
                        "description": "Type of page, e.g. service page, landing page, about page, resource page.",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Main page topic or service.",
                    },
                    "audience": {
                        "type": "string",
                        "description": "Target audience for the page.",
                    },
                    "goal": {
                        "type": "string",
                        "description": "Primary conversion goal.",
                    },
                    "healthcare": {
                        "type": "boolean",
                        "description": "Whether this is healthcare/medical content requiring clinical review.",
                    },
                },
                "required": ["topic"],
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        cfg = _config(site_key)

        topic = str(params.get("topic") or "").strip()
        page_type = str(params.get("page_type") or "landing page").strip()
        audience = str(params.get("audience") or "website visitors").strip()
        goal = str(params.get("goal") or cfg.get("primary_cta") or "Book your consultation").strip()
        healthcare = bool(params.get("healthcare", True))

        if not topic:
            return self._result("A topic is required to build a WordPress page plan.", success=False)

        title = topic.strip()
        slug = _slugify(title)

        cta = cfg.get("primary_cta") or goal
        booking_url = cfg.get("booking_url") or ""
        lead_magnet_url = cfg.get("lead_magnet_url") or ""
        membership_url = cfg.get("membership_url") or ""
        corporate_url = cfg.get("corporate_wellness_url") or ""

        sections = [
            f"Hero: clear promise around {topic}",
            "Problem/context: explain the visitor's situation in plain language",
            "Solution/service: explain how Dr Piet or the site can help",
            "Benefits: list practical outcomes without overpromising",
            "Process: explain what happens next",
            "Trust: credentials, experience, reviews, or proof points",
            "FAQ: answer common objections and questions",
            f"CTA: {cta}",
        ]

        if healthcare:
            sections.append("Clinical safety note: include review language and avoid guaranteed outcomes.")

        internal_links = []
        if booking_url:
            internal_links.append(f"Booking: {booking_url}")
        if lead_magnet_url:
            internal_links.append(f"Lead magnet: {lead_magnet_url}")
        if membership_url:
            internal_links.append(f"Membership: {membership_url}")
        if corporate_url:
            internal_links.append(f"Corporate wellness: {corporate_url}")

        seo_title = f"{title} | Dr Piet Muller" if cfg.get("site_key") == "drpiet" else title
        meta = f"Learn about {topic} and the next steps available through {cfg.get('site_url') or 'the website'}."

        lines = [
            "WordPress website/page build plan",
            "",
            f"- Site: {cfg.get('site_key')} ({cfg.get('site_url') or 'not configured'})",
            f"- Page type: {page_type}",
            f"- Audience: {audience}",
            f"- Goal: {goal}",
            f"- Recommended status: draft",
            "",
            "Page basics:",
            f"- Title: {title}",
            f"- Slug: {slug}",
            f"- SEO title: {seo_title}",
            f"- Meta description: {meta}",
            "",
            "Recommended page structure:",
        ]

        lines.extend(f"- {section}" for section in sections)

        lines.extend([
            "",
            "Internal links / CTAs:",
        ])

        if internal_links:
            lines.extend(f"- {link}" for link in internal_links)
        else:
            lines.append("- No business URLs configured yet.")

        lines.extend([
            "",
            "Approval and safety:",
            "- Create as draft first.",
            "- Ask for explicit approval before publishing.",
            "- Ask for explicit approval before updating live public content.",
        ])

        if healthcare:
            lines.extend([
                "- Healthcare/medical content requires Dr Piet or clinician review before publishing.",
                "- Avoid unsupported clinical claims and guaranteed outcomes.",
            ])

        return self._result(
            "\n".join(lines),
            metadata={
                "site_key": cfg.get("site_key"),
                "title": title,
                "slug": slug,
                "seo_title": seo_title,
                "meta_description": meta,
                "recommended_status": "draft",
                "healthcare": healthcare,
            },
        )


@ToolRegistry.register("serena_wordpress_get_content")
class SerenaWordPressGetContentTool(_WordPressBaseTool):
    tool_id = "serena_wordpress_get_content"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Get a WordPress post or page by ID, including rendered title, status, link, excerpt, and optional content.",
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {
                        "type": "string",
                        "description": "WordPress site key, e.g. drpiet or serena. Defaults to WORDPRESS_DEFAULT_SITE.",
                    },
                    "content_type": {
                        "type": "string",
                        "description": "Content type: posts or pages.",
                    },
                    "content_id": {
                        "type": "integer",
                        "description": "WordPress post/page ID.",
                    },
                    "include_content": {
                        "type": "boolean",
                        "description": "Include rendered HTML content in the output.",
                    },
                },
                "required": ["content_id"],
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        content_type = str(params.get("content_type") or "pages").strip().lower()
        content_id = int(params.get("content_id") or 0)
        include_content = bool(params.get("include_content", False))

        if not content_id:
            return self._result("content_id is required.", success=False)

        endpoint = "posts" if content_type == "posts" else "pages"

        try:
            item = _request("GET", f"{endpoint}/{content_id}?context=edit", site_key=site_key)
            if not isinstance(item, dict):
                return self._result("Unexpected WordPress response.", success=False)

            title = _rendered(item.get("title"))
            excerpt = _rendered(item.get("excerpt"))
            content = str((item.get("content") or {}).get("rendered") or "")

            lines = [
                "WordPress content",
                "",
                f"- Site: {_config(site_key).get('site_key')} ({_config(site_key).get('site_url')})",
                f"- Type: {endpoint}",
                f"- ID: {item.get('id')}",
                f"- Title: {title or '(untitled)'}",
                f"- Status: {item.get('status')}",
                f"- Link: {item.get('link') or ''}",
                f"- Slug: {item.get('slug') or ''}",
                f"- Modified: {item.get('modified') or item.get('modified_gmt') or ''}",
                "",
                "Excerpt:",
                excerpt or "(none)",
            ]

            if include_content:
                lines.extend(["", "Rendered content:", content or "(empty)"])

            return self._result(
                "\n".join(lines),
                metadata={
                    "site_key": _config(site_key).get("site_key"),
                    "content_type": endpoint,
                    "content_id": item.get("id"),
                    "status": item.get("status"),
                    "link": item.get("link"),
                    "slug": item.get("slug"),
                    "title": title,
                },
            )

        except Exception as exc:
            return self._result(f"Failed to get WordPress content: {exc}", success=False)


@ToolRegistry.register("serena_wordpress_inspect_content")
class SerenaWordPressInspectContentTool(_WordPressBaseTool):
    tool_id = "serena_wordpress_inspect_content"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Inspect a WordPress post or page like a developer/operator. Checks content completeness, SEO basics, "
                "UX structure, CTA presence, links, media, healthcare compliance, status, and next actions."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {
                        "type": "string",
                        "description": "WordPress site key, e.g. drpiet or serena. Defaults to WORDPRESS_DEFAULT_SITE.",
                    },
                    "content_type": {
                        "type": "string",
                        "description": "Content type: posts or pages.",
                    },
                    "content_id": {
                        "type": "integer",
                        "description": "WordPress post/page ID.",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "Optional target SEO keyword.",
                    },
                    "healthcare": {
                        "type": "boolean",
                        "description": "Whether healthcare/medical compliance review is needed.",
                    },
                },
                "required": ["content_id"],
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        cfg = _config(site_key)
        content_type = str(params.get("content_type") or "pages").strip().lower()
        content_id = int(params.get("content_id") or 0)
        keyword = str(params.get("keyword") or "").strip().lower()
        healthcare = bool(params.get("healthcare", True))

        if not content_id:
            return self._result("content_id is required.", success=False)

        endpoint = "posts" if content_type == "posts" else "pages"

        try:
            item = _request("GET", f"{endpoint}/{content_id}?context=edit", site_key=site_key)
            if not isinstance(item, dict):
                return self._result("Unexpected WordPress response.", success=False)

            title = _rendered(item.get("title"))
            slug = str(item.get("slug") or "")
            status = str(item.get("status") or "")
            link = str(item.get("link") or "")
            raw_content = str((item.get("content") or {}).get("rendered") or "")
            featured_media_id = int(item.get("featured_media") or 0)
            featured_media_status = "yes" if featured_media_id else "no"
            text_content = _rendered(raw_content)
            words = re.findall(r"\b\w+\b", text_content)

            headings = re.findall(r"<h([1-6])[^>]*>(.*?)</h\1>", raw_content, flags=re.I | re.S)
            links = re.findall(r"<a\s+[^>]*href=[\"']([^\"']+)[\"']", raw_content, flags=re.I)
            images = re.findall(r"<img\s+[^>]*>", raw_content, flags=re.I)
            missing_alt = [img for img in images if "alt=" not in img.lower() or 'alt=""' in img.lower() or "alt=''" in img.lower()]

            keyword_hits = text_content.lower().count(keyword) if keyword else 0
            has_cta = any(
                phrase.lower() in text_content.lower()
                for phrase in [
                    cfg.get("primary_cta") or "",
                    "book",
                    "contact",
                    "consultation",
                    "call",
                    "learn more",
                    "get started",
                ]
                if phrase
            )

            findings = []
            recommendations = []

            if not title:
                findings.append("Missing title.")
            elif len(title) < 25:
                recommendations.append("Consider a clearer, longer SEO-friendly title.")
            elif len(title) > 70:
                recommendations.append("Title may be too long for search snippets.")

            if not slug:
                findings.append("Missing slug.")
            if len(words) < 250:
                recommendations.append("Content is short for a complete page/post. Expand if this is intended as a full public page.")
            if not headings:
                findings.append("No visible heading structure found.")
            else:
                h_levels = [h[0] for h in headings]
                if "1" not in h_levels:
                    recommendations.append("No H1 detected in rendered content. Confirm theme supplies H1 or add one.")
                if "2" not in h_levels:
                    recommendations.append("No H2 sections detected. Add section headings for readability and SEO.")

            if not has_cta:
                findings.append("No clear call-to-action detected.")
            if not links:
                recommendations.append("No internal/external links detected. Add relevant internal links where useful.")
            if images and missing_alt:
                findings.append(f"{len(missing_alt)} image(s) may be missing useful alt text.")
            if keyword and keyword_hits == 0:
                findings.append(f"Target keyword '{keyword}' not found in visible text.")
            if status == "publish":
                recommendations.append("This content is live. Require approval before changing it.")
            if healthcare:
                recommendations.append("Healthcare/medical content requires clinician review before publishing.")
                recommendations.append("Avoid unsupported clinical claims, guaranteed outcomes, or patient-specific advice.")

            if not findings:
                findings.append("No critical developer/operator issues found in the lightweight inspection.")

            if not recommendations:
                recommendations.append("No major recommendations from the lightweight inspection.")

            lines = [
                "WordPress developer/operator inspection",
                "",
                "Content identity:",
                f"- Site: {cfg.get('site_key')} ({cfg.get('site_url')})",
                f"- Type: {endpoint}",
                f"- ID: {item.get('id')}",
                f"- Title: {title or '(untitled)'}",
                f"- Status: {status}",
                f"- Link: {link}",
                f"- Slug: {slug}",
                f"- Modified: {item.get('modified') or item.get('modified_gmt') or ''}",
                "",
                "Developer checks:",
                f"- Word count: {len(words)}",
                f"- Headings found: {len(headings)}",
                f"- Links found: {len(links)}",
                f"- Inline images found: {len(images)}",
                f"- Inline images missing alt text: {len(missing_alt)}",
                f"- Featured image assigned: {featured_media_status}",
                f"- Featured media ID: {featured_media_id if featured_media_id else 'none'}",
                f"- CTA detected: {'yes' if has_cta else 'no'}",
                f"- Target keyword hits: {keyword_hits if keyword else 'not provided'}",
                "",
                "Findings:",
            ]

            lines.extend(f"- {item}" for item in findings)
            lines.append("")
            lines.append("Recommendations:")
            lines.extend(f"- {item}" for item in recommendations)

            lines.extend([
                "",
                "Next action:",
                "- If this is a draft, revise based on findings before publishing.",
                "- If this is live, ask for explicit approval before changing it.",
                "- Save a rollback snapshot before any update.",
            ])

            return self._result(
                "\n".join(lines),
                metadata={
                    "site_key": cfg.get("site_key"),
                    "content_type": endpoint,
                    "content_id": item.get("id"),
                    "status": status,
                    "word_count": len(words),
                    "headings": len(headings),
                    "links": len(links),
                    "images": len(images),
                    "missing_alt": len(missing_alt),
                    "featured_media_id": featured_media_id,
                    "featured_image_assigned": bool(featured_media_id),
                    "cta_detected": has_cta,
                    "keyword_hits": keyword_hits,
                },
            )

        except Exception as exc:
            return self._result(f"Failed to inspect WordPress content: {exc}", success=False)


@ToolRegistry.register("serena_wordpress_trash_content")
class SerenaWordPressTrashContentTool(_WordPressBaseTool):
    tool_id = "serena_wordpress_trash_content"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Move a WordPress post/page to trash in trusted operator mode. "
                "This is soft-trash only, not permanent deletion. A rollback snapshot is saved first."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {
                        "type": "string",
                        "description": "WordPress site key, e.g. drpiet or serena. Defaults to WORDPRESS_DEFAULT_SITE.",
                    },
                    "content_type": {
                        "type": "string",
                        "description": "Content type: posts or pages.",
                    },
                    "content_id": {
                        "type": "integer",
                        "description": "WordPress post/page ID.",
                    },
                },
                "required": ["content_id"],
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        content_type = str(params.get("content_type") or "pages").strip().lower()
        content_id = int(params.get("content_id") or 0)

        if not content_id:
            return self._result("content_id is required.", success=False)

        endpoint = "posts" if content_type == "posts" else "pages"

        try:
            snapshot_path = _snapshot_content(site_key, endpoint, content_id, "before-trash")
            item = _request("DELETE", f"{endpoint}/{content_id}?force=false", site_key=site_key)

            return self._result(
                "WordPress content moved to trash. Permanent deletion was not performed."
                f"\n\n- Site: {_config(site_key).get('site_key')} ({_config(site_key).get('site_url')})"
                f"\n- Type: {endpoint}"
                f"\n- ID: {content_id}"
                f"\n- Rollback snapshot: {snapshot_path}",
                metadata={
                    "site_key": _config(site_key).get("site_key"),
                    "content_type": endpoint,
                    "content_id": content_id,
                    "rollback_snapshot": snapshot_path,
                    "wordpress_response": item,
                },
            )
        except Exception as exc:
            return self._result(f"Failed to move WordPress content to trash: {exc}", success=False)


@ToolRegistry.register("serena_wordpress_content_create")
class SerenaWordPressContentCreateTool(_WordPressBaseTool):
    tool_id = "serena_wordpress_content_create"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Create and store WordPress-ready website content in Serena's approved local content library. "
                "Use this before creating or updating WordPress from generated content."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {"type": "string", "description": "Site key, e.g. drpiet or serena."},
                    "title": {"type": "string", "description": "Content/page title."},
                    "topic": {"type": "string", "description": "Main topic."},
                    "content_type": {"type": "string", "description": "page or post."},
                    "audience": {"type": "string", "description": "Target audience."},
                    "goal": {"type": "string", "description": "Conversion goal."},
                    "healthcare": {"type": "boolean", "description": "Add healthcare compliance language."},
                    "content": {"type": "string", "description": "Optional explicit HTML content. If omitted, Serena generates a structured starter page."}
                },
                "required": ["title"],
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        cfg = _config(site_key)

        title = str(params.get("title") or "").strip()
        topic = str(params.get("topic") or title).strip()
        content_type = str(params.get("content_type") or "page").strip().lower()
        audience = str(params.get("audience") or "website visitors").strip()
        goal = str(params.get("goal") or cfg.get("primary_cta") or "Book your consultation").strip()
        healthcare = bool(params.get("healthcare", True))
        explicit_content = str(params.get("content") or "").strip()

        if not title:
            return self._result("Title is required.", success=False)

        seo_title = f"{title} | Dr Piet Muller" if cfg.get("site_key") == "drpiet" else title
        meta_description = f"Learn about {topic} and the next steps available through {cfg.get('site_url') or 'the website'}."

        if explicit_content:
            html_content = explicit_content
        else:
            compliance = ""
            if healthcare:
                compliance = (
                    "<h2>Important note</h2>"
                    "<p>This content is for education and should be reviewed by Dr Piet or a qualified clinician before publishing.</p>"
                )

            html_content = f"""<h1>{html.escape(title)}</h1>
<p>This page is prepared for {html.escape(audience)} with the goal: {html.escape(goal)}.</p>

<h2>Overview</h2>
<p>{html.escape(topic)} is introduced here in clear, practical language.</p>

<h2>How this helps</h2>
<p>This section explains the service, benefit, or resource without overpromising outcomes.</p>

<h2>Next steps</h2>
<p>{html.escape(goal)}</p>
{compliance}
"""

        file_path = _write_content_library_file(
            site_key=site_key,
            title=title,
            content=html_content,
            content_type=content_type,
            topic=topic,
            seo_title=seo_title,
            meta_description=meta_description,
        )

        return self._result(
            "WordPress content-library file created\n\n"
            f"- Site: {cfg.get('site_key')} ({cfg.get('site_url')})\n"
            f"- Title: {title}\n"
            f"- Type: {content_type}\n"
            f"- File: {file_path}\n"
            f"- SEO title: {seo_title}\n"
            f"- Meta description: {meta_description}",
            metadata={
                "site_key": cfg.get("site_key"),
                "title": title,
                "content_type": content_type,
                "file": file_path,
                "seo_title": seo_title,
                "meta_description": meta_description,
            },
        )


@ToolRegistry.register("serena_wordpress_content_list")
class SerenaWordPressContentListTool(_WordPressBaseTool):
    tool_id = "serena_wordpress_content_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List stored WordPress content-library files for a site.",
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {"type": "string", "description": "Site key, e.g. drpiet or serena."},
                    "limit": {"type": "integer", "description": "Maximum files to show."}
                },
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        limit = int(params.get("limit") or 20)
        folder = _content_library_dir(site_key)

        files = sorted(folder.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]

        if not files:
            return self._result(f"No content-library files found in {folder}", metadata={"folder": str(folder), "count": 0})

        lines = ["WordPress content-library files", "", f"Folder: {folder}", ""]
        for file in files:
            lines.append(f"- {file.name}")

        return self._result("\n".join(lines), metadata={"folder": str(folder), "count": len(files)})


@ToolRegistry.register("serena_wordpress_content_inspect")
class SerenaWordPressContentInspectTool(_WordPressBaseTool):
    tool_id = "serena_wordpress_content_inspect"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect a local WordPress content-library HTML file before upload/build.",
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {"type": "string", "description": "Site key, e.g. drpiet or serena."},
                    "path": {"type": "string", "description": "Path to HTML file inside approved content library."},
                    "keyword": {"type": "string", "description": "Optional target keyword."},
                    "healthcare": {"type": "boolean", "description": "Whether healthcare review is required."}
                },
                "required": ["path"],
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        keyword = str(params.get("keyword") or "").strip().lower()
        healthcare = bool(params.get("healthcare", True))

        try:
            file_path = _assert_content_library_path(site_key, Path(str(params.get("path") or "")))
            raw_content = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            return self._result(f"Failed to inspect content-library file: {exc}", success=False)

        text_content = _rendered(raw_content)
        words = re.findall(r"\b\w+\b", text_content)
        headings = re.findall(r"<h([1-6])[^>]*>(.*?)</h\1>", raw_content, flags=re.I | re.S)
        links = re.findall(r"<a\s+[^>]*href=[\"']([^\"']+)[\"']", raw_content, flags=re.I)
        images = re.findall(r"<img\s+[^>]*>", raw_content, flags=re.I)
        keyword_hits = text_content.lower().count(keyword) if keyword else 0
        has_cta = any(x in text_content.lower() for x in ["book", "contact", "consultation", "learn more", "get started"])

        findings = []
        recommendations = []

        if len(words) < 250:
            recommendations.append("Content is short for a complete public page. Expand before publishing.")
        if not headings:
            findings.append("No heading structure found.")
        if not has_cta:
            findings.append("No clear CTA detected.")
        if not links:
            recommendations.append("No links detected. Add internal links where useful.")
        if images:
            missing_alt = [img for img in images if "alt=" not in img.lower() or 'alt=""' in img.lower() or "alt=''" in img.lower()]
            if missing_alt:
                findings.append(f"{len(missing_alt)} image(s) may be missing useful alt text.")
        if keyword and keyword_hits == 0:
            findings.append(f"Target keyword '{keyword}' not found.")
        if healthcare:
            recommendations.append("Healthcare content should be reviewed by Dr Piet/clinician before publishing.")

        if not findings:
            findings.append("No critical content-library issues found.")

        lines = [
            "WordPress local content inspection",
            "",
            f"- File: {file_path}",
            f"- Word count: {len(words)}",
            f"- Headings found: {len(headings)}",
            f"- Links found: {len(links)}",
            f"- Images found: {len(images)}",
            f"- CTA detected: {'yes' if has_cta else 'no'}",
            f"- Target keyword hits: {keyword_hits if keyword else 'not provided'}",
            "",
            "Findings:",
        ]
        lines.extend(f"- {item}" for item in findings)
        lines.append("")
        lines.append("Recommendations:")
        lines.extend(f"- {item}" for item in recommendations or ["No major recommendations."])

        return self._result("\n".join(lines), metadata={"file": str(file_path), "word_count": len(words)})


@ToolRegistry.register("serena_wordpress_build_page_from_library")
class SerenaWordPressBuildPageFromLibraryTool(_WordPressBaseTool):
    tool_id = "serena_wordpress_build_page_from_library"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a WordPress draft page from an approved local content-library HTML file, then inspect the draft.",
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {"type": "string", "description": "Site key, e.g. drpiet or serena."},
                    "path": {"type": "string", "description": "Path to HTML file inside approved content library."},
                    "title": {"type": "string", "description": "Page title."},
                    "slug": {"type": "string", "description": "Optional page slug."},
                    "keyword": {"type": "string", "description": "Optional target keyword."},
                    "healthcare": {"type": "boolean", "description": "Whether healthcare review is required."}
                },
                "required": ["path", "title"],
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        title = str(params.get("title") or "").strip()
        slug = str(params.get("slug") or "").strip()
        keyword = str(params.get("keyword") or "").strip()
        healthcare = bool(params.get("healthcare", True))

        if not title:
            return self._result("Title is required.", success=False)

        try:
            file_path = _assert_content_library_path(site_key, Path(str(params.get("path") or "")))
            content = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            return self._result(f"Failed to build page from content-library file: {exc}", success=False)

        create_result = SerenaWordPressCreatePageTool().execute(
            site_key=site_key,
            title=title,
            content=content,
            slug=slug,
            status="draft",
            approved=False,
        )

        if not create_result.success:
            return create_result

        page_id = create_result.metadata.get("id")
        inspect_result = None
        if page_id:
            inspect_result = SerenaWordPressInspectContentTool().execute(
                site_key=site_key,
                content_type="pages",
                content_id=int(page_id),
                keyword=keyword,
                healthcare=healthcare,
            )

        output = [
            "WordPress draft page built from content library",
            "",
            create_result.content,
        ]

        if inspect_result:
            output.extend(["", "Post-build developer inspection:", "", inspect_result.content])

        return self._result(
            "\n".join(output),
            metadata={
                "site_key": _config(site_key).get("site_key"),
                "source_file": str(file_path),
                "page_id": page_id,
                "inspection_success": bool(inspect_result and inspect_result.success),
            },
        )


@ToolRegistry.register("serena_wordpress_media_import")
class SerenaWordPressMediaImportTool(_WordPressBaseTool):
    tool_id = "serena_wordpress_media_import"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Copy a local media file into Serena's approved WordPress content-library media folder for a site.",
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {"type": "string", "description": "Site key, e.g. drpiet or serena."},
                    "source_path": {"type": "string", "description": "Existing local media file to copy into the approved media folder."},
                    "title": {"type": "string", "description": "Optional media title/name."}
                },
                "required": ["source_path"],
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        source_path = Path(str(params.get("source_path") or ""))
        title = str(params.get("title") or "").strip()

        try:
            target = _copy_media_to_content_library(site_key, source_path, title=title)
            return self._result(
                "Media imported into Serena WordPress content library\n\n"
                f"- Site: {_config(site_key).get('site_key')} ({_config(site_key).get('site_url')})\n"
                f"- Source: {source_path}\n"
                f"- Approved media path: {target}",
                metadata={"site_key": _config(site_key).get("site_key"), "path": target},
            )
        except Exception as exc:
            return self._result(f"Failed to import media: {exc}", success=False)


@ToolRegistry.register("serena_wordpress_set_featured_image")
class SerenaWordPressSetFeaturedImageTool(_WordPressBaseTool):
    tool_id = "serena_wordpress_set_featured_image"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Set a WordPress media item as the featured image for a post or page. Saves rollback snapshot first.",
            parameters={
                "type": "object",
                "properties": {
                    "site_key": {"type": "string", "description": "Site key, e.g. drpiet or serena."},
                    "content_type": {"type": "string", "description": "posts or pages."},
                    "content_id": {"type": "integer", "description": "WordPress post/page ID."},
                    "media_id": {"type": "integer", "description": "WordPress media ID to use as featured image."}
                },
                "required": ["content_id", "media_id"],
            },
            category="serena_wordpress",
        )

    def execute(self, **params: Any) -> ToolResult:
        site_key = str(params.get("site_key") or "").strip() or None
        content_type = str(params.get("content_type") or "pages").strip().lower()
        content_id = int(params.get("content_id") or 0)
        media_id = int(params.get("media_id") or 0)

        if not content_id or not media_id:
            return self._result("content_id and media_id are required.", success=False)

        endpoint = "posts" if content_type == "posts" else "pages"

        try:
            snapshot_path = _snapshot_content(site_key, endpoint, content_id, "before-featured-image")
            item = _request(
                "POST",
                f"{endpoint}/{content_id}",
                site_key=site_key,
                json={"featured_media": media_id},
            )

            if not isinstance(item, dict):
                return self._result("Unexpected WordPress response while setting featured image.", success=False)

            return self._result(
                "Featured image assigned\n\n"
                f"- Site: {_config(site_key).get('site_key')} ({_config(site_key).get('site_url')})\n"
                f"- Type: {endpoint}\n"
                f"- Content ID: {content_id}\n"
                f"- Media ID: {media_id}\n"
                f"- Rollback snapshot: {snapshot_path}",
                metadata={
                    "site_key": _config(site_key).get("site_key"),
                    "content_type": endpoint,
                    "content_id": content_id,
                    "media_id": media_id,
                    "rollback_snapshot": snapshot_path,
                },
            )
        except Exception as exc:
            return self._result(f"Failed to set featured image: {exc}", success=False)


__all__ = [
    "SerenaWordPressStatusTool",
    "SerenaWordPressListPostsTool",
    "SerenaWordPressListPagesTool",
    "SerenaWordPressCreateDraftTool",
    "SerenaWordPressCreatePageTool",
    "SerenaWordPressUpdateContentTool",
    "SerenaWordPressSearchTool",
    "SerenaWordPressUploadMediaTool",
    "SerenaWordPressAuditContentTool",
    "SerenaWordPressBuildPagePlanTool",
    "SerenaWordPressGetContentTool",
    "SerenaWordPressInspectContentTool",
    "SerenaWordPressTrashContentTool",
    "SerenaWordPressBuildPageFromLibraryTool",
    "SerenaWordPressSetFeaturedImageTool",
    "SerenaWordPressMediaImportTool",
    "SerenaWordPressContentInspectTool",
    "SerenaWordPressContentListTool",
    "SerenaWordPressContentCreateTool",
]
