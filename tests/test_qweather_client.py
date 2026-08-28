import pytest

from parser import parse_query
from weather_client import QWeatherClient, WeatherDataError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_qweather_current_uses_v1_endpoint_and_header_authentication():
    city = parse_query("北京今天天气").city
    response = FakeResponse(
        {
            "condition": {"text": "少云", "code": "102"},
            "temperature": {"value": 31.71, "unit": "°C"},
            "humidity": 0.69,
            "wind": {"speed": {"value": 4.74, "unit": "m/s"}},
            "precipitation": {"type": "none"},
        }
    )
    calls = []

    def fake_get(url, params, headers, timeout):
        calls.append((url, params, headers, timeout))
        return response

    client = QWeatherClient(
        api_key="qweather-test-key",
        api_host="abc123.def.qweatherapi.com",
        request_get=fake_get,
    )
    result = client.get_current(city)

    assert result.temperature_c == 31.7
    assert result.condition == "多云"
    assert result.humidity_percent == 69
    assert result.wind_speed_mps == 4.7
    assert result.rain_expected is False
    assert calls[0][0].endswith("/weather/v1/current/39.9042/116.4074")
    assert calls[0][1] == {"localTime": "true", "lang": "zh"}
    assert calls[0][2] == {"X-QW-Api-Key": "qweather-test-key"}


def test_qweather_daily_forecast_normalizes_tomorrow_and_rain():
    city = parse_query("上海明天会下雨吗？").city
    response = FakeResponse(
        {
            "days": [
                {
                    "temperatureAvg": {"value": 27.0, "unit": "°C"},
                    "daytime": {
                        "condition": {"text": "晴", "code": "100"},
                        "humidity": 0.50,
                        "wind": {"speed": {"value": 2.0, "unit": "m/s"}},
                        "precipitation": {"type": "none"},
                    },
                    "nighttime": {
                        "condition": {"text": "晴", "code": "100"},
                        "humidity": 0.60,
                        "wind": {"speed": {"value": 1.0, "unit": "m/s"}},
                        "precipitation": {"type": "none"},
                    },
                },
                {
                    "temperatureAvg": {"value": 25.5, "unit": "°C"},
                    "daytime": {
                        "condition": {"text": "小雨", "code": "305"},
                        "humidity": 0.80,
                        "wind": {"speed": {"value": 3.0, "unit": "m/s"}},
                        "precipitation": {"type": "rain"},
                    },
                    "nighttime": {
                        "condition": {"text": "阴", "code": "104"},
                        "humidity": 0.70,
                        "wind": {"speed": {"value": 2.0, "unit": "m/s"}},
                        "precipitation": {"type": "none"},
                    },
                },
            ]
        }
    )
    calls = []

    def fake_get(**kwargs):
        calls.append(kwargs)
        return response

    client = QWeatherClient(
        api_key="qweather-test-key",
        api_host="abc123.def.qweatherapi.com",
        request_get=fake_get,
    )
    result = client.get_forecast(city, day_offset=1)

    assert result.temperature_c == 25.5
    assert result.condition == "雨"
    assert result.humidity_percent == 75
    assert result.wind_speed_mps == 2.5
    assert result.rain_expected is True
    assert calls[0]["params"]["days"] == 3


def test_qweather_rejects_untrusted_api_host():
    with pytest.raises(ValueError):
        QWeatherClient("test-key", "https://example.com/internal")


def test_qweather_missing_forecast_day_raises_data_error():
    city = parse_query("广州后天天气").city
    response = FakeResponse({"days": []})
    client = QWeatherClient(
        "test-key",
        "abc123.def.qweatherapi.com",
        request_get=lambda **kwargs: response,
    )

    with pytest.raises(WeatherDataError):
        client.get_forecast(city, day_offset=2)
