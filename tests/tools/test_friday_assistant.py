"""Tests for Friday's local assistant feature pack."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from openjarvis.core.config import JarvisConfig
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.friday_assistant import (
    KOREAN_CITY_LOCATIONS,
    SEOUL_WEATHER_LOCATION,
    FridayAssistantRouter,
    FridayLocalStore,
    check_friday_status,
    open_macos_app,
    open_website,
)
from openjarvis.navigation import TmapPlace, TmapRouteSummary
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
    assert "shell" not in run_mock.call_args.kwargs


def test_macos_app_allowlist_supports_practical_aliases():
    aliases = {
        "크롬 열어줘": "Google Chrome",
        "chrome open": "Google Chrome",
        "사파리 열어줘": "Safari",
        "safari open": "Safari",
        "메모 열어줘": "Notes",
        "notes open": "Notes",
        "계산기 열어줘": "Calculator",
        "calculator open": "Calculator",
        "터미널 열어줘": "Terminal",
        "terminal open": "Terminal",
        "카카오톡 열어줘": "KakaoTalk",
        "kakaotalk open": "KakaoTalk",
    }

    for query, app_name in aliases.items():
        with (
            patch("openjarvis.friday_assistant.platform.system", return_value="Darwin"),
            patch("openjarvis.friday_assistant.subprocess.run") as run_mock,
        ):
            result = open_macos_app(query)

        assert result.success is True
        assert result.metadata["app"] == app_name
        run_mock.assert_called_once_with(
            ["open", "-a", app_name],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "shell" not in run_mock.call_args.kwargs


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


def test_last_note_delete_removes_only_most_recent_note(tmp_path):
    path = tmp_path / "friday_data.json"
    router = FridayAssistantRouter(data_path=path)
    router.route("메모해줘: 첫 번째")
    router.route("메모해줘: 두 번째")

    result = router.route("마지막 메모 삭제")

    assert result.success is True
    assert "두 번째" in result.content
    assert FridayLocalStore(path).list_notes() == ["첫 번째"]


def test_last_note_delete_handles_empty_store(tmp_path):
    router = FridayAssistantRouter(data_path=tmp_path / "friday_data.json")

    result = router.route("마지막 메모 삭제")

    assert result.success is False
    assert result.content == "삭제할 메모가 없습니다."


def test_todo_completion_marks_matching_local_todo_done(tmp_path):
    path = tmp_path / "friday_data.json"
    router = FridayAssistantRouter(data_path=path)
    router.route("할 일 추가: 장보기")

    result = router.route("할 일 완료: 장보기")

    assert result.success is True
    assert "장보기" in result.content
    assert FridayLocalStore(path)._load()["todos"][0]["done"] is True


def test_todo_completion_by_index_is_local_and_safe(tmp_path):
    path = tmp_path / "friday_data.json"
    router = FridayAssistantRouter(data_path=path)
    router.route("할 일 추가: 장보기")
    router.route("할 일 추가: 운동")

    result = router.route("할 일 완료: 2")

    todos = FridayLocalStore(path)._load()["todos"]
    assert result.success is True
    assert "운동" in result.content
    assert todos[0]["done"] is False
    assert todos[1]["done"] is True


def test_weather_default_location_commands_persist_to_local_json(tmp_path):
    path = tmp_path / "friday_data.json"
    router = FridayAssistantRouter(data_path=path)

    set_result = router.route("내 기본 위치는 부산이야")
    get_result = router.route("날씨 기본 위치 알려줘")

    assert "부산" in set_result.content
    assert "부산" in get_result.content
    assert FridayLocalStore(path).get_weather_location()["name"] == "부산"


def test_weather_default_location_falls_back_to_seoul(tmp_path):
    router = FridayAssistantRouter(data_path=tmp_path / "friday_data.json")

    result = router._resolve_weather_location("오늘 날씨 알려줘")

    assert result.metadata["location"] == SEOUL_WEATHER_LOCATION


def test_saved_default_location_used_when_no_city_is_present(tmp_path):
    path = tmp_path / "friday_data.json"
    store = FridayLocalStore(path)
    store.set_weather_location(KOREAN_CITY_LOCATIONS["부산"])
    router = FridayAssistantRouter(data_path=path)

    result = router._resolve_weather_location("오늘 날씨 알려줘")

    assert result.metadata["location"]["name"] == "부산"


def test_city_name_detection_uses_explicit_city(tmp_path):
    router = FridayAssistantRouter(data_path=tmp_path / "friday_data.json")

    result = router._resolve_weather_location("강릉 풍속 알려줘")

    assert result.metadata["location"]["name"] == "강릉"
    assert result.metadata["location"]["latitude"] == 37.7519


def test_status_check_uses_mocked_port_checker():
    def checker(host: str, port: int, timeout: float) -> bool:
        return port in {11434, 8000}

    result = check_friday_status(checker)

    assert "Ollama (11434): 실행 중" in result.content
    assert "backend (8000): 실행 중" in result.content
    assert "Friday.app: 앱 모드 사용 중" in result.content
    assert "frontend dev server (5173): 꺼짐, 앱 모드에서는 정상" in result.content
    assert result.metadata["desktop_app_mode"] is True


def test_status_check_can_report_frontend_as_required_for_dev_server_mode():
    def checker(host: str, port: int, timeout: float) -> bool:
        return port in {11434, 8000}

    result = check_friday_status(checker, desktop_app_mode=False)

    assert "Friday.app: 앱 모드 사용 중" not in result.content
    assert "frontend dev server (5173): 응답 없음" in result.content
    assert result.metadata["desktop_app_mode"] is False


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
    assert basic_result.metadata["location"]["name"] == "서울"
    assert detail_result.content == "상세 날씨입니다."
    assert detail_result.metadata["profile"] == "detail"
    assert basic.calls == [
        {
            "query": "오늘 날씨 알려줘",
            "latitude": 37.566,
            "longitude": 126.9784,
            "timezone": "Asia/Seoul",
            "location_name": "서울",
        }
    ]
    assert detail.calls == [
        {
            "query": "습도 알려줘",
            "latitude": 37.566,
            "longitude": 126.9784,
            "timezone": "Asia/Seoul",
            "location_name": "서울",
        }
    ]


def test_city_specific_weather_routing_passes_city_coordinates(tmp_path):
    detail = _FakeWeatherTool("weather_detail", "제주 상세 날씨입니다.")
    ToolRegistry.register_value("weather_detail", lambda: detail)
    router = FridayAssistantRouter(data_path=tmp_path / "friday.json")

    result = router.route("제주 자외선 알려줘")

    assert result.metadata["profile"] == "detail"
    assert result.metadata["location"]["name"] == "제주"
    assert detail.calls[0]["latitude"] == 33.4996
    assert detail.calls[0]["longitude"] == 126.5312
    assert detail.calls[0]["location_name"] == "제주"


def test_current_location_used_for_weather_without_storing(tmp_path):
    basic = _FakeWeatherTool("weather_basic", "현재 위치 날씨입니다.")
    ToolRegistry.register_value("weather_basic", lambda: basic)
    path = tmp_path / "friday.json"
    router = FridayAssistantRouter(
        data_path=path,
        current_location={
            "name": "현재 위치",
            "latitude": 35.0,
            "longitude": 128.0,
            "timezone": "Asia/Seoul",
        },
    )

    result = router.route("오늘 날씨 알려줘")

    assert result.metadata["location"]["name"] == "현재 위치"
    assert basic.calls[0]["latitude"] == 35.0
    assert FridayLocalStore(path).get_weather_location() is None


def test_navigation_requires_current_location(tmp_path):
    router = FridayAssistantRouter(
        data_path=tmp_path / "friday.json",
        navigation_context={"tmap_api_key": "test-key"},
    )

    result = router.route("강남역까지 길안내해줘")

    assert result.success is False
    assert result.intent == "navigation"
    assert "현재 위치가 필요합니다" in result.content


def test_navigation_requires_tmap_api_key(tmp_path):
    router = FridayAssistantRouter(
        data_path=tmp_path / "friday.json",
        current_location={
            "name": "현재 위치",
            "latitude": 37.5,
            "longitude": 127.0,
            "timezone": "Asia/Seoul",
        },
    )

    result = router.route("강남역까지 길안내해줘")

    assert result.success is False
    assert result.intent == "navigation"
    assert "TMAP API 키가 필요합니다" in result.content


def test_navigation_returns_tmap_route_summary(tmp_path):
    place = TmapPlace(
        name="강남역",
        latitude=37.4979,
        longitude=127.0276,
        address="서울 강남구 테헤란로",
    )

    class FakeTmapClient:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        def search_place(self, query, *, longitude=None, latitude=None):
            assert query == "강남역"
            assert longitude == 127.0
            assert latitude == 37.5
            return place

        def route(self, *, start_longitude, start_latitude, destination, mode="car"):
            assert start_longitude == 127.0
            assert start_latitude == 37.5
            assert destination == place
            assert mode == "car"
            return TmapRouteSummary(
                destination=place,
                mode=mode,
                distance_meters=2100,
                duration_seconds=420,
                taxi_fare_won=7600,
                instructions=[
                    "테헤란로를 따라 이동하세요",
                    "강남역 방면으로 우회전하세요",
                ],
            )

    router = FridayAssistantRouter(
        data_path=tmp_path / "friday.json",
        current_location={
            "name": "현재 위치",
            "latitude": 37.5,
            "longitude": 127.0,
            "timezone": "Asia/Seoul",
        },
        navigation_context={"tmap_api_key": "test-key", "mode": "car"},
    )

    with patch("openjarvis.friday_assistant.TmapClient", FakeTmapClient):
        result = router.route("강남역까지 길안내해줘")

    assert result.success is True
    assert result.intent == "navigation"
    assert "강남역까지의 거리는 2.1Km이며" in result.content
    assert "예상 소요 시간은 약 7분입니다" in result.content
    assert "예상 택시비" not in result.content
    assert "주요 경로" not in result.content


def test_navigation_duration_question_without_navigation_keyword(tmp_path):
    place = TmapPlace(
        name="서울역",
        latitude=37.5547,
        longitude=126.9707,
        address="서울 중구",
    )

    class FakeTmapClient:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        def search_place(self, query, *, longitude=None, latitude=None):
            assert query == "서울역"
            return place

        def route(self, *, start_longitude, start_latitude, destination, mode="car"):
            return TmapRouteSummary(
                destination=destination,
                mode=mode,
                distance_meters=3200,
                duration_seconds=780,
                instructions=["한강대로를 따라 이동하세요"],
            )

    router = FridayAssistantRouter(
        data_path=tmp_path / "friday.json",
        current_location={
            "name": "현재 위치",
            "latitude": 37.5,
            "longitude": 127.0,
            "timezone": "Asia/Seoul",
        },
        navigation_context={"tmap_api_key": "test-key", "mode": "car"},
    )

    with patch("openjarvis.friday_assistant.TmapClient", FakeTmapClient):
        result = router.route("서울역 까지 얼마나 걸려?")

    assert result.intent == "navigation"
    assert "서울역까지의 거리는 3.2Km이며" in result.content
    assert "예상 소요 시간은 약 13분입니다" in result.content


def test_unknown_city_weather_returns_supported_city_message(tmp_path):
    router = FridayAssistantRouter(data_path=tmp_path / "friday.json")

    result = router.route("목포 날씨 알려줘")

    assert result.success is False
    assert "지원하는 날씨 도시가 아닙니다" in result.content


def test_weather_routing_supports_rain_question_without_weather_word(tmp_path):
    basic = _FakeWeatherTool("weather_basic", "비 예보입니다.")
    ToolRegistry.register_value("weather_basic", lambda: basic)
    router = FridayAssistantRouter(data_path=tmp_path / "friday.json")

    result = router.route("내일 비 와?")

    assert result.content == "비 예보입니다."
    assert result.metadata["profile"] == "basic"


def test_calendar_placeholder_does_not_access_cloud(tmp_path):
    router = FridayAssistantRouter(data_path=tmp_path / "friday.json")

    result = router.route("오늘 일정 보여줘")

    assert result.success is False
    assert result.intent == "calendar_placeholder"
    assert result.content == "일정 기능은 아직 로컬 캘린더 연동 설정이 필요합니다."
    assert result.metadata["local_only"] is True


def test_file_search_placeholder_uses_allowlist_policy(tmp_path):
    router = FridayAssistantRouter(data_path=tmp_path / "friday.json")

    result = router.route("파일 찾아줘")

    assert result.success is False
    assert result.intent == "file_search_placeholder"
    assert "전체 디스크는 검색하지 않습니다" in result.content
    assert result.metadata["allowlisted_folders"] == []


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
