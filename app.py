"""天气查询 Agent 的 Flask REST API。"""

import re
from dataclasses import replace
from functools import partial
from io import BytesIO
from threading import RLock
from typing import Dict, Optional
from uuid import uuid4

from flask import Flask, abort, jsonify, render_template, request, send_file
from werkzeug.middleware.proxy_fix import ProxyFix

from agent import AgentError, ChatModel, WeatherToolInput, run_agent
from langchain_agent import run_langchain_agent
from knowledge_base import build_default_knowledge_base
from config import ConfigurationError, Settings
from conversation_history import (
    ensure_conversation_for_request,
    is_valid_session_id,
    record_visible_exchange_for_request,
    register_conversation_history,
)
from conversation import (
    BRIEF,
    FOLLOW_UP,
    FULL,
    HUMIDITY,
    OUTING,
    RAIN,
    TEMPERATURE,
    WIND,
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
from regional_chat import build_regional_chat_outcome
from regional_weather import (
    RegionalWeatherProvider,
    parse_regional_weather_query,
)
from session_store import (
    ConversationContext,
    ConversationMessage,
    InMemorySessionStore,
)
from llm_client import LLMClientError, OpenAICompatibleClient
from llm_registry import (
    LLM_PROVIDER_CATALOG,
    InMemoryLLMRegistry,
    LLMRegistryError,
    build_runtime_llm,
)
from export_store import InMemoryExportStore
from export_chat import (
    create_export_payload,
    export_prompt_payload,
    snapshots_from_results,
)
from weather_export import (
    WeatherReportContext,
    parse_export_request,
    weather_query_text,
)
from itinerary import (
    ItineraryCityNotFoundError,
    ItineraryValidationError,
    parse_itinerary_request,
    query_itinerary_weather,
)
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
MAX_HISTORY_MESSAGES = 12
LOCAL_ADDRESSES = {"127.0.0.1", "::1"}
AGENT_CAPABILITY_ANSWER = (
    "我主要能查询全球城市今天、明天和后天的真实天气，支持中文、英文和一次最多五个城市，"
    "并按需回答温度、湿度、风速、降雨或出行建议。天气结果和多城市行程还可以导出为 "
    "Word、Excel、PDF 或 Markdown；配置 AI 模型后，也能进行基础聊天、解释、写作和总结，"
    "并结合权威天气安全资料给出建议。"
    "如果城市存在重名，建议写成“城市, 国家/地区”，例如“Paris, France明天天气怎么样？”"
)
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
    llm_client: Optional[ChatModel] = None,
    regional_weather_client: Optional[RegionalWeatherProvider] = None,
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
    if effective_settings.agent_engine not in {"langchain", "native"}:
        raise ConfigurationError("Agent engine is invalid")
    if effective_settings.agent_engine == "langchain":
        knowledge_base = build_default_knowledge_base()
        agent_runner = partial(
            run_langchain_agent,
            knowledge_search=knowledge_base.search,
        )
    else:
        # 保留原生引擎作为不启用 RAG 的显式回滚路径。
        agent_runner = run_agent
    store = session_store or InMemorySessionStore()
    resolver = city_resolver or NominatimCityResolver(
        base_url=effective_settings.geocoding_api_url,
        user_agent=effective_settings.geocoding_user_agent,
        timeout=effective_settings.request_timeout_seconds,
    )
    regional_client = regional_weather_client or OpenMeteoClient(
        timeout=effective_settings.request_timeout_seconds
    )
    initial_llm = llm_client
    if initial_llm is None and effective_settings.llm_base_url:
        try:
            initial_llm = OpenAICompatibleClient(
                api_key=effective_settings.llm_api_key,
                base_url=effective_settings.llm_base_url,
                model=effective_settings.llm_model or "",
                display_name=effective_settings.llm_display_name,
            )
        except ValueError as error:
            raise ConfigurationError("LLM environment configuration is invalid") from error

    clients_lock = RLock()
    llm_registry = InMemoryLLMRegistry(initial_llm)
    export_store = InMemoryExportStore()
    chat_rate_limiter = InMemoryRateLimiter(
        effective_settings.chat_rate_limit_per_minute
    )

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    if effective_settings.is_production:
        # Render 等托管平台位于一层反向代理之后；只在生产模式信任这一层。
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    register_conversation_history(
        app, store, is_production=effective_settings.is_production
    )

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
            llm_status=llm_registry.status_payload()["llm"],
            llm_profiles=llm_registry.status_payload()["models"],
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
            llm_providers=LLM_PROVIDER_CATALOG,
            llm_status=llm_registry.status_payload()["llm"],
            llm_profiles=llm_registry.status_payload()["models"],
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

    @app.get("/api/llm")
    def llm_status():
        if effective_settings.is_production:
            abort(404)
        local_error = _require_local_request()
        if local_error is not None:
            return local_error
        return jsonify(llm_registry.status_payload())

    @app.post("/api/llm")
    def configure_llm():
        if effective_settings.is_production:
            abort(404)
        local_error = _require_local_request()
        if local_error is not None:
            return local_error
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _error_response("INVALID_JSON", "请求必须是 JSON 对象。", 400)
        try:
            client = build_runtime_llm(body)
        except (TypeError, ValueError):
            return _error_response(
                "INVALID_LLM_CONFIG",
                "模型配置不完整或格式不正确，请检查后重试。",
                422,
            )

        try:
            llm_registry.add(client)
        except LLMRegistryError:
            return _error_response(
                "LLM_PROFILE_LIMIT", "已保存的模型配置达到上限，请重启后重新配置。", 409
            )
        return jsonify(llm_registry.status_payload()), 201

    @app.patch("/api/llm/active")
    def select_llm():
        if effective_settings.is_production:
            abort(404)
        local_error = _require_local_request()
        if local_error is not None:
            return local_error
        body = request.get_json(silent=True)
        profile_id = body.get("id") if isinstance(body, dict) else None
        if not isinstance(profile_id, str):
            return _error_response("INVALID_LLM", "请选择有效的 AI 模型配置。", 422)
        try:
            llm_registry.select(profile_id)
        except LLMRegistryError:
            return _error_response("INVALID_LLM", "没有找到该 AI 模型配置。", 422)
        return jsonify(llm_registry.status_payload())

    @app.get("/api/exports/<export_id>")
    def download_export(export_id: str):
        if not re.fullmatch(r"[0-9a-f]{32}", export_id):
            abort(404)
        artifact = export_store.get(export_id)
        if artifact is None:
            abort(404)
        response = send_file(
            BytesIO(artifact.content),
            mimetype=artifact.mimetype,
            as_attachment=True,
            download_name=artifact.filename,
            max_age=0,
        )
        response.headers["Cache-Control"] = "no-store"
        return response

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
        elif not isinstance(session_id, str) or not is_valid_session_id(session_id):
            return _error_response(
                "INVALID_SESSION", "session_id 只能包含字母、数字和 . _ : -。", 422
            )

        if not ensure_conversation_for_request(store, session_id):
            return _error_response(
                "CONVERSATION_NOT_FOUND", "没有找到该对话。", 404
            )

        previous_context = store.get_context(session_id)
        export_request = parse_export_request(message)
        export_query_message = (
            weather_query_text(message) if export_request.requested else message
        )
        parsed_export_query = (
            parse_query(export_query_message) if export_request.requested else None
        )
        references_previous_weather = bool(
            export_request.requested
            and re.search(r"刚才|上次|之前|这个|这些|它|最近", message)
        )
        if export_request.requested and export_request.format is None:
            response_payload = export_prompt_payload(
                session_id,
                "请选择导出格式：Word、Excel、PDF 或 Markdown。",
            )
            record_visible_exchange_for_request(store, session_id, message, response_payload)
            return jsonify(response_payload)
        try:
            itinerary_request = (
                parse_itinerary_request(message)
                if export_request.requested and export_request.format
                else None
            )
        except ItineraryValidationError as error:
            return _error_response("INVALID_ITINERARY", str(error), 422)
        if (
            export_request.requested
            and itinerary_request is None
            and parsed_export_query is not None
            and (
                not parsed_export_query.location_terms
                or references_previous_weather
            )
        ):
            if previous_context and previous_context.weather_snapshots:
                response_payload = create_export_payload(
                    session_id,
                    previous_context.weather_snapshots,
                    export_request.format or "md",
                    export_store,
                    previous_context.weather_report_context,
                )
            else:
                response_payload = export_prompt_payload(
                    session_id,
                    "还没有可导出的天气数据，请先查询天气。",
                )
            record_visible_exchange_for_request(store, session_id, message, response_payload)
            return jsonify(response_payload)

        if itinerary_request is not None:
            try:
                itinerary_snapshots, itinerary_cities = query_itinerary_weather(
                    itinerary_request,
                    selected_client,
                    resolver,
                    _provider_name(provider),
                )
            except ItineraryValidationError as error:
                return _error_response("INVALID_ITINERARY", str(error), 422)
            except ItineraryCityNotFoundError as error:
                return _error_response(
                    "CITY_NOT_FOUND",
                    f"没有找到“{error.location}”，请检查城市名称。",
                    422,
                )
            except GeocodingError:
                return _error_response(
                    "LOCATION_UNAVAILABLE", "城市查询服务暂时不可用，请稍后重试。", 502
                )
            except WeatherClientError:
                return _error_response(
                    "WEATHER_UNAVAILABLE", "天气服务暂时不可用，请稍后重试。", 502
                )

            report_context = WeatherReportContext(
                origin=itinerary_request.origin,
                total_days=itinerary_request.total_days,
                ordered=itinerary_request.ordered,
            )
            response_payload = create_export_payload(
                session_id,
                itinerary_snapshots,
                export_request.format or "md",
                export_store,
                report_context,
            )
            store.set_context(
                session_id,
                ConversationContext(
                    cities=itinerary_cities,
                    day_offset=itinerary_request.start_offset,
                    date_label="行程",
                    intent=FULL,
                    messages=previous_context.messages if previous_context else (),
                    weather_snapshots=itinerary_snapshots,
                    weather_report_context=report_context,
                ),
            )
            record_visible_exchange_for_request(
                store, session_id, message, response_payload
            )
            return jsonify(response_payload)

        pending_export_format = (
            export_request.format if export_request.requested else None
        )
        regional_query = parse_regional_weather_query(
            message,
            previous_scope=(previous_context.regional_scope if previous_context else ""),
            previous_phenomena=(
                previous_context.regional_phenomena if previous_context else ()
            ),
        )
        if regional_query is not None:
            try:
                regional_outcome = build_regional_chat_outcome(
                    provider=regional_client,
                    query=regional_query,
                    session_id=session_id,
                    user_message=message,
                    previous_context=previous_context,
                    max_history_messages=MAX_HISTORY_MESSAGES,
                )
            except WeatherClientError:
                return _error_response(
                    "WEATHER_UNAVAILABLE", "天气服务暂时不可用，请稍后重试。", 502
                )
            store.set_context(session_id, regional_outcome.context)
            response_payload = regional_outcome.payload
            record_visible_exchange_for_request(
                store, session_id, message, response_payload
            )
            return jsonify(response_payload)

        grounding_required = _requires_weather_grounding(message, previous_context)

        llm_id = body.get("llm_id")
        if llm_id is not None and not isinstance(llm_id, str):
            return _error_response("INVALID_LLM", "请选择有效的 AI 模型配置。", 422)
        try:
            active_llm = llm_registry.client_for(llm_id)
        except LLMRegistryError:
            return _error_response("INVALID_LLM", "没有找到该 AI 模型配置。", 422)
        if _is_agent_capability_question(message):
            previous_messages = previous_context.messages if previous_context else ()
            messages = (
                *previous_messages,
                ConversationMessage("user", message),
                ConversationMessage("assistant", AGENT_CAPABILITY_ANSWER),
            )[-MAX_HISTORY_MESSAGES:]
            context = (
                replace(previous_context, messages=messages)
                if previous_context
                else ConversationContext(cities=(), intent=BRIEF, messages=messages)
            )
            response_payload = {
                "session_id": session_id,
                "provider": provider,
                "mode": "agent" if active_llm is not None else "weather",
                "tool_used": False,
                "rag_used": False,
                "knowledge_sources": [],
                "intent": "capabilities",
                "display_mode": "text",
                "answer": AGENT_CAPABILITY_ANSWER,
            }
            if active_llm is not None:
                response_payload["model"] = active_llm.display_name
                response_payload["agent_engine"] = effective_settings.agent_engine
            store.set_context(session_id, context)
            record_visible_exchange_for_request(
                store, session_id, message, response_payload
            )
            return jsonify(response_payload)
        if active_llm is not None:
            agent_tool_contexts = []

            def execute_weather_tool(tool_input: WeatherToolInput):
                payload, resolved = _execute_weather_tool(
                    tool_input,
                    selected_client,
                    resolver,
                )
                agent_tool_contexts.append((tool_input, resolved))
                return payload

            history = [
                {"role": item.role, "content": item.content}
                for item in (previous_context.messages if previous_context else ())
            ]
            try:
                agent_result = agent_runner(
                    client=active_llm,
                    history=history,
                    user_message=message,
                    weather_tool=execute_weather_tool,
                )
            except CityNotFoundError as error:
                return _error_response(
                    "CITY_NOT_FOUND",
                    f"没有找到“{error.location}”，请检查城市名称。",
                    422,
                )
            except GeocodingError:
                return _error_response(
                    "LOCATION_UNAVAILABLE", "城市查询服务暂时不可用，请稍后重试。", 502
                )
            except WeatherClientError:
                return _error_response(
                    "WEATHER_UNAVAILABLE", "天气服务暂时不可用，请稍后重试。", 502
                )
            except (LLMClientError, AgentError):
                return _error_response(
                    "AI_UNAVAILABLE", "AI 服务暂时不可用，请稍后重试。", 502
                )

            if (
                agent_result.tool_results
                or agent_result.knowledge_sources
                or not grounding_required
            ):
                previous_messages = (
                    previous_context.messages if previous_context else ()
                )
                messages = (
                    *previous_messages,
                    ConversationMessage("user", message),
                    ConversationMessage("assistant", agent_result.answer),
                )[-MAX_HISTORY_MESSAGES:]
                if agent_tool_contexts:
                    last_input, last_resolutions = agent_tool_contexts[-1]
                    context = ConversationContext(
                        cities=tuple(item.city for item in last_resolutions),
                        day_offset=last_input.day_offset,
                        date_label=_date_label(last_input.day_offset),
                        intent=_intent_from_detail(last_input.detail),
                        offered_full_weather=last_input.detail == "advice",
                        messages=messages,
                    )
                else:
                    context = ConversationContext(
                        cities=previous_context.cities if previous_context else (),
                        day_offset=previous_context.day_offset if previous_context else 0,
                        date_label=(
                            previous_context.date_label if previous_context else "今天"
                        ),
                        intent=previous_context.intent if previous_context else BRIEF,
                        offered_full_weather=False,
                        messages=messages,
                        regional_scope=(
                            previous_context.regional_scope if previous_context else ""
                        ),
                        regional_phenomena=(
                            previous_context.regional_phenomena
                            if previous_context
                            else ()
                        ),
                        weather_snapshots=(
                            previous_context.weather_snapshots
                            if previous_context
                            else ()
                        ),
                        weather_report_context=(
                            previous_context.weather_report_context
                            if previous_context
                            else None
                        ),
                    )
                response_payload = _agent_response_payload(
                    session_id=session_id,
                    provider=provider,
                    model_name=active_llm.display_name,
                    agent_engine=effective_settings.agent_engine,
                    answer=agent_result.answer,
                    tool_results=agent_result.tool_results,
                    tool_inputs=agent_result.tool_inputs,
                    knowledge_sources=agent_result.knowledge_sources,
                )
                if agent_result.tool_results:
                    snapshots = snapshots_from_results(
                        response_payload.get("results", ()), _provider_name(provider)
                    )
                    context = replace(context, weather_snapshots=snapshots)
                    if pending_export_format:
                        response_payload = create_export_payload(
                            session_id,
                            snapshots,
                            pending_export_format,
                            export_store,
                        )
                        response_payload["agent_engine"] = (
                            effective_settings.agent_engine
                        )
                        response_payload["model"] = active_llm.display_name
                        response_payload["rag_used"] = bool(
                            agent_result.knowledge_sources
                        )
                        response_payload["knowledge_sources"] = (
                            _knowledge_sources_payload(
                                agent_result.knowledge_sources
                            )
                        )
                store.set_context(session_id, context)
                record_visible_exchange_for_request(
                    store,
                    session_id,
                    message,
                    response_payload,
                )
                return jsonify(response_payload)

        fallback_intent = classify_intent(
            message,
            has_full_weather_offer=bool(
                previous_context and previous_context.offered_full_weather
            ),
        )
        if (
            not _looks_like_weather_request(message)
            and fallback_intent not in {FULL, FOLLOW_UP}
        ):
            return _error_response(
                "AI_NOT_CONFIGURED",
                "AI 聊天模型尚未配置；请打开配置页面添加模型，天气查询仍可直接使用。",
                422,
            )

        parsed = parse_query(export_query_message)
        intent = fallback_intent
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
                messages=previous_context.messages if previous_context else (),
                weather_snapshots=snapshots_from_results(
                    weather_results, _provider_name(provider)
                ),
            ),
        )
        first_result = weather_results[0]
        response_payload = {
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
        if pending_export_format:
            response_payload = create_export_payload(
                session_id,
                snapshots_from_results(weather_results, _provider_name(provider)),
                pending_export_format,
                export_store,
            )
        record_visible_exchange_for_request(
            store,
            session_id,
            message,
            response_payload,
        )
        return jsonify(response_payload)

    return app


class CityNotFoundError(Exception):
    def __init__(self, location: str):
        super().__init__("city not found")
        self.location = location


def _execute_weather_tool(
    tool_input: WeatherToolInput,
    weather_client: WeatherProvider,
    resolver: CityResolver,
):
    resolutions = []
    for location in tool_input.cities:
        known_city = SUPPORTED_CITIES.get(location)
        resolution = (
            CityResolution(known_city)
            if known_city is not None
            else resolver.resolve(location)
        )
        if resolution is None:
            raise CityNotFoundError(location)
        resolutions.append(resolution)

    date_label = _date_label(tool_input.day_offset)
    intent = _intent_from_detail(tool_input.detail)
    results = []
    for resolution in resolutions:
        weather = (
            weather_client.get_current(resolution.city)
            if tool_input.day_offset == 0
            else weather_client.get_forecast(resolution.city, tool_input.day_offset)
        )
        advice = _build_advice(tool_input.day_offset, weather)
        results.append(
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
                "weather": _weather_payload(weather, advice),
            }
        )
    return (
        {
            "cities": [item["city"] for item in results],
            "date": date_label,
            "detail": tool_input.detail,
            "results": results,
        },
        resolutions,
    )


def _agent_response_payload(
    session_id: str,
    provider: str,
    model_name: str,
    agent_engine: str,
    answer: str,
    tool_results,
    tool_inputs,
    knowledge_sources,
):
    serialized_sources = _knowledge_sources_payload(knowledge_sources)
    payload = {
        "session_id": session_id,
        "provider": provider,
        "mode": "agent",
        "model": model_name,
        "agent_engine": agent_engine,
        "tool_used": bool(tool_results or serialized_sources),
        "rag_used": bool(serialized_sources),
        "knowledge_sources": serialized_sources,
        "display_mode": "text",
        "answer": answer,
    }
    if not tool_results:
        return payload

    weather_results = [
        result
        for tool_result in tool_results
        for result in tool_result.get("results", [])
        if isinstance(result, dict)
    ]
    if not weather_results:
        return payload
    first_result = weather_results[0]
    last_input = tool_inputs[-1]
    payload.update(
        {
            "city": first_result["city"],
            "cities": [result["city"] for result in weather_results],
            "date": first_result["date"],
            "intent": _intent_from_detail(last_input.detail),
            "display_mode": (
                "weather_cards"
                if any(item.detail == "full" for item in tool_inputs)
                else "text"
            ),
            "weather": first_result["weather"],
            "results": weather_results,
        }
    )
    return payload


def _knowledge_sources_payload(knowledge_sources):
    return [
        {
            "title": source.title,
            "section": source.section,
            "source_name": source.source_name,
            "source_url": source.source_url,
        }
        for source in knowledge_sources
    ]


def _intent_from_detail(detail: str) -> str:
    return {
        "full": FULL,
        "temperature": TEMPERATURE,
        "humidity": HUMIDITY,
        "wind": WIND,
        "rain": RAIN,
        "advice": OUTING,
        "brief": BRIEF,
    }[detail]


def _date_label(day_offset: int) -> str:
    return ("今天", "明天", "后天")[day_offset]


def _looks_like_weather_request(message: str) -> bool:
    return bool(
        re.search(
            r"天气|气温|温度|湿度|风速|风大|刮风|下雨|降雨|带伞|出门|穿衣|跑步|户外|运动|冷不冷|热不热|今天|明天|后天|"
            r"\b(?:weather|forecast|temperature|humidity|wind|windy|rain|raining|rainy|umbrella|outdoor|today|tomorrow)\b",
            message,
            re.IGNORECASE,
        )
    )


def _is_global_city_capability_question(message: str) -> bool:
    """识别全球查询能力询问，避免把“国外”误送去地理编码。"""

    normalized = re.sub(r"\s+", "", message)
    if re.search(r"今天|明天|后天|\b(?:today|tomorrow)\b", normalized, re.I):
        return False
    scope = r"(?:国外|海外|全球|全世界|世界各地)"
    trailing = r"(?:的)?(?:城市)?(?:的?天气)?(?:吗|呢|么)?[？?。！!]*"
    capability_first = re.fullmatch(
        rf"(?:你)?(?:可不可以|不可以|可以|能不能|不能|能否|能|是否支持|支持)"
        rf"(?:查询|查|查看|查到)?{scope}{trailing}",
        normalized,
    )
    scope_first = re.fullmatch(
        rf"{scope}(?:城市)?(?:的?天气)?(?:也)?"
        rf"(?:可不可以|可以|能不能|不能|能否|是否支持|支持|能查|能查询|能查看|能查到)"
        r"(?:查询|查|查看|查到)?(?:吗|呢|么)?[？?。！!]*",
        normalized,
    )
    return bool(capability_first or scope_first)


def _is_agent_capability_question(message: str) -> bool:
    """能力说明使用应用事实，避免模型臆测功能或地域范围。"""

    if _is_global_city_capability_question(message):
        return True
    normalized = re.sub(r"\s+", "", message)
    return bool(
        re.fullmatch(
            r"(?:你好[,，]?)?(?:(?:你)?(?:可以|能|会)做(?:些)?什么|"
            r"(?:你)?(?:有)?哪些(?:能力|功能)|"
            r"介绍(?:一下)?(?:你)?的?(?:能力|功能))[？?。！!]*",
            normalized,
        )
    )


def _requires_weather_grounding(
    message: str, previous_context: Optional[ConversationContext]
) -> bool:
    # Definition and explanation questions may mention weather vocabulary without
    # asking for live conditions, so they can be answered directly by the model.
    if re.search(r"什么是|是什么意思|解释(?:一下)?|定义|概念|原理", message):
        return False
    if not re.search(
        r"天气|气温|温度|湿度|风速|风大|刮风|下雨|降雨|带伞|出门|穿衣|跑步|户外|运动|冷不冷|热不热|"
        r"\b(?:weather|forecast|temperature|humidity|wind|windy|rain|raining|rainy|umbrella|outdoor)\b",
        message,
        re.IGNORECASE,
    ):
        return False
    parsed = parse_query(message)
    has_city_context = bool(previous_context and previous_context.cities)
    has_relative_date = bool(
        re.search(r"今天|明天|后天|\b(?:today|tomorrow)\b", message, re.IGNORECASE)
    )
    return bool(
        parsed.location_terms
        or has_city_context
        or has_relative_date
        or "天气" in message
        or bool(re.search(r"\b(?:weather|forecast)\b", message, re.IGNORECASE))
    )


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
