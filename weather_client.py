"""OpenWeatherMap Current Weather 与 5 Day / 3 Hour Forecast 客户端。"""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from parser import City


class WeatherClientError(Exception):
    """天气上游调用或响应处理失败。"""


class WeatherUpstreamError(WeatherClientError):
    """网络、HTTP 状态码或 JSON 解码失败。"""


class WeatherDataError(WeatherClientError):
    """上游响应缺少 MVP 所需字段。"""


@dataclass(frozen=True)
class WeatherData:
    temperature_c: float
    condition: str
    humidity_percent: int
    wind_speed_mps: float
    rain_expected: bool


RequestGet = Callable[..., Any]


class OpenWeatherClient:
    """使用官方 weather/forecast 接口，所有请求都设置连接和读取超时。"""

    BASE_URL = "https://api.openweathermap.org/data/2.5"
    DEFAULT_TIMEOUT: Tuple[float, float] = (3.05, 10.0)

    def __init__(
        self,
        api_key: str,
        request_get: RequestGet = requests.get,
        timeout: Tuple[float, float] = DEFAULT_TIMEOUT,
    ):
        if not api_key or not api_key.strip():
            raise ValueError("OpenWeatherMap API key is required")
        self._api_key = api_key.strip()
        self._request_get = request_get
        self._timeout = timeout

    def get_current(self, city: City) -> WeatherData:
        payload = self._request_json("/weather", city)
        return self._normalize_weather(payload)

    def get_forecast(
        self,
        city: City,
        day_offset: int,
        now: Optional[datetime] = None,
    ) -> WeatherData:
        payload = self._request_json("/forecast", city)
        target_date = self._target_local_date(payload, day_offset, now)
        items = payload.get("list")
        if not isinstance(items, list):
            raise WeatherDataError("forecast list is missing")

        city_timezone = self._city_timezone(payload)
        matching_items = [
            item
            for item in items
            if isinstance(item, dict)
            and self._timestamp_to_date(item.get("dt"), city_timezone) == target_date
        ]
        if not matching_items:
            raise WeatherDataError("forecast does not contain the requested date")

        normalized = [self._normalize_weather(item) for item in matching_items]
        return WeatherData(
            temperature_c=round(sum(item.temperature_c for item in normalized) / len(normalized), 1),
            condition=self._aggregate_condition(normalized),
            humidity_percent=round(
                sum(item.humidity_percent for item in normalized) / len(normalized)
            ),
            wind_speed_mps=round(
                sum(item.wind_speed_mps for item in normalized) / len(normalized), 1
            ),
            rain_expected=any(item.rain_expected for item in normalized),
        )

    def _request_json(self, path: str, city: City) -> Dict[str, Any]:
        params = {
            "lat": city.latitude,
            "lon": city.longitude,
            "appid": self._api_key,
            "units": "metric",
            "lang": "zh_cn",
        }
        try:
            response = self._request_get(
                url=f"{self.BASE_URL}{path}",
                params=params,
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, TimeoutError, ValueError) as exc:
            raise WeatherUpstreamError("OpenWeatherMap request failed") from exc

        if not isinstance(payload, dict):
            raise WeatherDataError("weather response must be an object")
        return payload

    @staticmethod
    def _normalize_weather(payload: Dict[str, Any]) -> WeatherData:
        main = payload.get("main")
        wind = payload.get("wind")
        weather = payload.get("weather")
        if not isinstance(main, dict) or not isinstance(wind, dict):
            raise WeatherDataError("weather main or wind is missing")
        if not isinstance(weather, list) or not weather or not isinstance(weather[0], dict):
            raise WeatherDataError("weather condition is missing")

        temperature = OpenWeatherClient._number(main.get("temp"), "main.temp")
        humidity = OpenWeatherClient._number(main.get("humidity"), "main.humidity")
        wind_speed = OpenWeatherClient._number(wind.get("speed"), "wind.speed")
        raw_condition = weather[0].get("main")
        if not isinstance(raw_condition, str):
            raise WeatherDataError("weather.main is missing")

        condition = OpenWeatherClient._condition_label(raw_condition)
        return WeatherData(
            temperature_c=round(temperature, 1),
            condition=condition,
            humidity_percent=round(humidity),
            wind_speed_mps=round(wind_speed, 1),
            rain_expected=raw_condition.lower() in {"rain", "drizzle", "thunderstorm"},
        )

    @staticmethod
    def _number(value: Any, field_name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise WeatherDataError(f"{field_name} is invalid")
        return float(value)

    @staticmethod
    def _condition_label(raw_condition: str) -> str:
        labels = {
            "clear": "晴",
            "clouds": "阴",
            "rain": "雨",
            "drizzle": "雨",
            "thunderstorm": "雷雨",
            "snow": "雪",
            "mist": "雾",
            "smoke": "雾",
            "haze": "雾",
            "dust": "沙尘",
            "fog": "雾",
            "sand": "沙尘",
            "ash": "火山灰",
            "squall": "强风",
            "tornado": "龙卷风",
        }
        return labels.get(raw_condition.strip().lower(), "天气")

    @staticmethod
    def _aggregate_condition(items: List[WeatherData]) -> str:
        if any(item.condition == "雷雨" for item in items):
            return "雷雨"
        if any(item.rain_expected for item in items):
            return "雨"
        counts = Counter(item.condition for item in items)
        return counts.most_common(1)[0][0]

    @staticmethod
    def _city_timezone(payload: Dict[str, Any]) -> timezone:
        city = payload.get("city")
        offset = city.get("timezone") if isinstance(city, dict) else None
        if isinstance(offset, bool) or not isinstance(offset, (int, float)):
            raise WeatherDataError("city timezone is missing")
        return timezone(timedelta(seconds=int(offset)))

    @staticmethod
    def _timestamp_to_date(timestamp: Any, city_timezone: timezone) -> Optional[date]:
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            return None
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(city_timezone).date()
        except (OverflowError, OSError, ValueError):
            return None

    @classmethod
    def _target_local_date(
        cls,
        payload: Dict[str, Any],
        day_offset: int,
        now: Optional[datetime],
    ) -> date:
        city_timezone = cls._city_timezone(payload)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(city_timezone).date() + timedelta(days=day_offset)
