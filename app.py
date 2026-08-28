"""天气查询 Agent 的 Flask REST API。"""

import re
from threading import RLock
from typing import Dict, Optional
from uuid import uuid4

from flask import Flask, abort, jsonify, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

from config import ConfigurationError, Settings
from conversation import (
    BRIEF,
    FOLLOW_UP,
    FULL,
    OUTING,
    build_weather_answer,
    classify_intent,
)
from geocoding import (
    CityResolution,
    CityResolver,
    GeocodingError,
    NominatimCityResolver,
)
from parser import SUPPORTED_CITIES, parse_query
from rate_limiter import InMemoryRateLimiter
from session_store import ConversationContext, InMemorySessionStore
from weather_client import (
    OpenMeteoClient,
    OpenWeatherClient,
    QWeatherClient,
    VisualCrossingClient,
    WeatherApiClient,
    WeatherClientError,
    WeatherData,
    WeatherProvider,
)


MAX_MESSAGE_LENGTH = 200
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
LOCAL_ADDRESSES = {"127.0.0.1", "::1"}
PROVIDER_CATALOG = (
    {
        "id": "openmeteo",
        "name": "Open-Meteo",
        "required_fields": [],
        "configurable": False,
    },
    {
        "id": "openweather",
        "name": "OpenWeather",
        "required_fields": ["api_key"],
        "configurable": True,
    },
    {
        "id": "qweather",
        "name": "和风天气",
        "required_fields": ["api_key", "api_host"],
        "configurable": True,
    },
    {
        "id": "weatherapi",
        "name": "WeatherAPI.com",
        "required_fields": ["api_key"],
        "configurable": True,
    },
    {
        "id": "visualcrossing",
        "name": "Visual Crossing",
        "required_fields": ["api_key"],
        "configurable": True,
    },
)


def create_app(
    settings: Optional[Settings] = None,
    weather_client: Optional[WeatherProvider] = None,
    session_store: Optional[InMemorySessionStore] = None,
    weather_clients: Optional[Dict[str, WeatherProvider]] = None,
    default_provider: Optional[str] = None,
    city_resolver: Optional[CityResolver] = None,
) -> Flask:
    """创建 Flask 应用；依赖可注入，便于脱离真实网络测试。"""

    if weather_client is not None and weather_clients is not None:
        raise ValueError("weather_client and weather_clients cannot both be provided")

    if weather_clients is not None:
        effective_settings = settings or Settings()
        clients = dict(weather_clients)
        effective_default_provider = default_provider or "openweather"
    elif weather_client is not None:
        effective_settings = settings or Settings()
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
    resolver = city_resolver or NominatimCityResolver(
        base_url=effective_settings.geocoding_api_url,
        user_agent=effective_settings.geocoding_user_agent,
        timeout=effective_settings.request_timeout_seconds,
    )
    clients_lock = RLock()
    chat_rate_limiter = InMemoryRateLimiter(
        effective_settings.chat_rate_limit_per_minute
    )

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    if effective_settings.is_production:
        # Render 等托管平台位于一层反向代理之后；只在生产模式信任这一层。
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

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
        if effective_settings.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    @app.get("/health")
    def health():
        """供托管平台探测进程是否已能响应 HTTP 请求。"""

        response = jsonify({"status": "ok"})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        """渲染不暴露天气服务密钥的同源聊天界面。"""

        with clients_lock:
            ordered_providers = sorted(
                clients,
                key=lambda provider_name: provider_name
                != effective_default_provider,
            )
        return render_template(
            "index.html",
            providers=[
                {
                    "value": provider_name,
                    "label": _provider_name(provider_name),
                }
                for provider_name in ordered_providers
            ],
            default_provider=effective_default_provider,
            settings_enabled=not effective_settings.is_production,
        )

    @app.get("/settings")
    def provider_settings():
        if effective_settings.is_production:
            abort(404)
        local_error = _require_local_request()
        if local_error is not None:
            return local_error
        return render_template(
            "settings.html",
            providers=_provider_statuses(clients, clients_lock),
            configurable_providers=[
                provider for provider in PROVIDER_CATALOG if provider["configurable"]
            ],
        )

    @app.get("/api/providers")
    def provider_status():
        if effective_settings.is_production:
            abort(404)
        local_error = _require_local_request()
        if local_error is not None:
            return local_error
        return jsonify({"providers": _provider_statuses(clients, clients_lock)})

    @app.post("/api/providers")
    def configure_provider():
        if effective_settings.is_production:
            abort(404)
        local_error = _require_local_request()
        if local_error is not None:
            return local_error

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _error_response("INVALID_JSON", "请求必须是 JSON 对象。", 400)

        provider_name = body.get("provider")
        try:
            client = _build_runtime_provider(
                provider_name,
                body,
                timeout=effective_settings.request_timeout_seconds,
            )
        except (TypeError, ValueError):
            return _error_response(
                "INVALID_PROVIDER_CONFIG",
                "配置不完整或格式不正确，请检查后重试。",
                422,
            )

        with clients_lock:
            was_configured = provider_name in clients
            clients[provider_name] = client
        return (
            jsonify(
                {
                    "provider": {
                        "id": provider_name,
                        "name": _provider_name(provider_name),
                        "configured": True,
                    }
                }
            ),
            200 if was_configured else 201,
        )

    @app.errorhandler(413)
    def payload_too_large(_error):
        return _error_response(
            "PAYLOAD_TOO_LARGE", "请求体过大。", status_code=413
        )

    @app.post("/chat")
    def chat():
        if effective_settings.is_production:
            allowed, retry_after = chat_rate_limiter.check(
                request.remote_addr or "unknown"
            )
            if not allowed:
                response, status_code = _error_response(
                    "RATE_LIMITED", "请求过于频繁，请稍后重试。", 429
                )
                response.headers["Retry-After"] = str(retry_after)
                return response, status_code

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
        with clients_lock:
            available_providers = tuple(sorted(clients))
            selected_client = clients.get(provider) if isinstance(provider, str) else None
        if selected_client is None:
            available = "、".join(available_providers)
            return _error_response(
                "INVALID_PROVIDER", f"不支持该天气服务，可选值：{available}。", 422
            )

        session_id = body.get("session_id")
        if session_id is None:
            session_id = uuid4().hex
        elif not isinstance(session_id, str) or not SESSION_ID_PATTERN.fullmatch(session_id):
            return _error_response(
                "INVALID_SESSION", "session_id 只能包含字母、数字和 . _ : -。", 422
            )

        parsed = parse_query(message)
        previous_context = store.get_context(session_id)
        intent = classify_intent(
            message,
            has_full_weather_offer=bool(
                previous_context and previous_context.offered_full_weather
            ),
        )
        if intent == FOLLOW_UP:
            intent = previous_context.intent if previous_context else BRIEF

        resolutions = []
        if parsed.location_terms:
            try:
                for location_term in parsed.location_terms:
                    known_city = SUPPORTED_CITIES.get(location_term)
                    resolution = (
                        CityResolution(known_city)
                        if known_city is not None
                        else resolver.resolve(location_term)
                    )
                    if resolution is None:
                        return _error_response(
                            "CITY_NOT_FOUND",
                            f"没有找到“{location_term}”，请检查城市名称。",
                            422,
                        )
                    resolutions.append(resolution)
            except GeocodingError:
                return _error_response(
                    "LOCATION_UNAVAILABLE", "城市查询服务暂时不可用，请稍后重试。", 502
                )
        elif previous_context:
            resolutions = [CityResolution(city) for city in previous_context.cities]

        if not resolutions:
            return _error_response("CITY_NOT_FOUND", "请提供要查询的城市。", 422)

        if (
            previous_context
            and not parsed.date_is_explicit
            and not parsed.location_terms
        ):
            day_offset = previous_context.day_offset
            date_label = previous_context.date_label
        else:
            day_offset = parsed.day_offset
            date_label = parsed.date_label

        try:
            weather_results = []
            for resolution in resolutions:
                if day_offset == 0:
                    weather = selected_client.get_current(resolution.city)
                else:
                    weather = selected_client.get_forecast(
                        resolution.city, day_offset
                    )
                advice = _build_advice(day_offset, weather)
                weather_payload = _weather_payload(weather, advice)
                weather_results.append(
                    {
                        "city": resolution.city.name,
                        "date": date_label,
                        "corrected_from": resolution.corrected_from,
                        "answer": build_weather_answer(
                            resolution.city.name,
                            date_label,
                            weather,
                            intent,
                            corrected_from=resolution.corrected_from,
                        ),
                        "weather": weather_payload,
                    }
                )
        except WeatherClientError:
            return _error_response(
                "WEATHER_UNAVAILABLE", "天气服务暂时不可用，请稍后重试。", 502
            )

        # 只在全部城市查询成功后保存上下文，避免失败污染后续对话。
        store.set_context(
            session_id,
            ConversationContext(
                cities=tuple(resolution.city for resolution in resolutions),
                day_offset=day_offset,
                date_label=date_label,
                intent=intent,
                offered_full_weather=intent == OUTING,
            ),
        )
        first_result = weather_results[0]
        return jsonify(
            {
                "session_id": session_id,
                "city": first_result["city"],
                "cities": [result["city"] for result in weather_results],
                "date": date_label,
                "provider": provider,
                "intent": intent,
                "display_mode": "weather_cards" if intent == FULL else "text",
                "answer": "\n".join(result["answer"] for result in weather_results),
                "weather": first_result["weather"],
                "results": weather_results,
            }
        )

    return app


def _build_weather_clients(settings: Settings) -> Dict[str, WeatherProvider]:
    clients: Dict[str, WeatherProvider] = {
        "openmeteo": OpenMeteoClient(timeout=settings.request_timeout_seconds)
    }
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
    if settings.weatherapi_api_key:
        clients["weatherapi"] = WeatherApiClient(
            settings.weatherapi_api_key,
            timeout=settings.request_timeout_seconds,
        )
    if settings.visual_crossing_api_key:
        clients["visualcrossing"] = VisualCrossingClient(
            settings.visual_crossing_api_key,
            timeout=settings.request_timeout_seconds,
        )
    return clients


def _provider_name(provider_id: str) -> str:
    for provider in PROVIDER_CATALOG:
        if provider["id"] == provider_id:
            return provider["name"]
    return provider_id


def _provider_statuses(clients: Dict[str, WeatherProvider], lock: RLock):
    with lock:
        configured = set(clients)
    return [
        {
            "id": provider["id"],
            "name": provider["name"],
            "configured": provider["id"] in configured,
            "required_fields": provider["required_fields"],
        }
        for provider in PROVIDER_CATALOG
    ]


def _require_local_request():
    if request.remote_addr not in LOCAL_ADDRESSES:
        return _error_response(
            "LOCAL_ACCESS_REQUIRED", "API 配置仅允许在本机访问。", 403
        )
    return None


def _build_runtime_provider(
    provider_name: object,
    body: Dict[str, object],
    timeout,
) -> WeatherProvider:
    api_key = body.get("api_key")
    if (
        provider_name not in {"openweather", "qweather", "weatherapi", "visualcrossing"}
        or not isinstance(api_key, str)
        or not api_key.strip()
        or len(api_key.strip()) > 512
    ):
        raise ValueError("invalid provider configuration")

    if provider_name == "openweather":
        return OpenWeatherClient(api_key, timeout=timeout)
    if provider_name == "weatherapi":
        return WeatherApiClient(api_key, timeout=timeout)
    if provider_name == "visualcrossing":
        return VisualCrossingClient(api_key, timeout=timeout)

    api_host = body.get("api_host")
    if not isinstance(api_host, str):
        raise ValueError("QWeather API host is required")
    return QWeatherClient(api_key, api_host, timeout=timeout)


def _error_response(code: str, message: str, status_code: int):
    return jsonify({"error": {"code": code, "message": message}}), status_code


def _build_advice(day_offset: int, weather: WeatherData) -> Optional[str]:
    if day_offset != 1:
        return None
    if weather.rain_expected:
        return "明天可能有雨，建议携带雨具。"
    return "明天暂无明显降雨信号，出行可暂不携带雨具。"


def _weather_payload(weather: WeatherData, advice: Optional[str]):
    return {
        "temperature_c": weather.temperature_c,
        "condition": weather.condition,
        "humidity_percent": weather.humidity_percent,
        "wind_speed_mps": weather.wind_speed_mps,
        "rain_expected": weather.rain_expected,
        "advice": advice,
    }


if __name__ == "__main__":
    # 先设置 WEATHER_PROVIDER 及对应凭据，再执行 python app.py。
    create_app().run(host="127.0.0.1", port=5000, debug=False)
