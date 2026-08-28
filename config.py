"""应用配置，敏感值只从环境变量读取。"""

from dataclasses import dataclass
import os


class ConfigurationError(Exception):
    """必需配置缺失或无效。"""


@dataclass(frozen=True)
class Settings:
    api_key: str
    request_timeout_seconds: tuple = (3.05, 10.0)

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.getenv("OPENWEATHER_API_KEY", "").strip()
        if not api_key:
            raise ConfigurationError(
                "OPENWEATHER_API_KEY environment variable is not configured"
            )
        return cls(api_key=api_key)
