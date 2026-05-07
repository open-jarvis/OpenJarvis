"""Cloudinary upload / search / delete client.

Auth uses HTTP Basic with ``CLOUDINARY_API_KEY`` as username and
``CLOUDINARY_API_SECRET`` as password. Cloud namespace comes from
``CLOUDINARY_CLOUD_NAME``. Upload uses the unsigned multipart endpoint
with a server-side timestamp + signature so callers don't need to
import the official SDK.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class CloudinaryUnavailableError(RuntimeError):
    """Raised when Cloudinary credentials are missing or a call fails."""


def _signature(params: dict[str, Any], api_secret: str) -> str:
    """Cloudinary upload signature: SHA1(sorted params + api_secret)."""
    pairs = sorted(
        (k, v) for k, v in params.items() if k != "file" and v not in (None, "")
    )
    base = "&".join(f"{k}={v}" for k, v in pairs)
    return hashlib.sha1((base + api_secret).encode("utf-8")).hexdigest()


class CloudinaryClient:
    def __init__(
        self,
        *,
        cloud_name: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        self._cloud = cloud_name or os.environ.get("CLOUDINARY_CLOUD_NAME", "")
        self._key = api_key or os.environ.get("CLOUDINARY_API_KEY", "")
        self._secret = api_secret or os.environ.get("CLOUDINARY_API_SECRET", "")
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._cloud and self._key and self._secret)

    def _ensure(self) -> None:
        if not self.configured:
            raise CloudinaryUnavailableError(
                "Cloudinary not configured — set CLOUDINARY_CLOUD_NAME, "
                "CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET"
            )

    def _admin_url(self, path: str) -> str:
        return f"https://api.cloudinary.com/v1_1/{self._cloud}{path}"

    def _upload_url(self, resource_type: str = "auto") -> str:
        return f"https://api.cloudinary.com/v1_1/{self._cloud}/{resource_type}/upload"

    def upload(
        self,
        *,
        file_url: Optional[str] = None,
        file_data: Optional[bytes] = None,
        public_id: Optional[str] = None,
        folder: Optional[str] = None,
        resource_type: str = "auto",
    ) -> Any:
        """Upload by remote URL or in-memory bytes.

        At least one of ``file_url`` or ``file_data`` must be provided.
        """
        self._ensure()
        if not (file_url or file_data):
            raise ValueError("Provide file_url or file_data")
        timestamp = int(time.time())
        signed_params: dict[str, Any] = {"timestamp": timestamp}
        if public_id:
            signed_params["public_id"] = public_id
        if folder:
            signed_params["folder"] = folder
        sig = _signature(signed_params, self._secret)

        form = {
            **{k: str(v) for k, v in signed_params.items()},
            "api_key": self._key,
            "signature": sig,
        }
        files: Optional[dict[str, Any]] = None
        if file_url:
            form["file"] = file_url
        else:
            files = {"file": ("upload.bin", file_data)}

        try:
            with httpx.Client(timeout=self._timeout) as c:
                resp = c.post(self._upload_url(resource_type), data=form, files=files)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            raise CloudinaryUnavailableError(f"Cloudinary upload failed: {exc}") from exc

    def search(
        self,
        expression: str,
        *,
        max_results: int = 30,
    ) -> Any:
        self._ensure()
        try:
            with httpx.Client(timeout=self._timeout) as c:
                resp = c.post(
                    self._admin_url("/resources/search"),
                    auth=(self._key, self._secret),
                    json={"expression": expression, "max_results": max_results},
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            raise CloudinaryUnavailableError(f"Cloudinary search failed: {exc}") from exc

    def delete(self, public_id: str, *, resource_type: str = "image") -> Any:
        self._ensure()
        try:
            with httpx.Client(timeout=self._timeout) as c:
                resp = c.delete(
                    self._admin_url(f"/resources/{resource_type}/upload"),
                    auth=(self._key, self._secret),
                    params={"public_ids[]": public_id},
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            raise CloudinaryUnavailableError(f"Cloudinary delete failed: {exc}") from exc


_default: Optional[CloudinaryClient] = None


def get_default_client() -> CloudinaryClient:
    global _default
    if _default is None:
        _default = CloudinaryClient()
    return _default


__all__ = [
    "CloudinaryClient",
    "CloudinaryUnavailableError",
    "get_default_client",
]
