"""Minimal Cloudflare R2 (S3-compatible) client for approved images only.

Buffer fetches images from a public URL at publish time and has no upload
endpoint, so the approved PNG — and nothing else — is uploaded to the
company's own public bucket under an unguessable key. The URL never expires;
R2's public endpoint does not list bucket contents.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
from typing import Any, Optional
from urllib.parse import quote

import httpx


class R2Error(RuntimeError):
    """Arabic message safe to show the operator (never contains secrets)."""


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


class R2Client:
    def __init__(
        self,
        *,
        account_id: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        public_base_url: str,
        transport: Any = None,
        timeout: float = 30.0,
    ) -> None:
        self.host = f"{account_id}.r2.cloudflarestorage.com"
        self.bucket = bucket
        self._access_key = access_key_id
        self._secret = secret_access_key
        self.public_base_url = public_base_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout

    def _headers(
        self, method: str, path: str, payload: bytes, extra: dict[str, str]
    ) -> dict[str, str]:
        now = dt.datetime.now(dt.UTC)
        amz_date, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(payload).hexdigest()
        headers = {
            "host": self.host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
            **{k.lower(): v for k, v in extra.items()},
        }
        names = sorted(headers)
        canonical = "\n".join(
            [
                method,
                path,
                "",
                "".join(f"{n}:{headers[n].strip()}\n" for n in names),
                ";".join(names),
                payload_hash,
            ]
        )
        scope = f"{day}/auto/s3/aws4_request"
        to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                scope,
                hashlib.sha256(canonical.encode()).hexdigest(),
            ]
        )
        key = _sign(("AWS4" + self._secret).encode(), day)
        for part in ("auto", "s3", "aws4_request"):
            key = _sign(key, part)
        signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
        headers["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self._access_key}/{scope}, "
            f"SignedHeaders={';'.join(names)}, Signature={signature}"
        )
        headers.pop("host")
        return headers

    def _request(
        self, method: str, key: Optional[str], payload: bytes = b"", **extra: str
    ) -> httpx.Response:
        path = f"/{self.bucket}" + (f"/{quote(key)}" if key else "")
        try:
            with httpx.Client(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                return client.request(
                    method,
                    f"https://{self.host}{path}",
                    content=payload,
                    headers=self._headers(method, path, payload, extra),
                )
        except httpx.HTTPError:
            raise R2Error("تعذّر الوصول إلى Cloudflare R2 خلال المهلة.") from None

    def verify(self) -> None:
        """Check the credential can reach the bucket (no object is written)."""
        response = self._request("HEAD", None)
        if response.status_code in {401, 403}:
            raise R2Error("رفض Cloudflare R2 بيانات الدخول أو صلاحية الـbucket.")
        if response.status_code == 404:
            raise R2Error("الـbucket غير موجود في حساب Cloudflare R2.")
        if response.is_error:
            raise R2Error(f"فشل التحقق من R2 (HTTP {response.status_code}).")

    @staticmethod
    def new_key() -> str:
        """Unguessable object name that reveals no company folder or file name."""
        return f"approved/{secrets.token_urlsafe(24)}.png"

    def put_png(self, key: str, data: bytes) -> str:
        """Upload (idempotent for the same key) and return the public URL."""
        response = self._request(
            "PUT",
            key,
            data,
            **{
                "content-type": "image/png",
                "cache-control": "public, max-age=31536000, immutable",
            },
        )
        if response.status_code in {401, 403}:
            raise R2Error("رفض Cloudflare R2 رفع الصورة؛ راجع صلاحية المفتاح.")
        if response.is_error:
            raise R2Error(f"فشل رفع الصورة إلى R2 (HTTP {response.status_code}).")
        return f"{self.public_base_url}/{quote(key)}"


__all__ = ["R2Client", "R2Error"]
