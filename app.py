"""天气查询 Agent 的 Flask REST API。"""

import re
from typing import Optional
from uuid import uuid4

from flask import Flask, jsonify, request

from config import ConfigurationError, Settings
from parser import parse_query
from session_store import InMemorySessionStore
from weather_client import OpenWeatherClient, WeatherClientError, WeatherData


MAX_MESSAGE_LENGTH = 200
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def create_app(
    settings: Optional[Settings] = None,
    weather_client: Optional[OpenWeatherClient] = None,
    session_store: Optional[InMemorySessionStore] = None,
) -> Flask:
    """创建 Flask 应用；依赖可注入，便于脱离真实网络测试。"""

    if weather_client is None:
        effective_settings = settings or Settings.from_env()
        weather_client = OpenWeatherClient(
            effective_settings.api_key,
            timeout=effective_settings.request_timeout_seconds,
        )
    store = session_store or InMemorySessionStore()

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

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
                weather = weather_client.get_current(city)
            else:
                weather = weather_client.get_forecast(city, parsed.day_offset)
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
    # 开发启动方式：先设置 OPENWEATHER_API_KEY，再执行 python app.py。
    create_app().run(host="127.0.0.1", port=5000, debug=False)
