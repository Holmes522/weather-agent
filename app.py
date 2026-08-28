"""天气查询 Agent 的 Flask REST API。"""

import re
from typing import Dict, Optional
from uuid import uuid4

from flask import Flask, jsonify, render_template, request

from config import ConfigurationError, Settings
from parser import parse_query
from session_store import InMemorySessionStore
from weather_client import (
    OpenWeatherClient,
    QWeatherClient,
    WeatherClientError,
    WeatherData,
    WeatherProvider,
)


MAX_MESSAGE_LENGTH = 200
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def create_app(
    settings: Optional[Settings] = None,
    weather_client: Optional[WeatherProvider] = None,
    session_store: Optional[InMemorySessionStore] = None,
    weather_clients: Optional[Dict[str, WeatherProvider]] = None,
    default_provider: Optional[str] = None,
) -> Flask:
    """创建 Flask 应用；依赖可注入，便于脱离真实网络测试。"""

    if weather_client is not None and weather_clients is not None:
        raise ValueError("weather_client and weather_clients cannot both be provided")

    if weather_clients is not None:
        clients = dict(weather_clients)
        effective_default_provider = default_provider or "openweather"
    elif weather_client is not None:
        clients = {"openweather": weather_client}
        effective_default_provider = default_provider or "openweather"
    else:
        effective_settings = settings or Settings.from_env()
        clients = _build_weather_clients(effective_settings)
        effective_default_provider = (
            default_provider or effective_settings.default_provider
        )

    if effective_default_provider not in clients:
        raise ConfigurationError(
            f"Default weather provider is not configured: {effective_default_provider}"
        )
    store = session_store or InMemorySessionStore()

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

    @app.after_request
    def add_security_headers(response):
        """为网页和 JSON API 添加适合当前同源应用的基础安全响应头。"""

        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        return response

    @app.get("/")
    def index():
        """渲染不暴露天气服务密钥的同源聊天界面。"""

        provider_labels = {
            "qweather": "和风天气",
            "openweather": "OpenWeather",
        }
        ordered_providers = sorted(
            clients,
            key=lambda provider_name: provider_name != effective_default_provider,
        )
        return render_template(
            "index.html",
            providers=[
                {
                    "value": provider_name,
                    "label": provider_labels.get(provider_name, provider_name),
                }
                for provider_name in ordered_providers
            ],
            default_provider=effective_default_provider,
        )

    @app.errorhandler(413)
    def payload_too_large(_error):
        return _error_response(
            "PAYLOAD_TOO_LARGE", "请求体过大。", status_code=413
        )

    @app.post("/chat")
    def chat():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _error_response("INVALID_JSON", "请求必须是 JSON 对象。", 400)

        message = body.get("message")
        if not isinstance(message, str) or not message.strip():
            return _error_response(
                "INVALID_MESSAGE", "请提供要查询的天气问题。", 422
            )
        message = message.strip()
        if len(message) > MAX_MESSAGE_LENGTH:
            return _error_response("MESSAGE_TOO_LONG", "问题长度不能超过 200 个字符。", 422)

        provider = body.get("provider", effective_default_provider)
        if not isinstance(provider, str) or provider not in clients:
            available = "、".join(sorted(clients))
            return _error_response(
                "INVALID_PROVIDER", f"不支持该天气服务，可选值：{available}。", 422
            )
        selected_client = clients[provider]

        session_id = body.get("session_id")
        if session_id is None:
            session_id = uuid4().hex
        elif not isinstance(session_id, str) or not SESSION_ID_PATTERN.fullmatch(session_id):
            return _error_response(
                "INVALID_SESSION", "session_id 只能包含字母、数字和 . _ : -。", 422
            )

        parsed = parse_query(message)
        city = parsed.city or store.get_city(session_id)
        if city is None:
            return _error_response("CITY_NOT_FOUND", "请提供要查询的城市。", 422)

        try:
            if parsed.day_offset == 0:
                weather = selected_client.get_current(city)
            else:
                weather = selected_client.get_forecast(city, parsed.day_offset)
        except WeatherClientError:
            return _error_response(
                "WEATHER_UNAVAILABLE", "天气服务暂时不可用，请稍后重试。", 502
            )

        # 只在查询成功后保存城市，避免上游失败污染会话上下文。
        store.set_city(session_id, city)
        advice = _build_advice(parsed.day_offset, weather)
        return jsonify(
            {
                "session_id": session_id,
                "city": city.name,
                "date": parsed.date_label,
                "provider": provider,
                "answer": _build_answer(city.name, parsed.date_label, weather, advice),
                "weather": {
                    "temperature_c": weather.temperature_c,
                    "condition": weather.condition,
                    "humidity_percent": weather.humidity_percent,
                    "wind_speed_mps": weather.wind_speed_mps,
                    "rain_expected": weather.rain_expected,
                    "advice": advice,
                },
            }
        )

    return app


def _build_weather_clients(settings: Settings) -> Dict[str, WeatherProvider]:
    clients: Dict[str, WeatherProvider] = {}
    if settings.api_key:
        clients["openweather"] = OpenWeatherClient(
            settings.api_key,
            timeout=settings.request_timeout_seconds,
        )
    if settings.qweather_api_key and settings.qweather_api_host:
        clients["qweather"] = QWeatherClient(
            settings.qweather_api_key,
            settings.qweather_api_host,
            timeout=settings.request_timeout_seconds,
        )
    return clients


def _error_response(code: str, message: str, status_code: int):
    return jsonify({"error": {"code": code, "message": message}}), status_code


def _build_advice(day_offset: int, weather: WeatherData) -> Optional[str]:
    if day_offset != 1:
        return None
    if weather.rain_expected:
        return "明天可能有雨，建议携带雨具。"
    return "明天暂无明显降雨信号，出行可暂不携带雨具。"


def _build_answer(city: str, date_label: str, weather: WeatherData, advice: Optional[str]) -> str:
    answer = (
        f"{city}{date_label}：{weather.condition}，气温约 {weather.temperature_c:.1f}℃，"
        f"湿度 {weather.humidity_percent}%，风速 {weather.wind_speed_mps:.1f} m/s。"
    )
    return f"{answer}{advice or ''}"


if __name__ == "__main__":
    # 先设置 WEATHER_PROVIDER 及对应凭据，再执行 python app.py。
    create_app().run(host="127.0.0.1", port=5000, debug=False)
