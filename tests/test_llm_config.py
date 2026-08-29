import pytest

from app import create_app
from config import ConfigurationError, Settings
from weather_client import WeatherData


class FakeWeatherClient:
    def get_current(self, city):
        return WeatherData(22.0, "晴", 50, 2.0, False)

    def get_forecast(self, city, day_offset):
        return WeatherData(20.0, "阴", 60, 3.0, False)


def local_app(settings=None):
    return create_app(
        settings=settings or Settings(default_provider="openmeteo"),
        weather_clients={"openmeteo": FakeWeatherClient()},
        default_provider="openmeteo",
    )


def test_llm_environment_configuration_is_loaded(monkeypatch):
    monkeypatch.setenv("WEATHER_PROVIDER", "openmeteo")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "environment-model-secret")
    monkeypatch.setenv("LLM_MODEL", "example-chat")
    monkeypatch.setenv("LLM_DISPLAY_NAME", "示例模型")

    settings = Settings.from_env()

    assert settings.llm_base_url == "https://api.example.com/v1"
    assert settings.llm_api_key == "environment-model-secret"
    assert settings.llm_model == "example-chat"
    assert settings.llm_display_name == "示例模型"


def test_incomplete_llm_environment_configuration_is_rejected(monkeypatch):
    monkeypatch.setenv("WEATHER_PROVIDER", "openmeteo")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1")

    with pytest.raises(ConfigurationError):
        Settings.from_env()


def test_runtime_llm_status_does_not_expose_api_key():
    app = local_app()
    http = app.test_client()

    response = http.post(
        "/api/llm",
        json={
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "api_key": "runtime-model-secret",
        },
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["llm"]["configured"] is True
    assert body["llm"]["provider"] == "OpenAI"
    assert body["llm"]["model"] == "gpt-4.1-mini"
    assert body["llm"]["id"]
    assert body["models"] == [{**body["llm"], "active": True}]
    status = http.get("/api/llm")
    assert status.get_json() == body
    assert "runtime-model-secret" not in status.get_data(as_text=True)


def test_runtime_ollama_configuration_does_not_require_api_key():
    response = local_app().test_client().post(
        "/api/llm",
        json={"provider": "ollama", "model": "qwen3:8b", "api_key": ""},
    )

    assert response.status_code == 201
    assert response.get_json()["llm"]["provider"] == "Ollama（本机）"


def test_runtime_llm_configuration_keeps_previous_models_and_can_switch():
    http = local_app().test_client()
    first = http.post(
        "/api/llm",
        json={"provider": "openai", "model": "gpt-test", "api_key": "secret-1"},
    ).get_json()["llm"]
    second_response = http.post(
        "/api/llm",
        json={"provider": "kimi", "model": "kimi-test", "api_key": "secret-2"},
    )

    assert second_response.status_code == 201
    second = second_response.get_json()
    assert [item["id"] for item in second["models"]] == [first["id"], second["llm"]["id"]]
    switched = http.patch("/api/llm/active", json={"id": first["id"]})
    assert switched.status_code == 200
    assert switched.get_json()["llm"]["id"] == first["id"]
    assert sum(item["active"] for item in switched.get_json()["models"]) == 1


@pytest.mark.parametrize(
    ("provider", "provider_name"),
    [
        ("glm", "智谱 GLM"),
        ("kimi", "Moonshot Kimi"),
        ("qwen", "通义千问"),
        ("doubao", "豆包（火山方舟）"),
        ("gemini", "Google Gemini"),
    ],
)
def test_common_llm_provider_presets_are_supported(provider, provider_name):
    response = local_app().test_client().post(
        "/api/llm",
        json={"provider": provider, "model": f"{provider}-test", "api_key": "secret"},
    )

    assert response.status_code == 201
    assert response.get_json()["llm"]["provider"] == provider_name


@pytest.mark.parametrize(
    "payload",
    [
        {"provider": "unknown", "model": "test", "api_key": "secret"},
        {"provider": "openai", "model": "", "api_key": "secret"},
        {"provider": "openai", "model": "test", "api_key": ""},
        {
            "provider": "custom",
            "base_url": "http://internal.example.com/v1",
            "model": "test",
            "api_key": "secret",
        },
        {
            "provider": "custom",
            "base_url": "https://user:pass@example.com/v1",
            "model": "test",
            "api_key": "secret",
        },
    ],
)
def test_invalid_runtime_llm_configuration_is_rejected(payload):
    response = local_app().test_client().post("/api/llm", json=payload)

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "INVALID_LLM_CONFIG"


def test_llm_configuration_is_blocked_for_non_local_clients():
    app = local_app()
    response = app.test_client().post(
        "/api/llm",
        json={
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "api_key": "runtime-model-secret",
        },
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )

    assert response.status_code == 403
    assert app.test_client().get("/api/llm").get_json()["llm"]["configured"] is False


def test_settings_page_renders_llm_configuration_form():
    html = local_app().test_client().get("/settings").get_data(as_text=True)

    assert 'id="llm-config-form"' in html
    assert 'id="llm-provider"' in html
    assert 'id="llm-model"' in html
    assert 'id="llm-api-key"' in html
    assert 'id="llm-base-url"' in html
    assert 'id="llm-profile-list"' in html
    assert "智谱 GLM" in html
    assert "Moonshot Kimi" in html
    assert "通义千问" in html
    assert "豆包（火山方舟）" in html
    assert "Google Gemini" in html


def test_home_renders_model_selector_and_non_secret_storage_contract():
    http = local_app().test_client()
    configured = http.post(
        "/api/llm",
        json={"provider": "openai", "model": "gpt-test", "api_key": "secret"},
    ).get_json()["llm"]

    html = http.get("/").get_data(as_text=True)
    script = http.get("/static/app.js").get_data(as_text=True)

    assert 'id="llm-select"' in html
    assert configured["id"] in html
    assert "weather-agent.weather-provider" in script
    assert "weather-agent.llm-profile" in script
    assert "api_key" not in script
