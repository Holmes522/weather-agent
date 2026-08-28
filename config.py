"""应用配置，敏感值只从环境变量读取。"""

from dataclasses import dataclass
import os
from typing import Optional


class ConfigurationError(Exception):
    """必需配置缺失或无效。"""


@dataclass(frozen=True)
class Settings:
    api_key: Optional[str] = None
    request_timeout_seconds: tuple = (3.05, 10.0)
    default_provider: str = "openweather"
    qweather_api_key: Optional[str] = None
    qweather_api_host: Optional[str] = None
    weatherapi_api_key: Optional[str] = None
    visual_crossing_api_key: Optional[str] = None
    environment: str = "development"
    chat_rate_limit_per_minute: int = 30
    geocoding_api_url: str = "https://nominatim.openstreetmap.org/search"
    geocoding_user_agent: str = (
        "weather-agent/1.0 (https://github.com/Holmes522/weather-agent)"
    )

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @classmethod
    def from_env(cls) -> "Settings":
        default_provider = os.getenv("WEATHER_PROVIDER", "openmeteo").strip().lower()
        if default_provider not in {
            "openweather",
            "qweather",
            "openmeteo",
            "weatherapi",
            "visualcrossing",
        }:
            raise ConfigurationError(
                "WEATHER_PROVIDER is not a supported provider"
            )

        openweather_api_key = os.getenv("OPENWEATHER_API_KEY", "").strip() or None
        qweather_api_key = os.getenv("QWEATHER_API_KEY", "").strip() or None
        qweather_api_host = os.getenv("QWEATHER_API_HOST", "").strip() or None
        weatherapi_api_key = os.getenv("WEATHERAPI_API_KEY", "").strip() or None
        visual_crossing_api_key = (
            os.getenv("VISUAL_CROSSING_API_KEY", "").strip() or None
        )
        environment = os.getenv("APP_ENV", "development").strip().lower()
        if environment not in {"development", "production"}:
            raise ConfigurationError("APP_ENV must be development or production")
        geocoding_api_url = os.getenv(
            "GEOCODING_API_URL", cls.geocoding_api_url
        ).strip()
        geocoding_user_agent = os.getenv(
            "GEOCODING_USER_AGENT", cls.geocoding_user_agent
        ).strip()
        if not geocoding_api_url.startswith("https://") or not geocoding_user_agent:
            raise ConfigurationError("GEOCODING_API_URL and GEOCODING_USER_AGENT are invalid")

        try:
            chat_rate_limit = int(
                os.getenv("CHAT_RATE_LIMIT_PER_MINUTE", "30").strip()
            )
        except ValueError as error:
            raise ConfigurationError(
                "CHAT_RATE_LIMIT_PER_MINUTE must be an integer"
            ) from error
        if not 1 <= chat_rate_limit <= 300:
            raise ConfigurationError(
                "CHAT_RATE_LIMIT_PER_MINUTE must be between 1 and 300"
            )

        if default_provider == "openweather" and not openweather_api_key:
            raise ConfigurationError(
                "OPENWEATHER_API_KEY environment variable is not configured"
            )
        if default_provider == "qweather" and (
            not qweather_api_key or not qweather_api_host
        ):
            raise ConfigurationError(
                "QWEATHER_API_KEY and QWEATHER_API_HOST must both be configured"
            )
        if default_provider == "weatherapi" and not weatherapi_api_key:
            raise ConfigurationError(
                "WEATHERAPI_API_KEY environment variable is not configured"
            )
        if default_provider == "visualcrossing" and not visual_crossing_api_key:
            raise ConfigurationError(
                "VISUAL_CROSSING_API_KEY environment variable is not configured"
            )

        return cls(
            api_key=openweather_api_key,
            default_provider=default_provider,
            qweather_api_key=qweather_api_key,
            qweather_api_host=qweather_api_host,
            weatherapi_api_key=weatherapi_api_key,
            visual_crossing_api_key=visual_crossing_api_key,
            environment=environment,
            chat_rate_limit_per_minute=chat_rate_limit,
            geocoding_api_url=geocoding_api_url,
            geocoding_user_agent=geocoding_user_agent,
        )
