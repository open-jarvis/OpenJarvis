"""Buffer GraphQL API client (https://api.buffer.com) for approved posts.

Reference (checked 2026-11-05): developers.buffer.com guides "authentication",
"posts-and-scheduling", "hosting-media", "error-handling", "api-limits" and the
GraphQL reference. Buffer has no idempotency key, so the caller must look up an
uncertain create (``find_post``) before ever retrying it. Errors usually come
back as HTTP 200 with an ``errors`` array or a typed mutation error.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from openjarvis.marketing.connections import BUFFER_API_URL


class BufferError(RuntimeError):
    """Arabic message safe to show the operator.

    ``uncertain`` means the request may have been applied (timeout or server
    error after sending) and must be reconciled before any retry.
    """

    def __init__(self, message: str, *, uncertain: bool = False) -> None:
        super().__init__(message)
        self.uncertain = uncertain


_POST_FIELDS = "id text dueAt status channelId sentAt error { message }"


def _lit(value: str) -> str:
    """A GraphQL string literal for an ID or timestamp (validated charset)."""
    import json
    import re

    if not re.fullmatch(r"[A-Za-z0-9_:.+-]{1,64}", value or ""):
        raise BufferError("معرّف أو موعد غير صالح لطلب Buffer.")
    return json.dumps(value)


class BufferClient:
    def __init__(
        self, token: str, *, transport: Any = None, timeout: float = 30.0
    ) -> None:
        self._token = token
        self._transport = transport
        self._timeout = timeout

    def _call(self, query: str, variables: Optional[dict] = None) -> Dict[str, Any]:
        try:
            with httpx.Client(
                timeout=self._timeout, transport=self._transport, follow_redirects=False
            ) as client:
                response = client.post(
                    BUFFER_API_URL,
                    json={"query": query, "variables": variables or {}},
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.ConnectError:
            raise BufferError("تعذّر الاتصال بـ Buffer؛ لم يُرسل الطلب.") from None
        except httpx.HTTPError:
            raise BufferError(
                "انقطع الاتصال بـ Buffer بعد إرسال الطلب؛ النتيجة غير مؤكدة.",
                uncertain=True,
            ) from None
        if response.status_code == 401:
            raise BufferError("رفض Buffer مفتاح الـAPI؛ راجع اتصال Buffer للفريق.")
        if response.status_code == 429:
            retry = response.headers.get("Retry-After", "")
            raise BufferError(
                f"تجاوزت حد طلبات Buffer؛ أعد المحاولة بعد {retry} ثانية."
            )
        if response.status_code >= 500:
            raise BufferError(
                f"خطأ من خادم Buffer (HTTP {response.status_code})؛ النتيجة غير مؤكدة.",
                uncertain=True,
            )
        if response.is_error:
            raise BufferError(f"رفض Buffer الطلب (HTTP {response.status_code}).")
        try:
            body = response.json()
        except ValueError:
            raise BufferError("ردّ Buffer غير مفهوم؛ النتيجة غير مؤكدة.", uncertain=True)
        errors = body.get("errors") or []
        if errors:
            code = (errors[0].get("extensions") or {}).get("code", "")
            message = str(errors[0].get("message", ""))[:300]
            if code == "UNAUTHORIZED":
                raise BufferError("رفض Buffer مفتاح الـAPI؛ راجع اتصال Buffer للفريق.")
            if code == "FORBIDDEN":
                raise BufferError(
                    "مفتاح Buffer لا يملك صلاحية لهذه العملية (مثل إنشاء منشورات)."
                )
            if code == "RATE_LIMIT_EXCEEDED":
                raise BufferError("تجاوزت حد طلبات Buffer؛ أعد المحاولة لاحقًا.")
            raise BufferError(
                f"خطأ من Buffer ({code or 'غير محدد'}): {message}",
                uncertain=code == "UNEXPECTED",
            )
        return body.get("data") or {}

    # ── Read ─────────────────────────────────────────────────────

    def verify(self) -> Dict[str, Any]:
        """Prove the key works: account and organizations."""
        data = self._call("query { account { id email organizations { id name } } }")
        account = data.get("account")
        if not account:
            raise BufferError("لم يُرجع Buffer بيانات الحساب؛ لم يتم التحقق.")
        return account

    def channels(self, organization_id: str) -> List[Dict[str, Any]]:
        data = self._call(
            f"query {{ channels(input: {{ organizationId: {_lit(organization_id)} }})"
            " { id name displayName service timezone isQueuePaused } }"
        )
        return data.get("channels") or []

    def get_post(self, post_id: str) -> Optional[Dict[str, Any]]:
        data = self._call(
            f"query {{ post(input: {{ id: {_lit(post_id)} }}) {{ {_POST_FIELDS} }} }}"
        )
        return data.get("post")

    def find_post(
        self,
        *,
        organization_id: str,
        channel_id: str,
        text: str,
        due_at_start: str,
        due_at_end: str,
    ) -> Optional[Dict[str, Any]]:
        """Look for an already-created post matching this exact draft."""
        data = self._call(
            f"query {{ posts(first: 50, input: {{ organizationId: "
            f"{_lit(organization_id)}, filter: {{ channelIds: [{_lit(channel_id)}], "
            f"dueAt: {{ start: {_lit(due_at_start)}, end: {_lit(due_at_end)} }} }} }})"
            f" {{ edges {{ node {{ {_POST_FIELDS} }} }} }} }}"
        )
        for edge in ((data.get("posts") or {}).get("edges")) or []:
            node = edge.get("node") or {}
            if (node.get("text") or "").strip() == text.strip():
                return node
        return None

    # ── Write ────────────────────────────────────────────────────

    def create_scheduled_post(
        self, *, channel_id: str, text: str, due_at: str, image_url: str
    ) -> Dict[str, Any]:
        data = self._call(
            "mutation($input: CreatePostInput!) { createPost(input: $input) {"
            " __typename ... on PostActionSuccess { post { "
            f"{_POST_FIELDS} }} }} ... on MutationError {{ message }} }} }}",
            {
                "input": {
                    "text": text,
                    "channelId": channel_id,
                    "schedulingType": "automatic",
                    "mode": "customScheduled",
                    "dueAt": due_at,
                    "assets": [{"image": {"url": image_url}}],
                }
            },
        )
        result = data.get("createPost") or {}
        post = result.get("post")
        if post and post.get("id"):
            return post
        raise BufferError(
            "رفض Buffer إنشاء المنشور: "
            + str(result.get("message") or result.get("__typename") or "سبب غير معروف")[
                :300
            ]
        )


__all__ = ["BufferClient", "BufferError"]
