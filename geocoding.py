"""将任意地点名称解析为天气 Provider 共用的经纬度。"""

from dataclasses import dataclass
from math import isfinite
from threading import Lock
from time import monotonic, sleep
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from parser import City, SUPPORTED_CITIES


class GeocodingError(Exception):
    """地理编码网络失败或上游响应不符合契约。"""


@dataclass(frozen=True)
class CityResolution:
    city: City
    corrected_from: Optional[str] = None


RequestGet = Callable[..., Any]


class NominatimCityResolver:
    """带缓存和串行限速的 Nominatim 城市解析器。"""

    DEFAULT_BASE_URL = "https://nominatim.openstreetmap.org/search"
    DEFAULT_USER_AGENT = (
        "weather-agent/1.0 (https://github.com/Holmes522/weather-agent)"
    )
    CONFIRMED_ALIASES = {
        "大利": "大理",
    }
    _TYPE_PRIORITY = {
        "city": 0,
        "municipality": 1,
        "town": 2,
        "region": 3,
        "county": 4,
        "village": 5,
        "hamlet": 6,
    }

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: Tuple[float, float] = (3.05, 10.0),
        request_get: RequestGet = requests.get,
        min_interval_seconds: float = 1.0,
        max_cache_size: int = 10_000,
        clock: Callable[[], float] = monotonic,
        sleeper: Callable[[float], None] = sleep,
    ):
        if not base_url.startswith("https://"):
            raise ValueError("geocoding base URL must use HTTPS")
        if not user_agent.strip() or min_interval_seconds < 0 or max_cache_size < 1:
            raise ValueError("invalid geocoding configuration")
        self._base_url = base_url
        self._user_agent = user_agent.strip()
        self._timeout = timeout
        self._request_get = request_get
        self._min_interval_seconds = min_interval_seconds
        self._max_cache_size = max_cache_size
        self._clock = clock
        self._sleeper = sleeper
        self._cache: Dict[str, Optional[CityResolution]] = {}
        self._cache_lock = Lock()
        self._request_lock = Lock()
        self._last_request_at: Optional[float] = None

    def resolve(self, location_term: str) -> Optional[CityResolution]:
        """返回确认后的城市；没有匹配时返回 None。"""

        normalized = location_term.strip()
        if not normalized:
            return None
        corrected_name = self.CONFIRMED_ALIASES.get(normalized, normalized)
        corrected_from = normalized if corrected_name != normalized else None

        known_city = SUPPORTED_CITIES.get(corrected_name)
        if known_city is not None:
            return CityResolution(known_city, corrected_from)

        cache_key = corrected_name.casefold()
        with self._cache_lock:
            if cache_key in self._cache:
                cached = self._cache[cache_key]
                if cached is None or corrected_from is None:
                    return cached
                return CityResolution(cached.city, corrected_from)

        resolution = self._request_resolution(corrected_name, corrected_from)
        with self._cache_lock:
            if cache_key not in self._cache and len(self._cache) >= self._max_cache_size:
                self._cache.pop(next(iter(self._cache)))
            self._cache[cache_key] = resolution
        return resolution

    def _request_resolution(
        self, query_name: str, corrected_from: Optional[str]
    ) -> Optional[CityResolution]:
        with self._request_lock:
            now = self._clock()
            if self._last_request_at is not None:
                remaining = self._min_interval_seconds - (now - self._last_request_at)
                if remaining > 0:
                    self._sleeper(remaining)
            try:
                response = self._request_get(
                    url=self._base_url,
                    params={
                        "q": query_name,
                        "format": "jsonv2",
                        "limit": 5,
                        "accept-language": "zh-CN,zh,en",
                        "addressdetails": 1,
                        "featureType": "settlement",
                    },
                    headers={"User-Agent": self._user_agent},
                    timeout=self._timeout,
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError, TypeError) as error:
                raise GeocodingError("geocoding request failed") from error
            finally:
                self._last_request_at = self._clock()

        if not isinstance(payload, list):
            raise GeocodingError("geocoding response must be a list")
        if not payload:
            return None

        candidates = self._valid_candidates(payload)
        if not candidates:
            raise GeocodingError("geocoding response has no valid city")
        _priority, _negative_importance, latitude, longitude, country_code = min(
            candidates
        )
        return CityResolution(
            City(query_name, latitude, longitude, country_code), corrected_from
        )

    def _valid_candidates(
        self, payload: List[object]
    ) -> List[Tuple[int, float, float, float, str]]:
        candidates = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                latitude = float(item["lat"])
                longitude = float(item["lon"])
                importance = float(item.get("importance", 0))
            except (KeyError, TypeError, ValueError):
                continue
            if (
                not isfinite(latitude)
                or not isfinite(longitude)
                or not -90 <= latitude <= 90
                or not -180 <= longitude <= 180
            ):
                continue
            address = item.get("address")
            country_code = address.get("country_code") if isinstance(address, dict) else None
            if not isinstance(country_code, str) or len(country_code) != 2:
                continue
            address_type = item.get("addresstype")
            priority = self._TYPE_PRIORITY.get(address_type, 20)
            candidates.append(
                (priority, -importance, latitude, longitude, country_code.upper())
            )
        return candidates
