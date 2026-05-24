"""Local rule-based assistant actions for Friday.

This module handles small deterministic assistant commands before they reach
the LLM. Everything here is local-first: no cloud APIs, no API keys, and no
free-form shell execution.
"""

from __future__ import annotations

import json
import platform
import re
import socket
import subprocess
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from openjarvis.core.config import DEFAULT_CONFIG_DIR

FRIDAY_DATA_PATH = DEFAULT_CONFIG_DIR / "friday_data.json"

WEBSITE_ALIASES: dict[str, str] = {
    "구글": "https://www.google.com",
    "google": "https://www.google.com",
    "네이버": "https://www.naver.com",
    "naver": "https://www.naver.com",
    "유튜브": "https://www.youtube.com",
    "youtube": "https://www.youtube.com",
    "깃허브": "https://github.com",
    "github": "https://github.com",
    "챗지피티": "https://chatgpt.com",
    "chatgpt": "https://chatgpt.com",
}

APP_ALIASES: dict[str, str] = {
    "크롬": "Google Chrome",
    "chrome": "Google Chrome",
    "사파리": "Safari",
    "safari": "Safari",
    "메모": "Notes",
    "notes": "Notes",
    "계산기": "Calculator",
    "calculator": "Calculator",
    "터미널": "Terminal",
    "terminal": "Terminal",
    "카카오톡": "KakaoTalk",
    "kakaotalk": "KakaoTalk",
}

DETAIL_WEATHER_KEYWORDS = (
    "상세",
    "자세히",
    "디테일",
    "습도",
    "기압",
    "풍속",
    "자외선",
    "가시거리",
)

OPEN_VERBS = ("열어", "열어줘", "켜", "켜줘", "실행", "실행해", "실행해줘", "open")
WEEKDAYS_KO = ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")


@dataclass(slots=True)
class FridayAssistantResult:
    """A handled local Friday command."""

    content: str
    intent: str
    success: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_response(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "usage": {},
            "model": "friday-local",
            "engine": "local-rule",
            "metadata": {
                "friday_local": True,
                "intent": self.intent,
                **self.metadata,
            },
        }


class FridayLocalStore:
    """Simple JSON-backed local notes and todos."""

    def __init__(self, path: str | Path = FRIDAY_DATA_PATH) -> None:
        self.path = Path(path).expanduser()

    def add_note(self, text: str) -> int:
        data = self._load()
        data["notes"].append(
            {
                "text": text.strip(),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        self._save(data)
        return len(data["notes"])

    def list_notes(self) -> list[str]:
        return [str(item.get("text", "")) for item in self._load()["notes"]]

    def add_todo(self, text: str) -> int:
        data = self._load()
        data["todos"].append(
            {
                "text": text.strip(),
                "done": False,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        self._save(data)
        return len(data["todos"])

    def list_todos(self) -> list[str]:
        return [str(item.get("text", "")) for item in self._load()["todos"]]

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return {"notes": [], "todos": []}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"notes": [], "todos": []}
        return {
            "notes": list(raw.get("notes") or []),
            "todos": list(raw.get("todos") or []),
        }

    def _save(self, data: dict[str, list[dict[str, Any]]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def open_website(alias_or_url: str) -> FridayAssistantResult:
    target = _resolve_website(alias_or_url)
    if not target:
        return FridayAssistantResult(
            content=(
                "지원하는 사이트만 열 수 있습니다. "
                "구글, 네이버, 유튜브, 깃허브, 챗지피티를 지원합니다."
            ),
            intent="open_website",
            success=False,
        )
    webbrowser.open(target)
    return FridayAssistantResult(
        content=f"브라우저에서 {target} 열었습니다.",
        intent="open_website",
        metadata={"url": target},
    )


def open_macos_app(alias: str) -> FridayAssistantResult:
    app_name = _find_alias(alias, APP_ALIASES)
    if not app_name:
        return FridayAssistantResult(
            content=(
                "지원하는 앱만 열 수 있습니다. "
                "크롬, 사파리, 메모, 계산기, 터미널, 카카오톡을 지원합니다."
            ),
            intent="open_app",
            success=False,
        )
    if platform.system() != "Darwin":
        return FridayAssistantResult(
            content="앱 열기는 macOS에서만 지원합니다.",
            intent="open_app",
            success=False,
            metadata={"app": app_name},
        )
    try:
        subprocess.run(
            ["open", "-a", app_name],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return FridayAssistantResult(
            content=f"{app_name} 앱을 열지 못했습니다: {exc}",
            intent="open_app",
            success=False,
            metadata={"app": app_name},
        )
    return FridayAssistantResult(
        content=f"{app_name} 앱을 열었습니다.",
        intent="open_app",
        metadata={"app": app_name},
    )


def check_friday_status(
    port_checker: Callable[[str, int, float], bool] | None = None,
) -> FridayAssistantResult:
    checker = port_checker or _is_port_open
    targets = [
        ("Ollama", "127.0.0.1", 11434),
        ("backend", "127.0.0.1", 8000),
        ("frontend", "127.0.0.1", 5173),
    ]
    statuses = {name: checker(host, port, 0.3) for name, host, port in targets}
    lines = ["Friday 로컬 상태입니다."]
    for name, _host, port in targets:
        state = "실행 중" if statuses[name] else "응답 없음"
        lines.append(f"- {name} ({port}): {state}")
    return FridayAssistantResult(
        content="\n".join(lines),
        intent="status",
        metadata={"ports": statuses},
    )


class FridayAssistantRouter:
    """Rule-based command router for local Friday assistant actions."""

    def __init__(
        self,
        *,
        data_path: str | Path = FRIDAY_DATA_PATH,
        now_fn: Callable[[], datetime] | None = None,
        port_checker: Callable[[str, int, float], bool] | None = None,
    ) -> None:
        self.store = FridayLocalStore(data_path)
        self.now_fn = now_fn or datetime.now
        self.port_checker = port_checker

    def route(self, query: str) -> FridayAssistantResult | None:
        text = _compact(query)
        if not text:
            return None

        handled = (
            self._route_time_date(text)
            or self._route_weather(text)
            or self._route_website(text)
            or self._route_app(text)
            or self._route_notes_todos(text)
            or self._route_status(text)
        )
        return handled

    def _route_time_date(self, text: str) -> FridayAssistantResult | None:
        now = self.now_fn()
        if (
            "몇 시" in text
            or "몇시" in text
            or "현재 시간" in text
            or "지금 시간" in text
        ):
            return FridayAssistantResult(
                content=f"지금은 {now.hour}시 {now.minute:02d}분입니다.",
                intent="time",
            )
        if "무슨 요일" in text or text.endswith("요일이야?") or "요일 알려" in text:
            return FridayAssistantResult(
                content=f"오늘은 {WEEKDAYS_KO[now.weekday()]}입니다.",
                intent="weekday",
            )
        if "오늘 날짜" in text or "날짜 알려" in text:
            return FridayAssistantResult(
                content=f"오늘은 {now.year}년 {now.month}월 {now.day}일입니다.",
                intent="date",
            )
        return None

    def _route_weather(self, text: str) -> FridayAssistantResult | None:
        if "날씨" not in text and not any(k in text for k in DETAIL_WEATHER_KEYWORDS):
            return None
        if not any(k in text for k in ("날씨", "비", *DETAIL_WEATHER_KEYWORDS)):
            return None

        profile = (
            "detail" if any(k in text for k in DETAIL_WEATHER_KEYWORDS) else "basic"
        )
        tool_name = "weather_detail" if profile == "detail" else "weather_basic"
        try:
            import openjarvis.tools  # noqa: F401
            from openjarvis.core.registry import ToolRegistry

            if ToolRegistry.contains(tool_name):
                result = ToolRegistry.create(tool_name).execute(query=text)
            elif ToolRegistry.contains("weather"):
                result = ToolRegistry.create("weather").execute(
                    query=text,
                    profile=profile,
                )
            else:
                return None
        except Exception as exc:
            return FridayAssistantResult(
                content=f"날씨 정보를 가져오지 못했습니다: {exc}",
                intent="weather",
                success=False,
                metadata={"profile": profile},
            )

        return FridayAssistantResult(
            content=result.content,
            intent="weather",
            success=result.success,
            metadata={"profile": profile, "tool": result.tool_name},
        )

    def _route_website(self, text: str) -> FridayAssistantResult | None:
        if not _has_open_verb(text):
            return None
        target = _find_alias(text, WEBSITE_ALIASES) or _extract_safe_url(text)
        if not target:
            return None
        return open_website(target)

    def _route_app(self, text: str) -> FridayAssistantResult | None:
        if not _has_open_verb(text):
            return None
        if not _find_alias(text, APP_ALIASES):
            return None
        return open_macos_app(text)

    def _route_notes_todos(self, text: str) -> FridayAssistantResult | None:
        if "메모 목록" in text or ("메모" in text and "목록" in text):
            notes = self.store.list_notes()
            if not notes:
                return FridayAssistantResult(
                    content="저장된 메모가 없습니다.",
                    intent="list_notes",
                )
            lines = ["저장된 메모입니다."]
            lines.extend(f"- {note}" for note in notes)
            return FridayAssistantResult(content="\n".join(lines), intent="list_notes")

        if "할 일 목록" in text or "할일 목록" in text:
            todos = self.store.list_todos()
            if not todos:
                return FridayAssistantResult(
                    content="저장된 할 일이 없습니다.",
                    intent="list_todos",
                )
            lines = ["할 일 목록입니다."]
            lines.extend(f"- {todo}" for todo in todos)
            return FridayAssistantResult(content="\n".join(lines), intent="list_todos")

        note = _extract_after(
            text,
            ("메모해줘:", "메모해 줘:", "메모해줘", "메모해 줘"),
        )
        if note:
            count = self.store.add_note(note)
            return FridayAssistantResult(
                content=f"메모했습니다. 현재 메모는 {count}개입니다.",
                intent="add_note",
            )

        todo = _extract_after(
            text,
            ("할 일 추가:", "할일 추가:", "할 일 추가", "할일 추가"),
        )
        if todo:
            count = self.store.add_todo(todo)
            return FridayAssistantResult(
                content=f"할 일을 추가했습니다. 현재 할 일은 {count}개입니다.",
                intent="add_todo",
            )

        return None

    def _route_status(self, text: str) -> FridayAssistantResult | None:
        if (
            ("friday" in text.lower() and "상태" in text)
            or "서버 상태" in text
            or "로컬 모델 상태" in text
        ):
            return check_friday_status(self.port_checker)
        return None


def route_friday_command(
    query: str,
    *,
    data_path: str | Path = FRIDAY_DATA_PATH,
    now_fn: Callable[[], datetime] | None = None,
    port_checker: Callable[[str, int, float], bool] | None = None,
) -> FridayAssistantResult | None:
    return FridayAssistantRouter(
        data_path=data_path,
        now_fn=now_fn,
        port_checker=port_checker,
    ).route(query)


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _has_open_verb(text: str) -> bool:
    lowered = text.lower()
    return any(verb in lowered for verb in OPEN_VERBS)


def _find_alias(text: str, aliases: dict[str, str]) -> str | None:
    lowered = text.lower()
    for alias, target in aliases.items():
        if alias.lower() in lowered:
            return target
    return None


def _resolve_website(alias_or_url: str) -> str | None:
    return _find_alias(alias_or_url, WEBSITE_ALIASES) or _extract_safe_url(alias_or_url)


def _extract_safe_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s]+", text)
    if not match:
        return None
    url = match.group(0).rstrip(".,)")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return url


def _extract_after(text: str, markers: tuple[str, ...]) -> str:
    for marker in markers:
        if marker in text:
            value = text.split(marker, 1)[1].strip(" :")
            return value
    return ""


def _is_port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


__all__ = [
    "APP_ALIASES",
    "FRIDAY_DATA_PATH",
    "FridayAssistantResult",
    "FridayAssistantRouter",
    "FridayLocalStore",
    "WEBSITE_ALIASES",
    "check_friday_status",
    "open_macos_app",
    "open_website",
    "route_friday_command",
]
