"""Tests for TMAP navigation response formatting."""

from __future__ import annotations

import httpx
import pytest

from openjarvis.navigation import (
    TmapClient,
    TmapNavigationError,
    TmapPlace,
    TmapRouteSummary,
    format_navigation_summary,
)
from openjarvis.navigation.tmap import TMAP_CAR_ROUTE_URL


def test_format_navigation_summary_is_concise_route_summary():
    destination = TmapPlace(
        name="서울역",
        longitude=126.9707,
        latitude=37.5547,
        address="서울 중구",
    )
    summary = TmapRouteSummary(
        destination=destination,
        mode="walk",
        distance_meters=850,
        duration_seconds=540,
        instructions=[
            "출발지에서 남쪽으로 20m 이동",
            "서울로7017, 300m",
            "횡단보도를 건너세요",
            "횡단보도를 건너세요",
        ],
    )

    result = format_navigation_summary(summary)

    assert "서울역까지의 거리는 850m이며, 예상 소요 시간은 약 9분입니다" in result
    assert "주요 경로" not in result
    assert "목적지는" not in result


def test_format_navigation_summary_deduplicates_repeated_road_descriptions():
    destination = TmapPlace(name="서울역", longitude=126.9707, latitude=37.5547)
    summary = TmapRouteSummary(
        destination=destination,
        mode="car",
        distance_meters=4100,
        duration_seconds=1440,
        instructions=[
            "삼일대로10길을 따라",
            "삼일대로10길",
            "우회전 후 삼일대로10길을 따라",
            "수표로를 따라",
            "한강대로를 따라",
        ],
    )

    result = format_navigation_summary(summary)

    assert "서울역까지의 거리는 4.1Km이며" in result
    assert "주요 경로" not in result


def test_car_route_uses_current_tmap_routes_endpoint(monkeypatch):
    calls = []
    destination = TmapPlace(name="부산역", longitude=129.0403, latitude=35.1152)

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "features": [
                    {
                        "properties": {
                            "totalDistance": 1000,
                            "totalTime": 300,
                            "roadName": "중앙대로",
                            "description": "직진하세요",
                        }
                    }
                ]
            }

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)

    result = TmapClient("test-key").route(
        start_longitude=126.9784,
        start_latitude=37.566,
        destination=destination,
        mode="car",
    )

    assert calls[0][0] == TMAP_CAR_ROUTE_URL
    assert calls[0][0] == "https://apis.openapi.sk.com/tmap/routes"
    assert result.distance_meters == 1000
    assert result.instructions == ["중앙대로"]


def test_tmap_403_error_is_user_friendly(monkeypatch):
    destination = TmapPlace(name="부산역", longitude=129.0403, latitude=35.1152)

    class FakeResponse:
        status_code = 403

        def raise_for_status(self):
            request = httpx.Request("POST", TMAP_CAR_ROUTE_URL)
            response = httpx.Response(403, request=request)
            raise httpx.HTTPStatusError(
                "Client error '403 Forbidden'",
                request=request,
                response=response,
            )

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(TmapNavigationError) as excinfo:
        TmapClient("test-key").route(
            start_longitude=126.9784,
            start_latitude=37.566,
            destination=destination,
            mode="car",
        )

    assert "권한이 거절되었습니다" in str(excinfo.value)
    assert "API 상품이 활성화" in str(excinfo.value)
