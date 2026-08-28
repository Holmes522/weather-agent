"""统一天气数据模型，以及 OpenWeatherMap、和风天气客户端。"""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import re
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

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


class WeatherProvider(Protocol):
    """所有天气 Provider 必须实现的稳定接口。"""

    def get_current(self, city: City) -> WeatherData:
        ...

    def get_forecast(self, city: City, day_offset: int) -> WeatherData:
        ...


class OpenMeteoClient:
    """无需 API Key 的 Open-Meteo 全球预报客户端。

    官方字段与单位契约：https://open-meteo.com/en/docs
    """

    BASE_URL = "https://api.open-meteo.com/v1/forecast"
    DEFAULT_TIMEOUT: Tuple[float, float] = (3.05, 10.0)
    CURRENT_FIELDS = (
        "temperature_2m",
        "relative_humidity_2m",
        "weather_code",
        "wind_speed_10m",
        "precipitation",
    )
    DAILY_FIELDS = (
        "weather_code",
        "temperature_2m_mean",
        "relative_humidity_2m_mean",
        "wind_speed_10m_mean",
        "precipitation_probability_max",
        "precipitation_sum",
    )

    def __init__(
        self,
        request_get: RequestGet = requests.get,
        timeout: Tuple[float, float] = DEFAULT_TIMEOUT,
    ):
        self._request_get = request_get
        self._timeout = timeout

    def get_current(self, city: City) -> WeatherData:
        payload = self._request_json(
            city,
            {
                "current": ",".join(self.CURRENT_FIELDS),
                "wind_speed_unit": "ms",
            },
        )
        current = _dict_field(payload, "current")
        code = _wmo_code(current.get("weather_code"))
        precipitation = _non_negative_number(
            current.get("precipitation"), "current.precipitation"
        )
        humidity = _percentage(
            current.get("relative_humidity_2m"),
            "current.relative_humidity_2m",
        )

        return WeatherData(
            temperature_c=round(
                _number(current.get("temperature_2m"), "current.temperature_2m"),
                1,
            ),
            condition=_openmeteo_condition(code),
            humidity_percent=round(humidity),
            wind_speed_mps=round(
                _non_negative_number(
                    current.get("wind_speed_10m"), "current.wind_speed_10m"
                ),
                1,
            ),
            rain_expected=_openmeteo_rain_expected(code) or precipitation > 0,
        )

    def get_forecast(self, city: City, day_offset: int) -> WeatherData:
        payload = self._request_json(
            city,
            {
                "daily": ",".join(self.DAILY_FIELDS),
                "forecast_days": 3,
                "timezone": "auto",
                "wind_speed_unit": "ms",
            },
        )
        daily = _dict_field(payload, "daily")
        code = _wmo_code(_daily_value(daily, "weather_code", day_offset))
        probability = _percentage(
            _daily_value(daily, "precipitation_probability_max", day_offset),
            "daily.precipitation_probability_max",
        )
        precipitation = _non_negative_number(
            _daily_value(daily, "precipitation_sum", day_offset),
            "daily.precipitation_sum",
        )
        rain_expected = (
            _openmeteo_rain_expected(code)
            or precipitation > 0
            or probability >= 50
        )

        return WeatherData(
            temperature_c=round(
                _number(
                    _daily_value(daily, "temperature_2m_mean", day_offset),
                    "daily.temperature_2m_mean",
                ),
                1,
            ),
            condition="雨" if rain_expected else _openmeteo_condition(code),
            humidity_percent=round(
                _percentage(
                    _daily_value(daily, "relative_humidity_2m_mean", day_offset),
                    "daily.relative_humidity_2m_mean",
                )
            ),
            wind_speed_mps=round(
                _non_negative_number(
                    _daily_value(daily, "wind_speed_10m_mean", day_offset),
                    "daily.wind_speed_10m_mean",
                ),
                1,
            ),
            rain_expected=rain_expected,
        )

    def _request_json(
        self, city: City, provider_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        params = {
            "latitude": city.latitude,
            "longitude": city.longitude,
            **provider_params,
        }
        try:
            response = self._request_get(
                url=self.BASE_URL,
                params=params,
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, TimeoutError, ValueError) as exc:
            raise WeatherUpstreamError("Open-Meteo request failed") from exc

        if not isinstance(payload, dict):
            raise WeatherDataError("Open-Meteo response must be an object")
        return payload


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

        temperature = _number(main.get("temp"), "main.temp")
        humidity = _number(main.get("humidity"), "main.humidity")
        wind_speed = _number(wind.get("speed"), "wind.speed")
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


class QWeatherClient:
    """和风天气 v1 实时天气与每日预报客户端。"""

    DEFAULT_TIMEOUT: Tuple[float, float] = (3.05, 10.0)

    def __init__(
        self,
        api_key: str,
        api_host: str,
        request_get: RequestGet = requests.get,
        timeout: Tuple[float, float] = DEFAULT_TIMEOUT,
    ):
        if not api_key or not api_key.strip():
            raise ValueError("QWeather API key is required")

        normalized_host = api_host.strip().lower().rstrip(".") if api_host else ""
        if (
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", normalized_host)
            or ".." in normalized_host
            or not normalized_host.endswith(".qweatherapi.com")
        ):
            raise ValueError("QWeather API host must be a *.qweatherapi.com hostname")

        self._api_key = api_key.strip()
        self._api_host = normalized_host
        self._request_get = request_get
        self._timeout = timeout

    def get_current(self, city: City) -> WeatherData:
        payload = self._request_json(
            f"/weather/v1/current/{city.latitude:.4f}/{city.longitude:.4f}",
            {"localTime": "true", "lang": "zh"},
        )
        return self._normalize_current(payload)

    def get_forecast(self, city: City, day_offset: int) -> WeatherData:
        payload = self._request_json(
            f"/weather/v1/daily/{city.latitude:.4f}/{city.longitude:.4f}",
            {"days": 3, "localTime": "true", "lang": "zh"},
        )
        days = payload.get("days")
        if not isinstance(days, list) or day_offset >= len(days):
            raise WeatherDataError("QWeather forecast does not contain the requested day")
        day = days[day_offset]
        if not isinstance(day, dict):
            raise WeatherDataError("QWeather forecast day is invalid")
        return self._normalize_daily(day)

    def _request_json(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = self._request_get(
                url=f"https://{self._api_host}{path}",
                params=params,
                headers={"X-QW-Api-Key": self._api_key},
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, TimeoutError, ValueError) as exc:
            raise WeatherUpstreamError("QWeather request failed") from exc

        if not isinstance(payload, dict):
            raise WeatherDataError("QWeather response must be an object")
        return payload

    @staticmethod
    def _normalize_current(payload: Dict[str, Any]) -> WeatherData:
        condition = _dict_field(payload, "condition")
        temperature = _dict_field(payload, "temperature")
        wind = _dict_field(payload, "wind")
        wind_speed = _dict_field(wind, "speed")
        precipitation = _dict_field(payload, "precipitation")

        code = _condition_code(condition.get("code"))
        humidity = _fraction(payload.get("humidity"), "humidity")
        precipitation_type = precipitation.get("type")
        if not isinstance(precipitation_type, str):
            raise WeatherDataError("precipitation.type is invalid")

        return WeatherData(
            temperature_c=round(_number(temperature.get("value"), "temperature.value"), 1),
            condition=_qweather_condition(code),
            humidity_percent=round(humidity * 100),
            wind_speed_mps=round(_number(wind_speed.get("value"), "wind.speed.value"), 1),
            rain_expected=_qweather_rain_expected(code, precipitation_type),
        )

    @staticmethod
    def _normalize_daily(day: Dict[str, Any]) -> WeatherData:
        temperature = _dict_field(day, "temperatureAvg")
        daytime = _dict_field(day, "daytime")
        nighttime = _dict_field(day, "nighttime")
        day_condition = _dict_field(daytime, "condition")
        night_condition = _dict_field(nighttime, "condition")
        day_code = _condition_code(day_condition.get("code"))
        night_code = _condition_code(night_condition.get("code"))

        day_precipitation = _dict_field(daytime, "precipitation")
        night_precipitation = _dict_field(nighttime, "precipitation")
        precipitation_types = (
            day_precipitation.get("type"),
            night_precipitation.get("type"),
        )
        if not all(isinstance(value, str) for value in precipitation_types):
            raise WeatherDataError("forecast precipitation type is invalid")

        humidities = (
            _fraction(daytime.get("humidity"), "daytime.humidity"),
            _fraction(nighttime.get("humidity"), "nighttime.humidity"),
        )
        speeds = (
            _number(
                _dict_field(_dict_field(daytime, "wind"), "speed").get("value"),
                "daytime.wind.speed.value",
            ),
            _number(
                _dict_field(_dict_field(nighttime, "wind"), "speed").get("value"),
                "nighttime.wind.speed.value",
            ),
        )
        rain_expected = any(
            _qweather_rain_expected(code, precipitation_type)
            for code, precipitation_type in zip(
                (day_code, night_code), precipitation_types
            )
        )

        return WeatherData(
            temperature_c=round(_number(temperature.get("value"), "temperatureAvg.value"), 1),
            condition="雨" if rain_expected else _qweather_condition(day_code),
            humidity_percent=round(sum(humidities) / len(humidities) * 100),
            wind_speed_mps=round(sum(speeds) / len(speeds), 1),
            rain_expected=rain_expected,
        )


def _dict_field(payload: Dict[str, Any], field_name: str) -> Dict[str, Any]:
    value = payload.get(field_name)
    if not isinstance(value, dict):
        raise WeatherDataError(f"{field_name} is invalid")
    return value


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WeatherDataError(f"{field_name} is invalid")
    return float(value)


def _fraction(value: Any, field_name: str) -> float:
    number = _number(value, field_name)
    if not 0 <= number <= 1:
        raise WeatherDataError(f"{field_name} must be between 0 and 1")
    return number


def _percentage(value: Any, field_name: str) -> float:
    number = _number(value, field_name)
    if not 0 <= number <= 100:
        raise WeatherDataError(f"{field_name} must be between 0 and 100")
    return number


def _non_negative_number(value: Any, field_name: str) -> float:
    number = _number(value, field_name)
    if number < 0:
        raise WeatherDataError(f"{field_name} must not be negative")
    return number


def _daily_value(daily: Dict[str, Any], field_name: str, day_offset: int) -> Any:
    values = daily.get(field_name)
    if (
        not isinstance(values, list)
        or isinstance(day_offset, bool)
        or not isinstance(day_offset, int)
        or day_offset < 0
        or day_offset >= len(values)
    ):
        raise WeatherDataError(f"{field_name} does not contain the requested day")
    return values[day_offset]


def _wmo_code(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not float(value).is_integer()
        or not 0 <= int(value) <= 99
    ):
        raise WeatherDataError("weather_code is invalid")
    return int(value)


def _openmeteo_condition(code: int) -> str:
    if code == 0:
        return "晴"
    if code in {1, 2}:
        return "多云"
    if code == 3:
        return "阴"
    if code in {45, 48}:
        return "雾"
    if code in {51, 53, 55, 56, 57}:
        return "毛毛雨"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "雨"
    if code in {71, 73, 75, 77, 85, 86}:
        return "雪"
    if code in {95, 96, 99}:
        return "雷雨"
    return "天气"


def _openmeteo_rain_expected(code: int) -> bool:
    return code in {
        51,
        53,
        55,
        56,
        57,
        61,
        63,
        65,
        66,
        67,
        80,
        81,
        82,
        95,
        96,
        99,
    }


def _condition_code(value: Any) -> int:
    if not isinstance(value, str) or not value.isdigit():
        raise WeatherDataError("condition.code is invalid")
    return int(value)


def _qweather_condition(code: int) -> str:
    if code == 100:
        return "晴"
    if 101 <= code <= 103:
        return "多云"
    if code == 104:
        return "阴"
    if 302 <= code <= 304:
        return "雷雨"
    if 300 <= code <= 399:
        return "雨"
    if 404 <= code <= 406:
        return "雨夹雪"
    if 400 <= code <= 499:
        return "雪"
    if code in {500, 501, 509, 510, 514, 515}:
        return "雾"
    if code in {502, 511, 512, 513}:
        return "霾"
    if code in {503, 504, 507, 508}:
        return "沙尘"
    if code == 900:
        return "高温"
    if code == 901:
        return "严寒"
    return "天气"


def _qweather_rain_expected(code: int, precipitation_type: str) -> bool:
    return (
        300 <= code <= 399
        or 404 <= code <= 406
        or precipitation_type.lower() in {"rain", "mixed"}
    )
