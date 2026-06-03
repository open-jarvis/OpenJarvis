"""TMAP route and POI helpers for Korean navigation-style replies."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

TMAP_POI_URL = "https://apis.openapi.sk.com/tmap/pois"
TMAP_CAR_ROUTE_URL = "https://apis.openapi.sk.com/tmap/routes"
TMAP_PEDESTRIAN_ROUTE_URL = "https://apis.openapi.sk.com/tmap/routes/pedestrian"


class TmapNavigationError(RuntimeError):
    """Raised when TMAP cannot resolve a route."""


@dataclass(slots=True)
class TmapPlace:
    name: str
    longitude: float
    latitude: float
    address: str = ""
    poi_id: str = ""


@dataclass(slots=True)
class TmapRouteSummary:
    destination: TmapPlace
    mode: str
    distance_meters: int = 0
    duration_seconds: int = 0
    fare_won: int = 0
    taxi_fare_won: int = 0
    instructions: list[str] = field(default_factory=list)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _pois_from_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    pois = data.get("searchPoiInfo", {}).get("pois", {}).get("poi", [])
    if isinstance(pois, dict):
        return [pois]
    if isinstance(pois, list):
        return [poi for poi in pois if isinstance(poi, dict)]
    return []


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _raise_for_tmap_status(response: httpx.Response, api_name: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if status_code in {401, 403}:
            raise TmapNavigationError(
                f"{api_name} 권한이 거절되었습니다. TMAP API 키가 맞는지, "
                "그리고 TMAP 콘솔에서 해당 API 상품이 활성화되어 있는지 확인해주세요."
            ) from exc
        if status_code == 429:
            raise TmapNavigationError(
                f"{api_name} 호출 한도를 초과했습니다. 잠시 후 다시 시도해주세요."
            ) from exc
        raise TmapNavigationError(
            f"{api_name} 호출에 실패했습니다. HTTP {status_code}"
        ) from exc


class TmapClient:
    """Small REST client for TMAP POI and route APIs."""

    def __init__(self, api_key: str, *, timeout: float = 20.0) -> None:
        self.api_key = api_key.strip()
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise TmapNavigationError("TMAP API 키가 필요합니다.")
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "appKey": self.api_key,
        }

    def search_place(
        self,
        query: str,
        *,
        longitude: float | None = None,
        latitude: float | None = None,
    ) -> TmapPlace:
        params: dict[str, Any] = {
            "version": "1",
            "searchKeyword": query,
            "searchType": "all",
            "page": 1,
            "count": 5,
            "resCoordType": "WGS84GEO",
            "reqCoordType": "WGS84GEO",
            "multiPoint": "N",
            "poiGroupYn": "N",
        }
        if longitude is not None and latitude is not None:
            params.update({"centerLon": longitude, "centerLat": latitude})
        response = httpx.get(
            TMAP_POI_URL,
            params=params,
            headers=self._headers(),
            timeout=self.timeout,
        )
        _raise_for_tmap_status(response, "TMAP 장소 검색")
        pois = _pois_from_response(response.json())
        if not pois:
            raise TmapNavigationError(f"{query} 목적지를 찾지 못했습니다.")

        poi = pois[0]
        name = _first_text(poi.get("name"), poi.get("orgName"), query)
        longitude_value = _to_float(poi.get("frontLon") or poi.get("noorLon"))
        latitude_value = _to_float(poi.get("frontLat") or poi.get("noorLat"))
        if not longitude_value or not latitude_value:
            raise TmapNavigationError(f"{name}의 좌표를 찾지 못했습니다.")
        address = " ".join(
            part
            for part in [
                _first_text(poi.get("upperAddrName")),
                _first_text(poi.get("middleAddrName")),
                _first_text(poi.get("lowerAddrName")),
                _first_text(poi.get("roadName")),
            ]
            if part
        )
        return TmapPlace(
            name=name,
            longitude=longitude_value,
            latitude=latitude_value,
            address=address,
            poi_id=str(poi.get("id") or ""),
        )

    def route(
        self,
        *,
        start_longitude: float,
        start_latitude: float,
        destination: TmapPlace,
        mode: str = "car",
    ) -> TmapRouteSummary:
        if mode == "walk":
            return self._pedestrian_route(
                start_longitude=start_longitude,
                start_latitude=start_latitude,
                destination=destination,
            )
        return self._car_route(
            start_longitude=start_longitude,
            start_latitude=start_latitude,
            destination=destination,
        )

    def _car_route(
        self,
        *,
        start_longitude: float,
        start_latitude: float,
        destination: TmapPlace,
    ) -> TmapRouteSummary:
        payload = {
            "reqCoordType": "WGS84GEO",
            "resCoordType": "WGS84GEO",
            "startX": start_longitude,
            "startY": start_latitude,
            "endX": destination.longitude,
            "endY": destination.latitude,
            "startName": "현재 위치",
            "endName": destination.name,
            "searchOption": "0",
            "trafficInfo": "Y",
            "endRpFlag": "G",
        }
        response = httpx.post(
            TMAP_CAR_ROUTE_URL,
            params={"version": "1"},
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        _raise_for_tmap_status(response, "TMAP 자동차 경로 안내")
        return _parse_route_response(response.json(), destination, mode="car")

    def _pedestrian_route(
        self,
        *,
        start_longitude: float,
        start_latitude: float,
        destination: TmapPlace,
    ) -> TmapRouteSummary:
        payload = {
            "startX": start_longitude,
            "startY": start_latitude,
            "endX": destination.longitude,
            "endY": destination.latitude,
            "startName": "현재 위치",
            "endName": destination.name,
            "reqCoordType": "WGS84GEO",
            "resCoordType": "WGS84GEO",
        }
        response = httpx.post(
            TMAP_PEDESTRIAN_ROUTE_URL,
            params={"version": "1"},
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        _raise_for_tmap_status(response, "TMAP 도보 경로 안내")
        return _parse_route_response(response.json(), destination, mode="walk")


def _parse_route_response(
    data: dict[str, Any],
    destination: TmapPlace,
    *,
    mode: str,
) -> TmapRouteSummary:
    features = data.get("features") or []
    if not isinstance(features, list) or not features:
        raise TmapNavigationError("경로 정보를 찾지 못했습니다.")

    summary = TmapRouteSummary(destination=destination, mode=mode)
    instructions: list[str] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") or {}
        if not isinstance(properties, dict):
            continue
        summary.distance_meters = summary.distance_meters or _to_int(
            properties.get("totalDistance")
        )
        summary.duration_seconds = summary.duration_seconds or _to_int(
            properties.get("totalTime")
        )
        summary.fare_won = summary.fare_won or _to_int(properties.get("totalFare"))
        summary.taxi_fare_won = summary.taxi_fare_won or _to_int(
            properties.get("taxiFare")
        )
        instruction = _first_text(
            properties.get("roadName"),
            properties.get("name"),
            properties.get("description"),
        )
        if instruction and instruction not in instructions:
            instructions.append(instruction)
    summary.instructions = instructions[:8]
    return summary


def _format_distance(meters: int) -> str:
    if meters >= 1000:
        return f"{meters / 1000:.1f}Km"
    return f"{meters}m"


def _format_duration(seconds: int) -> str:
    minutes = max(1, round(seconds / 60))
    hours, rem = divmod(minutes, 60)
    if hours:
        return f"{hours}시간 {rem}분" if rem else f"{hours}시간"
    return f"{minutes}분"


def _clean_route_instruction(instruction: str) -> str:
    cleaned = re.sub(r"\s+", " ", instruction.strip())
    cleaned = re.sub(r"\s*,\s*\d+(?:\.\d+)?m$", "", cleaned)
    cleaned = re.sub(r"\s*\d+(?:\.\d+)?m\s*이동$", "", cleaned)
    cleaned = cleaned.replace("교차로에서 ", "")
    road_match = re.search(
        r"(?:후\s*)?([가-힣A-Za-z0-9·.-]+(?:로|길|대로|번길))을?를?\s*따라",
        cleaned,
    )
    if road_match:
        cleaned = road_match.group(1)
    return cleaned.strip(" ,.")


def _summarize_route_path(instructions: list[str], *, limit: int = 3) -> list[str]:
    route_parts: list[str] = []
    seen: set[str] = set()
    for instruction in instructions:
        cleaned = _clean_route_instruction(instruction)
        if not cleaned or cleaned in seen:
            continue
        if len(cleaned) < 3:
            continue
        seen.add(cleaned)
        route_parts.append(cleaned)
        if len(route_parts) >= limit:
            break
    return route_parts


def format_navigation_summary(summary: TmapRouteSummary) -> str:
    """Return a Korean navigation-style summary."""
    distance = _format_distance(summary.distance_meters)
    duration = _format_duration(summary.duration_seconds)
    return (
        f"{summary.destination.name}까지의 거리는 {distance}이며, "
        f"예상 소요 시간은 약 {duration}입니다."
    )
