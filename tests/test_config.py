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
