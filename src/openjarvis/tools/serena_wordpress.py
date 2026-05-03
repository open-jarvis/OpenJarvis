"""Serena WordPress native tools.

Converted and upgraded from legacy Serena `13-wordpress.js`.

These tools use WordPress REST API with Application Password authentication.
They keep the UX natural-language first and apply safe defaults:
drafts by default, explicit approval for publishing/live updates.
"""

from __future__ import annotations

import base64
import html
import json
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
        if not approved:
            return self._result("Updating WordPress content requires explicit approval. Confirm the exact change first.", success=False)

        payload: dict[str, Any] = {}
        for key in ("title", "content", "status"):
            value = params.get(key)
            if value:
                payload[key] = value

        if not payload:
            return self._result("No update fields provided.", success=False)

        endpoint = "pages" if content_type == "pages" else "posts"
        try:
            item = _request("POST", f"{endpoint}/{content_id}", site_key=site_key, json=payload)
            if isinstance(item, dict):
                _save_artifact(endpoint, item, content=str(payload.get("content") or ""))
                return self._result("WordPress content updated\n\n" + _format_item(item), metadata={"id": item.get("id")})
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
        if not bool(params.get("approved", False)):
            return self._result("Uploading public media requires explicit approval.", success=False)

        file_path = Path(str(params.get("path") or ""))
        if not file_path.exists() or not file_path.is_file():
            return self._result(f"Media file not found: {file_path}", success=False)

        headers = _headers(site_key)
        headers["Content-Disposition"] = f'attachment; filename="{file_path.name}"'

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
]
