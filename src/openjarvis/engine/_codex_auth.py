"""Opt-in local Codex auth; Codex itself owns OAuth refresh and storage."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import stat
import threading
import time
from pathlib import Path

from openjarvis.engine._base import EngineConnectionError


class LocalCodexAuth:
    """Read the existing private cache, never copy credentials or log them."""

    def __init__(self) -> None:
        self.path = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"
        self._lock = threading.Lock()
        self._retry_after = 0.0

    def _read(self) -> tuple[str, float]:
        try:
            info = self.path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("Private auth file required")
            token = json.loads(self.path.read_text())["tokens"]["access_token"]
            payload = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            return token, float(claims["exp"])
        except Exception:
            raise EngineConnectionError("Codex login unavailable; run codex login") from None

    def access_token(self) -> str:
        with self._lock:
            token, expiry = self._read()
            if expiry > time.time() + 120:
                return token
            if time.monotonic() < self._retry_after:
                raise EngineConnectionError("Codex auth refresh unavailable; retry later")
            self._retry_after = time.monotonic() + 60
            try:
                asyncio.run(self._refresh())
                token, expiry = self._read()
                if expiry <= time.time() + 120:
                    raise ValueError("Expired session")
            except Exception:
                raise EngineConnectionError("Codex session refresh failed; run codex login") from None
            self._retry_after = 0.0
            return token

    async def _refresh(self) -> None:
        # Auth/account methods only: no thread, inference, tools or MCP calls.
        proc = await asyncio.create_subprocess_exec(
            "codex", "app-server", "--listen", "stdio://",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(45):
                async def send(message):
                    proc.stdin.write((json.dumps(message) + "\n").encode())
                    await proc.stdin.drain()

                async def receive(request_id):
                    while line := await proc.stdout.readline():
                        message = json.loads(line)
                        if message.get("id") == request_id:
                            if "error" in message:
                                raise ValueError("Auth request failed")
                            return message.get("result", {})
                    raise ValueError("Auth process stopped")

                await send({"id": 1, "method": "initialize", "params": {
                    "clientInfo": {"name": "openjarvis_local_auth", "version": "1.0"},
                }})
                await receive(1)
                await send({"method": "initialized", "params": {}})
                await send({"id": 2, "method": "account/read", "params": {"refreshToken": True}})
                result = await receive(2)
                if (result.get("account") or {}).get("type") != "chatgpt":
                    raise ValueError("Managed ChatGPT login required")
        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
