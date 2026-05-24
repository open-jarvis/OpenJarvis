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
SEOUL_WEATHER_LOCATION = {
    "name": "서울",
    "latitude": 37.566,
    "longitude": 126.9784,
    "timezone": "Asia/Seoul",
}

KOREAN_CITY_LOCATIONS: dict[str, dict[str, Any]] = {
    "서울": SEOUL_WEATHER_LOCATION,
    "부산": {
        "name": "부산",
        "latitude": 35.1796,
        "longitude": 129.0756,
        "timezone": "Asia/Seoul",
    },
    "대구": {
        "name": "대구",
        "latitude": 35.8714,
        "longitude": 128.6014,
        "timezone": "Asia/Seoul",
    },
    "인천": {
        "name": "인천",
        "latitude": 37.4563,
        "longitude": 126.7052,
        "timezone": "Asia/Seoul",
    },
    "광주": {
        "name": "광주",
        "latitude": 35.1595,
        "longitude": 126.8526,
        "timezone": "Asia/Seoul",
    },
    "대전": {
        "name": "대전",
        "latitude": 36.3504,
        "longitude": 127.3845,
        "timezone": "Asia/Seoul",
    },
    "울산": {
        "name": "울산",
        "latitude": 35.5384,
        "longitude": 129.3114,
        "timezone": "Asia/Seoul",
    },
    "세종": {
        "name": "세종",
        "latitude": 36.48,
        "longitude": 127.289,
        "timezone": "Asia/Seoul",
    },
    "제주": {
        "name": "제주",
        "latitude": 33.4996,
        "longitude": 126.5312,
        "timezone": "Asia/Seoul",
    },
    "수원": {
        "name": "수원",
        "latitude": 37.2636,
        "longitude": 127.0286,
        "timezone": "Asia/Seoul",
    },
    "성남": {
        "name": "성남",
        "latitude": 37.42,
        "longitude": 127.1265,
        "timezone": "Asia/Seoul",
    },
    "고양": {
        "name": "고양",
        "latitude": 37.6584,
        "longitude": 126.832,
        "timezone": "Asia/Seoul",
    },
    "용인": {
        "name": "용인",
        "latitude": 37.2411,
        "longitude": 127.1776,
        "timezone": "Asia/Seoul",
    },
    "창원": {
        "name": "창원",
        "latitude": 35.2279,
        "longitude": 128.6811,
        "timezone": "Asia/Seoul",
    },
    "청주": {
        "name": "청주",
        "latitude": 36.6424,
        "longitude": 127.489,
        "timezone": "Asia/Seoul",
    },
    "전주": {
        "name": "전주",
        "latitude": 35.8242,
        "longitude": 127.148,
        "timezone": "Asia/Seoul",
    },
    "천안": {
        "name": "천안",
        "latitude": 36.8151,
        "longitude": 127.1139,
        "timezone": "Asia/Seoul",
    },
    "포항": {
        "name": "포항",
        "latitude": 36.019,
        "longitude": 129.3435,
        "timezone": "Asia/Seoul",
    },
    "강릉": {
        "name": "강릉",
        "latitude": 37.7519,
        "longitude": 128.8761,
        "timezone": "Asia/Seoul",
    },
    "춘천": {
        "name": "춘천",
        "latitude": 37.8813,
        "longitude": 127.7298,
        "timezone": "Asia/Seoul",
    },
}

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

    def set_weather_location(self, location: dict[str, Any]) -> None:
        data = self._load()
        data["weather_default_location"] = {
            "name": str(location["name"]),
            "latitude": float(location["latitude"]),
            "longitude": float(location["longitude"]),
            "timezone": str(location.get("timezone") or "Asia/Seoul"),
        }
        self._save(data)

    def get_weather_location(self) -> dict[str, Any] | None:
        location = self._load().get("weather_default_location")
        if not isinstance(location, dict):
            return None
        try:
            return {
                "name": str(location.get("name") or "현재 위치"),
                "latitude": float(location["latitude"]),
                "longitude": float(location["longitude"]),
                "timezone": str(location.get("timezone") or "Asia/Seoul"),
            }
        except (KeyError, TypeError, ValueError):
            return None

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"notes": [], "todos": []}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"notes": [], "todos": []}
        return {
            "notes": list(raw.get("notes") or []),
            "todos": list(raw.get("todos") or []),
            "weather_default_location": raw.get("weather_default_location"),
        }

    def _save(self, data: dict[str, Any]) -> None:
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
        current_location: dict[str, Any] | None = None,
    ) -> None:
        self.store = FridayLocalStore(data_path)
        self.now_fn = now_fn or datetime.now
        self.port_checker = port_checker
        self.current_location = _normalize_location(current_location)

    def route(self, query: str) -> FridayAssistantResult | None:
        text = _compact(query)
        if not text:
            return None

        handled = (
            self._route_time_date(text)
            or self._route_weather_location_settings(text)
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

    def _route_weather_location_settings(
        self, text: str
    ) -> FridayAssistantResult | None:
        if "날씨 기본 위치" in text and any(k in text for k in ("알려", "뭐", "어디")):
            location = self.store.get_weather_location() or SEOUL_WEATHER_LOCATION
            source = "저장된" if self.store.get_weather_location() else "기본"
            return FridayAssistantResult(
                content=(
                    f"{source} 날씨 위치는 {location['name']}입니다. "
                    f"위도 {location['latitude']}, 경도 {location['longitude']}입니다."
                ),
                intent="weather_location_get",
                metadata={"location": location},
            )

        city_name = _extract_default_location_city(text)
        if city_name is None:
            return None
        location = KOREAN_CITY_LOCATIONS.get(city_name)
        if location is None:
            return FridayAssistantResult(
                content=(
                    f"{city_name}은 아직 지원하는 날씨 위치가 아닙니다. "
                    "지원 도시 중 하나로 설정해 주세요."
                ),
                intent="weather_location_set",
                success=False,
                metadata={"city": city_name},
            )
        self.store.set_weather_location(location)
        return FridayAssistantResult(
            content=f"날씨 기본 위치를 {location['name']}로 설정했습니다.",
            intent="weather_location_set",
            metadata={"location": location},
        )

    def _route_weather(self, text: str) -> FridayAssistantResult | None:
        if (
            "날씨" not in text
            and "비" not in text
            and not any(k in text for k in DETAIL_WEATHER_KEYWORDS)
        ):
            return None
        if not any(k in text for k in ("날씨", "비", *DETAIL_WEATHER_KEYWORDS)):
            return None

        location_result = self._resolve_weather_location(text)
        if location_result.success is False:
            return location_result
        location = location_result.metadata["location"]
        profile = (
            "detail" if any(k in text for k in DETAIL_WEATHER_KEYWORDS) else "basic"
        )
        tool_name = "weather_detail" if profile == "detail" else "weather_basic"
        try:
            import openjarvis.tools  # noqa: F401
            from openjarvis.core.registry import ToolRegistry

            if ToolRegistry.contains(tool_name):
                result = ToolRegistry.create(tool_name).execute(
                    query=text,
                    latitude=location["latitude"],
                    longitude=location["longitude"],
                    timezone=location["timezone"],
                    location_name=location["name"],
                )
            elif ToolRegistry.contains("weather"):
                result = ToolRegistry.create("weather").execute(
                    query=text,
                    profile=profile,
                    latitude=location["latitude"],
                    longitude=location["longitude"],
                    timezone=location["timezone"],
                    location_name=location["name"],
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
            metadata={
                "profile": profile,
                "tool": result.tool_name,
                "location": location,
            },
        )

    def _resolve_weather_location(self, text: str) -> FridayAssistantResult:
        city_name = _find_city_name(text)
        if city_name:
            location = KOREAN_CITY_LOCATIONS[city_name]
            return FridayAssistantResult(
                content="",
                intent="weather_location_resolve",
                metadata={"location": location},
            )

        unknown_city = _extract_unknown_weather_city(text)
        if unknown_city:
            return FridayAssistantResult(
                content=(
                    f"{unknown_city}은 아직 지원하는 날씨 도시가 아닙니다. "
                    "지원 도시를 말하거나 기본 위치를 설정해 주세요."
                ),
                intent="weather",
                success=False,
                metadata={"city": unknown_city},
            )

        location = (
            self.current_location
            or self.store.get_weather_location()
            or SEOUL_WEATHER_LOCATION
        )
        return FridayAssistantResult(
            content="",
            intent="weather_location_resolve",
            metadata={"location": location},
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
    current_location: dict[str, Any] | None = None,
) -> FridayAssistantResult | None:
    return FridayAssistantRouter(
        data_path=data_path,
        now_fn=now_fn,
        port_checker=port_checker,
        current_location=current_location,
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


def _find_city_name(text: str) -> str | None:
    for city in KOREAN_CITY_LOCATIONS:
        if city in text:
            return city
    return None


def _extract_default_location_city(text: str) -> str | None:
    if "기본 위치" not in text:
        return None
    known = _find_city_name(text)
    if known:
        return known
    patterns = (
        r"기본 위치를\s*([가-힣]{2,4})(?:으?로)\s*설정",
        r"내 기본 위치는\s*([가-힣]{2,4}?)(?:이야|야|입니다|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _extract_unknown_weather_city(text: str) -> str | None:
    candidates: list[str] = []
    patterns = (
        r"^([가-힣]{2,4})\s*(?:상세\s*)?날씨",
        r"^([가-힣]{2,4})\s*(?:자외선|풍속|습도|기압|가시거리)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            candidates.append(match.group(1))

    ignored = {
        "오늘",
        "내일",
        "이번",
        "이번주",
        "상세",
        "자세히",
        "디테일",
        "날씨",
    }
    for candidate in candidates:
        if candidate not in ignored and candidate not in KOREAN_CITY_LOCATIONS:
            return candidate
    return None


def _normalize_location(location: dict[str, Any] | None) -> dict[str, Any] | None:
    if not location:
        return None
    try:
        return {
            "name": str(location.get("name") or "현재 위치"),
            "latitude": float(location["latitude"]),
            "longitude": float(location["longitude"]),
            "timezone": str(location.get("timezone") or "Asia/Seoul"),
        }
    except (KeyError, TypeError, ValueError):
        return None


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
    "KOREAN_CITY_LOCATIONS",
    "SEOUL_WEATHER_LOCATION",
    "WEBSITE_ALIASES",
    "check_friday_status",
    "open_macos_app",
    "open_website",
    "route_friday_command",
]
