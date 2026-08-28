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


@pytest.mark.parametrize("value", ["0", "301", "not-a-number"])
def test_invalid_chat_rate_limit_is_rejected(monkeypatch, value):
    monkeypatch.setenv("WEATHER_PROVIDER", "openmeteo")
    monkeypatch.setenv("CHAT_RATE_LIMIT_PER_MINUTE", value)

    with pytest.raises(ConfigurationError):
        Settings.from_env()
