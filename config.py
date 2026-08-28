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

    @classmethod
    def from_env(cls) -> "Settings":
        default_provider = os.getenv("WEATHER_PROVIDER", "openweather").strip().lower()
        if default_provider not in {"openweather", "qweather"}:
            raise ConfigurationError(
                "WEATHER_PROVIDER must be openweather or qweather"
            )

        openweather_api_key = os.getenv("OPENWEATHER_API_KEY", "").strip() or None
        qweather_api_key = os.getenv("QWEATHER_API_KEY", "").strip() or None
        qweather_api_host = os.getenv("QWEATHER_API_HOST", "").strip() or None

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

        return cls(
            api_key=openweather_api_key,
            default_provider=default_provider,
            qweather_api_key=qweather_api_key,
            qweather_api_host=qweather_api_host,
        )
