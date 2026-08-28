import pytest

from parser import parse_query
from weather_client import OpenMeteoClient, WeatherDataError, WeatherUpstreamError


class FakeResponse:
    def __init__(self, payload, status_error=None):
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        return self.payload


def test_openmeteo_current_weather_is_normalized_without_api_key():
    city = parse_query("北京今天天气").city
    response = FakeResponse(
        {
            "current": {
                "temperature_2m": 21.6,
                "relative_humidity_2m": 68,
                "weather_code": 61,
                "wind_speed_10m": 4.2,
                "precipitation": 0.4,
            }
        }
    )
    calls = []

    def fake_get(**kwargs):
        calls.append(kwargs)
        return response

    result = OpenMeteoClient(request_get=fake_get).get_current(city)

    assert result.temperature_c == 21.6
    assert result.condition == "雨"
    assert result.humidity_percent == 68
    assert result.wind_speed_mps == 4.2
    assert result.rain_expected is True
    assert calls[0]["url"] == "https://api.open-meteo.com/v1/forecast"
    assert calls[0]["params"]["latitude"] == city.latitude
    assert calls[0]["params"]["longitude"] == city.longitude
    assert calls[0]["params"]["wind_speed_unit"] == "ms"
    assert "temperature_2m" in calls[0]["params"]["current"]
    assert calls[0]["timeout"] == (3.05, 10.0)


def test_openmeteo_forecast_uses_requested_day_and_rain_probability():
    city = parse_query("上海明天会下雨吗？").city
    response = FakeResponse(
        {
            "daily": {
                "time": ["2026-08-28", "2026-08-29", "2026-08-30"],
                "weather_code": [2, 80, 3],
                "temperature_2m_mean": [26.0, 18.6, 22.0],
                "relative_humidity_2m_mean": [61, 83, 70],
                "wind_speed_10m_mean": [2.1, 3.7, 2.8],
                "precipitation_probability_max": [5, 72, 10],
                "precipitation_sum": [0.0, 4.5, 0.0],
            }
        }
    )
    calls = []

    def fake_get(**kwargs):
        calls.append(kwargs)
        return response

    result = OpenMeteoClient(request_get=fake_get).get_forecast(city, day_offset=1)

    assert result.temperature_c == 18.6
    assert result.condition == "雨"
    assert result.humidity_percent == 83
    assert result.wind_speed_mps == 3.7
    assert result.rain_expected is True
    assert calls[0]["params"]["timezone"] == "auto"
    assert calls[0]["params"]["forecast_days"] == 3
    assert "precipitation_probability_max" in calls[0]["params"]["daily"]


def test_openmeteo_rejects_invalid_percentage_from_upstream():
    city = parse_query("广州后天天气").city
    response = FakeResponse(
        {
            "daily": {
                "weather_code": [0, 0, 0],
                "temperature_2m_mean": [20, 21, 22],
                "relative_humidity_2m_mean": [60, 70, 150],
                "wind_speed_10m_mean": [1, 2, 3],
                "precipitation_probability_max": [0, 0, 0],
                "precipitation_sum": [0, 0, 0],
            }
        }
    )
    client = OpenMeteoClient(request_get=lambda **kwargs: response)

    with pytest.raises(WeatherDataError):
        client.get_forecast(city, day_offset=2)


def test_openmeteo_wraps_network_errors():
    city = parse_query("深圳天气").city

    def fake_get(**kwargs):
        raise TimeoutError("network is slow")

    client = OpenMeteoClient(request_get=fake_get)

    with pytest.raises(WeatherUpstreamError):
        client.get_current(city)
