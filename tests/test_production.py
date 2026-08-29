from app import create_app
from config import Settings
from weather_client import WeatherData


class FakeWeatherClient:
    def get_current(self, city):
        return WeatherData(22.0, "晴", 50, 2.0, False)

    def get_forecast(self, city, day_offset):
        return WeatherData(20.0, "阴", 60, 3.0, False)


def create_production_app(rate_limit=30):
    return create_app(
        settings=Settings(
            default_provider="openmeteo",
            environment="production",
            chat_rate_limit_per_minute=rate_limit,
        ),
        weather_clients={"openmeteo": FakeWeatherClient()},
        default_provider="openmeteo",
    )


def test_health_endpoint_reports_ready_without_calling_weather_provider():
    response = create_production_app().test_client().get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
    assert response.headers["Cache-Control"] == "no-store"


def test_production_anonymous_history_cookie_requires_https():
    response = create_production_app().test_client().get("/api/conversations")

    assert "Secure" in response.headers["Set-Cookie"]


def test_production_hides_runtime_provider_configuration():
    http = create_production_app().test_client()

    assert http.get("/settings").status_code == 404
    assert http.get("/api/providers").status_code == 404
    assert http.get("/api/llm").status_code == 404
    assert http.post(
        "/api/providers",
        json={"provider": "openweather", "api_key": "not-a-real-key"},
    ).status_code == 404
    assert http.post(
        "/api/llm",
        json={
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "api_key": "not-a-real-key",
        },
    ).status_code == 404
    assert 'href="/settings"' not in http.get("/").get_data(as_text=True)


def test_production_limits_chat_requests_per_client_ip():
    http = create_production_app(rate_limit=1).test_client()
    payload = {"message": "北京今天天气怎么样？", "session_id": "rate-session"}

    first = http.post("/chat", json=payload)
    limited = http.post("/chat", json=payload)

    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.get_json() == {
        "error": {"code": "RATE_LIMITED", "message": "请求过于频繁，请稍后重试。"}
    }
    assert limited.headers["Retry-After"] == "60"


def test_production_uses_forwarded_client_ip_for_rate_limiting():
    http = create_production_app(rate_limit=1).test_client()
    payload = {"message": "北京天气", "session_id": "forwarded-session"}

    first = http.post(
        "/chat", json=payload, headers={"X-Forwarded-For": "198.51.100.10"}
    )
    other_client = http.post(
        "/chat", json=payload, headers={"X-Forwarded-For": "198.51.100.11"}
    )

    assert first.status_code == 200
    assert other_client.status_code == 200
