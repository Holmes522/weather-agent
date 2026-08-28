from datetime import datetime, timezone

import pytest

from parser import parse_query
from weather_client import (
    OpenWeatherClient,
    WeatherDataError,
    WeatherUpstreamError,
)


class FakeResponse:
    def __init__(self, payload, status_error=None):
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        return self.payload


def test_current_weather_is_normalized_to_metric_fields():
    city = parse_query("北京今天天气").city
    response = FakeResponse(
        {
            "main": {"temp": 22.4, "humidity": 48},
            "weather": [{"main": "Clear"}],
            "wind": {"speed": 3.2},
        }
    )
    calls = []

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        return response

    client = OpenWeatherClient("test-key", request_get=fake_get)
    result = client.get_current(city)

    assert result.temperature_c == 22.4
    assert result.condition == "晴"
    assert result.humidity_percent == 48
    assert result.wind_speed_mps == 3.2
    assert result.rain_expected is False
    assert calls[0][1]["units"] == "metric"
    assert calls[0][1]["appid"] == "test-key"
    assert calls[0][2] == (3.05, 10.0)


def test_forecast_aggregates_rain_for_target_local_date():
    city = parse_query("上海明天会下雨吗？").city
    base = datetime(2026, 8, 28, 12, tzinfo=timezone.utc).timestamp()
    response = FakeResponse(
        {
            "city": {"timezone": 8 * 60 * 60},
            "list": [
                {
                    "dt": int(base) + 24 * 60 * 60,
                    "main": {"temp": 25.0, "humidity": 80},
                    "weather": [{"main": "Rain"}],
                    "wind": {"speed": 2.0},
                    "rain": {"3h": 1.4},
                },
                {
                    "dt": int(base) + 27 * 60 * 60,
                    "main": {"temp": 27.0, "humidity": 70},
                    "weather": [{"main": "Clouds"}],
                    "wind": {"speed": 4.0},
                },
            ],
        }
    )

    client = OpenWeatherClient("test-key", request_get=lambda **kwargs: response)
    result = client.get_forecast(
        city,
        day_offset=1,
        now=datetime(2026, 8, 28, 8, tzinfo=timezone.utc),
    )

    assert result.temperature_c == 26.0
    assert result.condition == "雨"
    assert result.humidity_percent == 75
    assert result.wind_speed_mps == 3.0
    assert result.rain_expected is True


def test_forecast_without_target_date_raises_data_error():
    city = parse_query("广州后天天气").city
    response = FakeResponse({"city": {"timezone": 8 * 60 * 60}, "list": []})
    client = OpenWeatherClient("test-key", request_get=lambda **kwargs: response)

    with pytest.raises(WeatherDataError):
        client.get_forecast(
            city,
            day_offset=2,
            now=datetime(2026, 8, 28, 8, tzinfo=timezone.utc),
        )


def test_upstream_request_error_is_wrapped():
    city = parse_query("深圳天气").city

    def fake_get(**kwargs):
        raise TimeoutError("network is slow")

    client = OpenWeatherClient("test-key", request_get=fake_get)

    with pytest.raises(WeatherUpstreamError):
        client.get_current(city)
