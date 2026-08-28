import pytest

from app import create_app
from config import Settings
from weather_client import WeatherData, WeatherUpstreamError


class FakeWeatherClient:
    def __init__(self, current=None, forecast=None, error=None):
        self.current = current or WeatherData(22.4, "晴", 48, 3.2, False)
        self.forecast = forecast or WeatherData(25.0, "雨", 80, 2.0, True)
        self.error = error
        self.calls = []

    def get_current(self, city):
        self.calls.append(("current", city.name, 0))
        if self.error:
            raise self.error
        return self.current

    def get_forecast(self, city, day_offset):
        self.calls.append(("forecast", city.name, day_offset))
        if self.error:
            raise self.error
        return self.forecast


@pytest.fixture
def settings():
    return Settings(api_key="test-key")


def test_chat_returns_current_weather_for_city(settings):
    client = FakeWeatherClient()
    app = create_app(settings=settings, weather_client=client)
    response = app.test_client().post(
        "/chat",
        json={"message": "北京今天天气怎么样？", "session_id": "session-1"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["session_id"] == "session-1"
    assert body["city"] == "北京"
    assert body["date"] == "今天"
    assert body["weather"]["temperature_c"] == 22.4
    assert body["weather"]["condition"] == "晴"
    assert body["weather"]["advice"] is None
    assert client.calls == [("current", "北京", 0)]


def test_chat_remembers_city_for_follow_up_and_adds_rain_advice(settings):
    client = FakeWeatherClient()
    app = create_app(settings=settings, weather_client=client)
    http = app.test_client()

    tomorrow = http.post(
        "/chat",
        json={"message": "上海明天会下雨吗？", "session_id": "session-2"},
    )
    day_after = http.post(
        "/chat",
        json={"message": "那后天呢？", "session_id": "session-2"},
    )

    assert tomorrow.status_code == 200
    assert tomorrow.get_json()["weather"]["advice"] == "明天可能有雨，建议携带雨具。"
    assert day_after.status_code == 200
    assert day_after.get_json()["city"] == "上海"
    assert day_after.get_json()["date"] == "后天"
    assert client.calls == [
        ("forecast", "上海", 1),
        ("forecast", "上海", 2),
    ]


def test_chat_rejects_follow_up_without_previous_city(settings):
    app = create_app(settings=settings, weather_client=FakeWeatherClient())
    response = app.test_client().post(
        "/chat", json={"message": "那后天呢？", "session_id": "new-session"}
    )

    assert response.status_code == 422
    assert response.get_json() == {
        "error": {"code": "CITY_NOT_FOUND", "message": "请提供要查询的城市。"}
    }


def test_chat_rejects_invalid_input(settings):
    app = create_app(settings=settings, weather_client=FakeWeatherClient())

    response = app.test_client().post("/chat", json={"message": " "})

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "INVALID_MESSAGE"


def test_chat_hides_upstream_error_details(settings):
    client = FakeWeatherClient(error=WeatherUpstreamError("secret upstream detail"))
    app = create_app(settings=settings, weather_client=client)
    response = app.test_client().post(
        "/chat", json={"message": "北京天气", "session_id": "session-3"}
    )

    assert response.status_code == 502
    assert response.get_json() == {
        "error": {
            "code": "WEATHER_UNAVAILABLE",
            "message": "天气服务暂时不可用，请稍后重试。",
        }
    }
    assert "secret upstream detail" not in response.get_data(as_text=True)


def test_chat_rejects_oversized_message(settings):
    app = create_app(settings=settings, weather_client=FakeWeatherClient())
    response = app.test_client().post(
        "/chat", json={"message": "北京" + "天气" * 200}
    )

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "MESSAGE_TOO_LONG"
