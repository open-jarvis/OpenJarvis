"""Small synchronous CDP adapter for an OpenJarvis-owned Chromium session."""

from __future__ import annotations

import base64
import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openjarvis.browser.models import BrowserSession


class BrowserControlError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BrowserObservation:
    url: str
    title: str
    ready_state: str
    text: str


class CdpBrowserAdapter:
    """CDP operations without using or discovering a user browser profile."""

    def __init__(self) -> None:
        self._socket = None
        self._message_id = 0
        self._session_id: str | None = None

    def connect(self, session: BrowserSession) -> bool:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{session.control_port}/json/list",
                timeout=2,
            ) as response:
                targets = json.loads(response.read(512 * 1024).decode("utf-8"))
            target = next(item for item in targets if item.get("type") == "page")
            websocket_url = target["webSocketDebuggerUrl"]
            if not websocket_url.startswith(
                (
                    f"ws://127.0.0.1:{session.control_port}/",
                    f"ws://localhost:{session.control_port}/",
                )
            ):
                raise BrowserControlError("CDP websocket escaped loopback control port")
            from websockets.sync.client import connect

            self.close()
            self._socket = connect(
                websocket_url,
                open_timeout=2,
                close_timeout=1,
                proxy=None,
            )
            self._session_id = session.session_id
            self._command("Runtime.enable")
            self._command("Page.enable")
            return True
        except Exception:
            self.close()
            return False

    def reconnect(self, session: BrowserSession) -> bool:
        return self.connect(session)

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
        self._socket = None
        self._session_id = None

    def _command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        if self._socket is None:
            raise BrowserControlError("CDP adapter is not connected")
        self._message_id += 1
        message_id = self._message_id
        self._socket.send(
            json.dumps({"id": message_id, "method": method, "params": params or {}})
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            raw = self._socket.recv(timeout=max(deadline - time.monotonic(), 0.01))
            message = json.loads(raw)
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise BrowserControlError(
                    f"{method} failed: {message['error'].get('message', 'unknown')}"
                )
            return dict(message.get("result", {}))
        raise BrowserControlError(f"CDP command timed out: {method}")

    def evaluate(self, expression: str) -> Any:
        result = self._command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        remote = result.get("result", {})
        if remote.get("subtype") == "error" or result.get("exceptionDetails"):
            raise BrowserControlError("JavaScript evaluation failed")
        return remote.get("value")

    def snapshot(self) -> BrowserObservation:
        value = self.evaluate(
            """(() => ({
                url: location.href,
                title: document.title,
                ready_state: document.readyState,
                text: document.documentElement
                    ? document.documentElement.textContent
                    : ''
            }))()"""
        )
        if not isinstance(value, dict):
            raise BrowserControlError("browser observation is invalid")
        return BrowserObservation(
            url=str(value.get("url", "")),
            title=str(value.get("title", "")),
            ready_state=str(value.get("ready_state", "")),
            text=str(value.get("text", ""))[:1_000_000],
        )

    def navigate(self, url: str, *, timeout: float = 15.0) -> BrowserObservation:
        self._command("Page.navigate", {"url": url})
        return self._wait_ready(timeout)

    def reload(self, *, timeout: float = 15.0) -> BrowserObservation:
        self._command("Page.reload", {"ignoreCache": True})
        return self._wait_ready(timeout)

    def _wait_ready(self, timeout: float) -> BrowserObservation:
        deadline = time.monotonic() + timeout
        last = self.snapshot()
        while time.monotonic() < deadline:
            last = self.snapshot()
            if last.ready_state in {"interactive", "complete"}:
                return last
            time.sleep(0.05)
        raise BrowserControlError(
            f"document did not become ready; state={last.ready_state!r}"
        )

    def element_info(self, selector: str) -> dict[str, Any] | None:
        encoded = json.dumps(selector)
        value = self.evaluate(
            f"""(() => {{
              const e=document.querySelector({encoded});
              if(!e) return null;
              return {{tag:e.tagName.toLowerCase(),type:(e.type||'').toLowerCase(),
                value:e.value||'',visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)}};
            }})()"""
        )
        return value if isinstance(value, dict) else None

    def click(self, selector: str) -> BrowserObservation:
        encoded = json.dumps(selector)
        clicked = self.evaluate(
            f"""(() => {{const e=document.querySelector({encoded});
            if(!e) return false;e.click();return true;}})()"""
        )
        if clicked is not True:
            raise BrowserControlError(f"element not found: {selector}")
        time.sleep(0.05)
        return self.snapshot()

    def fill(self, selector: str, text: str) -> BrowserObservation:
        encoded_selector = json.dumps(selector)
        encoded_text = json.dumps(text)
        value = self.evaluate(
            f"""(() => {{const e=document.querySelector({encoded_selector});
            if(!e) return null;e.focus();e.value={encoded_text};
            e.dispatchEvent(new Event('input',{{bubbles:true}}));
            e.dispatchEvent(new Event('change',{{bubbles:true}}));
            return e.value;}})()"""
        )
        if value is None:
            raise BrowserControlError(f"input not found: {selector}")
        return self.snapshot()

    def value(self, selector: str) -> str | None:
        encoded = json.dumps(selector)
        value = self.evaluate(
            f"""(() => {{const e=document.querySelector({encoded});
            return e?e.value:null;}})()"""
        )
        return None if value is None else str(value)

    def select(self, selector: str, value: str) -> BrowserObservation:
        encoded_selector = json.dumps(selector)
        encoded_value = json.dumps(value)
        selected = self.evaluate(
            f"""(() => {{const e=document.querySelector({encoded_selector});
            if(!e) return null;e.value={encoded_value};
            e.dispatchEvent(new Event('change',{{bubbles:true}}));
            return e.value;}})()"""
        )
        if selected != value:
            raise BrowserControlError("select verification failed")
        return self.snapshot()

    def scroll(self, delta_y: int) -> BrowserObservation:
        self.evaluate(f"window.scrollBy(0,{int(delta_y)});window.scrollY")
        return self.snapshot()

    def screenshot(self) -> bytes:
        result = self._command(
            "Page.captureScreenshot",
            {"format": "png", "captureBeyondViewport": False},
        )
        return base64.b64decode(result["data"], validate=True)

    def prepare_downloads(self, download_root: Path) -> None:
        self._command(
            "Browser.setDownloadBehavior",
            {
                "behavior": "allow",
                "downloadPath": str(download_root),
                "eventsEnabled": True,
            },
        )

    def prepare_upload(self, selector: str, file_path: Path) -> str:
        encoded = json.dumps(selector)
        evaluated = self._command(
            "Runtime.evaluate",
            {"expression": f"document.querySelector({encoded})"},
        )
        object_id = evaluated.get("result", {}).get("objectId")
        if not object_id:
            raise BrowserControlError("upload input not found")
        node = self._command("DOM.requestNode", {"objectId": object_id})
        node_id = node.get("nodeId")
        self._command(
            "DOM.setFileInputFiles",
            {"files": [str(file_path)], "nodeId": node_id},
        )
        value = self.value(selector) or ""
        return value.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]

    def open_tab(self, url: str) -> str:
        result = self._command("Target.createTarget", {"url": url})
        return str(result["targetId"])

    def close_tab(self, target_id: str) -> bool:
        return bool(
            self._command("Target.closeTarget", {"targetId": target_id}).get("success")
        )


__all__ = [
    "BrowserControlError",
    "BrowserObservation",
    "CdpBrowserAdapter",
]
