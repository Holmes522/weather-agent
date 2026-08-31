import pytest

from config import ConfigurationError, Settings


def test_qweather_can_be_the_only_configured_provider(monkeypatch):
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    monkeypatch.setenv("WEATHER_PROVIDER", "qweather")
    monkeypatch.setenv("QWEATHER_API_KEY", "qweather-key")
    monkeypatch.setenv("QWEATHER_API_HOST", "abc123.def.qweatherapi.com")

    settings = Settings.from_env()

    assert settings.default_provider == "qweather"
    assert settings.qweather_api_key == "qweather-key"
    assert settings.qweather_api_host == "abc123.def.qweatherapi.com"


def test_unknown_default_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("WEATHER_PROVIDER", "unknown")

    with pytest.raises(ConfigurationError):
        Settings.from_env()


def test_openmeteo_can_be_default_without_api_key(monkeypatch):
    monkeypatch.setenv("WEATHER_PROVIDER", "openmeteo")
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    monkeypatch.delenv("QWEATHER_API_KEY", raising=False)
    monkeypatch.delenv("QWEATHER_API_HOST", raising=False)

    settings = Settings.from_env()

    assert settings.default_provider == "openmeteo"
    assert settings.api_key is None
    assert settings.qweather_api_key is None


@pytest.mark.parametrize(
    ("provider", "environment_name", "settings_field"),
    [
        ("weatherapi", "WEATHERAPI_API_KEY", "weatherapi_api_key"),
        (
            "visualcrossing",
            "VISUAL_CROSSING_API_KEY",
            "visual_crossing_api_key",
        ),
    ],
)
def test_common_provider_can_be_selected_from_environment(
    monkeypatch, provider, environment_name, settings_field
):
    monkeypatch.setenv("WEATHER_PROVIDER", provider)
    monkeypatch.setenv(environment_name, "provider-key")

    settings = Settings.from_env()

    assert settings.default_provider == provider
    assert getattr(settings, settings_field) == "provider-key"


def test_production_settings_are_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("WEATHER_PROVIDER", "openmeteo")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CHAT_RATE_LIMIT_PER_MINUTE", "45")

    settings = Settings.from_env()

    assert settings.environment == "production"
    assert settings.is_production is True
    assert settings.chat_rate_limit_per_minute == 45


def test_langgraph_is_the_default_agent_engine(monkeypatch):
    monkeypatch.setenv("WEATHER_PROVIDER", "openmeteo")
    monkeypatch.delenv("AGENT_ENGINE", raising=False)

    assert Settings.from_env().agent_engine == "langgraph"


def test_legacy_langchain_agent_engine_is_normalized(monkeypatch):
    monkeypatch.setenv("WEATHER_PROVIDER", "openmeteo")
    monkeypatch.setenv("AGENT_ENGINE", "langchain")

    assert Settings.from_env().agent_engine == "langgraph"


def test_native_agent_engine_can_be_selected(monkeypatch):
    monkeypatch.setenv("WEATHER_PROVIDER", "openmeteo")
    monkeypatch.setenv("AGENT_ENGINE", "native")

    assert Settings.from_env().agent_engine == "native"


def test_unknown_agent_engine_is_rejected(monkeypatch):
    monkeypatch.setenv("WEATHER_PROVIDER", "openmeteo")
    monkeypatch.setenv("AGENT_ENGINE", "automatic")

    with pytest.raises(ConfigurationError):
        Settings.from_env()


def test_geocoding_service_can_be_replaced_with_environment(monkeypatch):
    monkeypatch.setenv("WEATHER_PROVIDER", "openmeteo")
    monkeypatch.setenv("GEOCODING_API_URL", "https://geo.example.com/search")
    monkeypatch.setenv("GEOCODING_USER_AGENT", "weather-agent-test/1.0")

    settings = Settings.from_env()

    assert settings.geocoding_api_url == "https://geo.example.com/search"
    assert settings.geocoding_user_agent == "weather-agent-test/1.0"


@pytest.mark.parametrize(
    "url",
    [
        "http://unsafe.example.com/search",
        "https://",
        "https://user:password@geo.example.com/search",
    ],
)
def test_geocoding_service_requires_safe_https_url(monkeypatch, url):
    monkeypatch.setenv("WEATHER_PROVIDER", "openmeteo")
    monkeypatch.setenv("GEOCODING_API_URL", url)

    with pytest.raises(ConfigurationError):
        Settings.from_env()


@pytest.mark.parametrize("value", ["0", "301", "not-a-number"])
def test_invalid_chat_rate_limit_is_rejected(monkeypatch, value):
    monkeypatch.setenv("WEATHER_PROVIDER", "openmeteo")
    monkeypatch.setenv("CHAT_RATE_LIMIT_PER_MINUTE", value)

    with pytest.raises(ConfigurationError):
        Settings.from_env()
