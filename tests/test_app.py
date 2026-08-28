import pytest

from app import create_app
from config import Settings
from geocoding import CityResolution
from parser import City
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


class FakeCityResolver:
    def __init__(self, resolutions=None):
        self.resolutions = resolutions or {}
        self.calls = []

    def resolve(self, term):
        self.calls.append(term)
        return self.resolutions.get(term)


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


def test_chat_returns_all_requested_cities_in_text_order(settings):
    client = FakeWeatherClient()
    app = create_app(settings=settings, weather_client=client)

    response = app.test_client().post(
        "/chat",
        json={"message": "深圳和广州明天天气什么样", "session_id": "multi-city"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["cities"] == ["深圳", "广州"]
    assert [result["city"] for result in body["results"]] == ["深圳", "广州"]
    assert body["display_mode"] == "weather_cards"
    assert client.calls == [
        ("forecast", "深圳", 1),
        ("forecast", "广州", 1),
    ]


def test_chat_only_answers_the_requested_humidity(settings):
    client = FakeWeatherClient(forecast=WeatherData(25.0, "阴", 73, 2.0, False))
    app = create_app(settings=settings, weather_client=client)

    response = app.test_client().post(
        "/chat",
        json={"message": "深圳明天湿度如何", "session_id": "humidity-only"},
    )

    body = response.get_json()
    assert response.status_code == 200
    assert body["intent"] == "humidity"
    assert body["display_mode"] == "text"
    assert body["answer"] == "深圳明天湿度约 73%。"
    assert "气温" not in body["answer"]
    assert "风速" not in body["answer"]


def test_chat_gives_outing_advice_then_accepts_full_weather_confirmation(settings):
    client = FakeWeatherClient()
    app = create_app(settings=settings, weather_client=client)
    http = app.test_client()

    advice = http.post(
        "/chat",
        json={"message": "深圳明天出门要带什么", "session_id": "outing-chat"},
    )
    details = http.post(
        "/chat",
        json={"message": "需要", "session_id": "outing-chat"},
    )

    assert advice.status_code == 200
    assert advice.get_json()["intent"] == "outing"
    assert advice.get_json()["display_mode"] == "text"
    assert "带伞" in advice.get_json()["answer"]
    assert "完整天气" in advice.get_json()["answer"]
    assert details.status_code == 200
    assert details.get_json()["intent"] == "full"
    assert details.get_json()["city"] == "深圳"
    assert details.get_json()["date"] == "明天"
    assert details.get_json()["display_mode"] == "weather_cards"


def test_chat_resolves_city_outside_static_list(settings):
    resolver = FakeCityResolver(
        {"纽约": CityResolution(City("纽约", 40.7127, -74.0060, "US"))}
    )
    client = FakeWeatherClient()
    app = create_app(
        settings=settings,
        weather_client=client,
        city_resolver=resolver,
    )

    response = app.test_client().post(
        "/chat", json={"message": "纽约明天天气", "session_id": "global-city"}
    )

    assert response.status_code == 200
    assert response.get_json()["city"] == "纽约"
    assert resolver.calls == ["纽约"]
    assert client.calls == [("forecast", "纽约", 1)]


def test_explicit_unknown_city_never_falls_back_to_previous_city(settings):
    resolver = FakeCityResolver({"不存在城": None})
    app = create_app(
        settings=settings,
        weather_client=FakeWeatherClient(),
        city_resolver=resolver,
    )
    http = app.test_client()
    assert http.post(
        "/chat", json={"message": "深圳天气", "session_id": "no-stale-city"}
    ).status_code == 200

    response = http.post(
        "/chat",
        json={"message": "不存在城明天天气", "session_id": "no-stale-city"},
    )

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "CITY_NOT_FOUND"


def test_chat_explains_city_name_correction(settings):
    resolver = FakeCityResolver(
        {"大利": CityResolution(City("大理", 25.59, 100.24), "大利")}
    )
    app = create_app(
        settings=settings,
        weather_client=FakeWeatherClient(),
        city_resolver=resolver,
    )

    response = app.test_client().post(
        "/chat", json={"message": "大利天气如何", "session_id": "correction"}
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["city"] == "大理"
    assert body["results"][0]["corrected_from"] == "大利"
    assert "可能是“大理”" in body["answer"]


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


def test_chat_selects_qweather_provider_per_request(settings):
    openweather = FakeWeatherClient(current=WeatherData(22.0, "晴", 40, 2.0, False))
    qweather = FakeWeatherClient(current=WeatherData(18.0, "阴", 70, 1.0, False))
    app = create_app(
        settings=settings,
        weather_clients={"openweather": openweather, "qweather": qweather},
        default_provider="openweather",
    )

    response = app.test_client().post(
        "/chat",
        json={
            "message": "北京今天天气怎么样？",
            "session_id": "provider-session",
            "provider": "qweather",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["provider"] == "qweather"
    assert response.get_json()["weather"]["temperature_c"] == 18.0
    assert qweather.calls == [("current", "北京", 0)]
    assert openweather.calls == []


def test_chat_rejects_unknown_provider(settings):
    app = create_app(
        settings=settings,
        weather_clients={"openweather": FakeWeatherClient()},
        default_provider="openweather",
    )

    response = app.test_client().post(
        "/chat", json={"message": "北京天气", "provider": "unknown"}
    )

    assert response.status_code == 422
    assert response.get_json()["error"] == {
        "code": "INVALID_PROVIDER",
        "message": "不支持该天气服务，可选值：openweather。",
    }


def test_home_renders_weather_chat_platform(settings):
    app = create_app(
        settings=settings,
        weather_clients={
            "openweather": FakeWeatherClient(),
            "qweather": FakeWeatherClient(),
        },
        default_provider="qweather",
    )

    response = app.test_client().get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="chat-form"' in html
    assert 'id="message-input"' in html
    assert 'id="provider-select"' in html
    assert '<option value="qweather" selected>' in html
    assert '<option value="openweather"' in html
    assert '/static/styles.css' in html
    assert '/static/app.js' in html
    assert "OpenStreetMap contributors" in html


def test_home_offers_openmeteo_without_additional_credentials(settings):
    app = create_app(settings=settings)

    response = app.test_client().get("/")

    assert response.status_code == 200
    assert '<option value="openmeteo">Open-Meteo</option>' in response.get_data(
        as_text=True
    )


@pytest.mark.parametrize("path", ["/", "/chat"])
def test_responses_include_browser_security_headers(settings, path):
    app = create_app(settings=settings, weather_client=FakeWeatherClient())
    http = app.test_client()

    if path == "/chat":
        response = http.post(
            path,
            json={"message": "北京天气", "session_id": "security-session"},
        )
    else:
        response = http.get(path)

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
