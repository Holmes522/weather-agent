from parser import parse_query
from weather_client import VisualCrossingClient, WeatherApiClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_weatherapi_current_weather_is_normalized():
    city = parse_query("北京今天天气").city
    calls = []
    response = FakeResponse(
        {
            "current": {
                "temp_c": 24.5,
                "humidity": 60,
                "wind_kph": 18.0,
                "precip_mm": 0.0,
                "condition": {"text": "多云", "code": 1003},
            }
        }
    )

    def fake_get(**kwargs):
        calls.append(kwargs)
        return response

    result = WeatherApiClient("weatherapi-key", request_get=fake_get).get_current(city)

    assert result.temperature_c == 24.5
    assert result.condition == "多云"
    assert result.humidity_percent == 60
    assert result.wind_speed_mps == 5.0
    assert result.rain_expected is False
    assert calls[0]["url"] == "https://api.weatherapi.com/v1/current.json"
    assert calls[0]["params"]["q"] == f"{city.latitude},{city.longitude}"
    assert calls[0]["params"]["lang"] == "zh"


def test_weatherapi_forecast_uses_requested_day():
    city = parse_query("上海明天会下雨吗").city
    response = FakeResponse(
        {
            "forecast": {
                "forecastday": [
                    {"day": {}},
                    {
                        "day": {
                            "avgtemp_c": 20.2,
                            "avghumidity": 82,
                            "maxwind_kph": 14.4,
                            "totalprecip_mm": 5.1,
                            "daily_will_it_rain": 1,
                            "daily_chance_of_rain": 78,
                            "condition": {"text": "中雨", "code": 1189},
                        }
                    },
                    {"day": {}},
                ]
            }
        }
    )
    client = WeatherApiClient(
        "weatherapi-key", request_get=lambda **kwargs: response
    )

    result = client.get_forecast(city, day_offset=1)

    assert result.temperature_c == 20.2
    assert result.condition == "中雨"
    assert result.humidity_percent == 82
    assert result.wind_speed_mps == 4.0
    assert result.rain_expected is True


def test_visual_crossing_current_weather_is_normalized():
    city = parse_query("广州今天天气").city
    calls = []
    response = FakeResponse(
        {
            "currentConditions": {
                "temp": 28.1,
                "humidity": 72,
                "windspeed": 10.8,
                "precip": 0.4,
                "preciptype": ["rain"],
                "conditions": "Rain, Partially cloudy",
                "icon": "rain",
            }
        }
    )

    def fake_get(**kwargs):
        calls.append(kwargs)
        return response

    result = VisualCrossingClient(
        "visual-crossing-key", request_get=fake_get
    ).get_current(city)

    assert result.temperature_c == 28.1
    assert result.condition == "雨"
    assert result.humidity_percent == 72
    assert result.wind_speed_mps == 3.0
    assert result.rain_expected is True
    assert calls[0]["url"].startswith(
        "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/"
    )
    assert calls[0]["params"]["unitGroup"] == "metric"
    assert calls[0]["params"]["include"] == "current"


def test_visual_crossing_forecast_uses_requested_day():
    city = parse_query("深圳后天天气").city
    response = FakeResponse(
        {
            "days": [
                {},
                {},
                {
                    "temp": 25.3,
                    "humidity": 66,
                    "windspeed": 7.2,
                    "precip": 0.0,
                    "precipprob": 8,
                    "preciptype": None,
                    "conditions": "Partially cloudy",
                    "icon": "partly-cloudy-day",
                },
            ]
        }
    )
    client = VisualCrossingClient(
        "visual-crossing-key", request_get=lambda **kwargs: response
    )

    result = client.get_forecast(city, day_offset=2)

    assert result.temperature_c == 25.3
    assert result.condition == "多云"
    assert result.humidity_percent == 66
    assert result.wind_speed_mps == 2.0
    assert result.rain_expected is False
