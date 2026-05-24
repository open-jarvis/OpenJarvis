"""Tests for Friday's local assistant feature pack."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from openjarvis.core.config import JarvisConfig
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.friday_assistant import (
    FridayAssistantRouter,
    FridayLocalStore,
    check_friday_status,
    open_macos_app,
    open_website,
)
from openjarvis.sdk import Jarvis
from openjarvis.tools._stubs import BaseTool, ToolSpec


class _FakeWeatherTool(BaseTool):
    tool_id = "fake_weather"

    def __init__(self, name: str, content: str) -> None:
        self._name = name
        self._content = content
        self.calls = []

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name=self._name, description="fake")

    def execute(self, **params):
        self.calls.append(params)
        return ToolResult(tool_name=self._name, content=self._content, success=True)


def test_korean_time_date_intents_use_local_clock(tmp_path):
    now = datetime(2026, 5, 25, 9, 7)
    router = FridayAssistantRouter(
        data_path=tmp_path / "friday.json",
        now_fn=lambda: now,
    )

    assert router.route("지금 몇 시야?").content == "지금은 9시 07분입니다."
    assert router.route("오늘 날짜 알려줘").content == "오늘은 2026년 5월 25일입니다."
    assert router.route("오늘 무슨 요일이야?").content == "오늘은 월요일입니다."


def test_website_allowlist_routing_opens_supported_alias():
    with patch("openjarvis.friday_assistant.webbrowser.open") as open_mock:
        result = open_website("유튜브 열어줘")

    assert result.success is True
    assert "https://www.youtube.com" in result.content
    open_mock.assert_called_once_with("https://www.youtube.com")


def test_website_allowlist_rejects_unknown_target():
    with patch("openjarvis.friday_assistant.webbrowser.open") as open_mock:
        result = open_website("unknown-site")

    assert result.success is False
    open_mock.assert_not_called()


def test_macos_app_allowlist_uses_subprocess_list_args():
    with (
        patch("openjarvis.friday_assistant.platform.system", return_value="Darwin"),
        patch("openjarvis.friday_assistant.subprocess.run") as run_mock,
    ):
        result = open_macos_app("계산기 켜줘")

    assert result.success is True
    assert "Calculator 앱을 열었습니다" in result.content
    run_mock.assert_called_once_with(
        ["open", "-a", "Calculator"],
        check=True,
        capture_output=True,
        text=True,
    )


def test_macos_app_allowlist_rejects_unknown_app():
    with patch("openjarvis.friday_assistant.subprocess.run") as run_mock:
        result = open_macos_app("아무 앱이나 열어줘")

    assert result.success is False
    run_mock.assert_not_called()


def test_notes_and_todos_persist_to_local_json(tmp_path):
    path = tmp_path / "friday_data.json"
    router = FridayAssistantRouter(data_path=path)

    assert "메모했습니다" in router.route("메모해줘: 우산 챙기기").content
    assert "할 일을 추가했습니다" in router.route("할 일 추가: 장보기").content

    store = FridayLocalStore(path)
    assert store.list_notes() == ["우산 챙기기"]
    assert store.list_todos() == ["장보기"]
    assert "우산 챙기기" in router.route("메모 목록 보여줘").content
    assert "장보기" in router.route("할 일 목록 보여줘").content


def test_status_check_uses_mocked_port_checker():
    def checker(host: str, port: int, timeout: float) -> bool:
        return port in {11434, 8000}

    result = check_friday_status(checker)

    assert "Ollama (11434): 실행 중" in result.content
    assert "backend (8000): 실행 중" in result.content
    assert "frontend (5173): 응답 없음" in result.content


def test_weather_routing_uses_basic_and_detail_tools(tmp_path):
    basic = _FakeWeatherTool("weather_basic", "기본 날씨입니다.")
    detail = _FakeWeatherTool("weather_detail", "상세 날씨입니다.")
    ToolRegistry.register_value("weather_basic", lambda: basic)
    ToolRegistry.register_value("weather_detail", lambda: detail)
    router = FridayAssistantRouter(data_path=tmp_path / "friday.json")

    basic_result = router.route("오늘 날씨 알려줘")
    detail_result = router.route("습도 알려줘")

    assert basic_result.content == "기본 날씨입니다."
    assert basic_result.metadata["profile"] == "basic"
    assert detail_result.content == "상세 날씨입니다."
    assert detail_result.metadata["profile"] == "detail"
    assert basic.calls == [{"query": "오늘 날씨 알려줘"}]
    assert detail.calls == [{"query": "습도 알려줘"}]


def test_unmatched_message_falls_back_to_existing_llm_route(monkeypatch):
    cfg = JarvisConfig()
    cfg.agent.context_from_memory = False
    jarvis = Jarvis(config=cfg)
    fake_engine = MagicMock()
    fake_engine.generate.return_value = {"content": "LLM 답변", "usage": {}}
    jarvis._engine = fake_engine
    jarvis._resolved_engine_key = "mock"
    monkeypatch.setattr(jarvis, "_ensure_engine", lambda: None)

    result = jarvis.ask_full("이건 일반 대화야")

    assert result["content"] == "LLM 답변"
    fake_engine.generate.assert_called_once()
