"""将区域天气搜索结果转换为稳定的聊天响应和会话上下文。"""

from dataclasses import dataclass
from typing import Dict, Optional

from regional_weather import (
    REGIONAL_WEATHER_INTENT,
    RegionalWeatherProvider,
    RegionalWeatherQuery,
    build_regional_weather_answer,
    search_regional_weather,
)
from session_store import ConversationContext, ConversationMessage
from weather_export import WeatherSnapshot


@dataclass(frozen=True)
class RegionalChatOutcome:
    payload: Dict[str, object]
    context: ConversationContext


def build_regional_chat_outcome(
    provider: RegionalWeatherProvider,
    query: RegionalWeatherQuery,
    session_id: str,
    user_message: str,
    previous_context: Optional[ConversationContext],
    max_history_messages: int,
) -> RegionalChatOutcome:
    """执行有界搜索，并构造应用层响应；上游异常由调用方映射。"""

    regional_result = search_regional_weather(provider, query)
    answer = build_regional_weather_answer(regional_result)
    results = [
        {
            "city": item.city.name,
            "date": "今天",
            "corrected_from": None,
            "answer": f"{item.city.name}当前为{item.weather.condition}。",
            "weather": {
                "temperature_c": item.weather.temperature_c,
                "condition": item.weather.condition,
                "humidity_percent": item.weather.humidity_percent,
                "wind_speed_mps": item.weather.wind_speed_mps,
                "rain_expected": item.weather.rain_expected,
                "advice": None,
            },
        }
        for item in regional_result.matches
    ]
    previous_messages = previous_context.messages if previous_context else ()
    messages = (
        *previous_messages,
        ConversationMessage("user", user_message),
        ConversationMessage("assistant", answer),
    )[-max_history_messages:]
    context = ConversationContext(
        cities=(),
        day_offset=0,
        date_label="今天",
        intent=REGIONAL_WEATHER_INTENT,
        messages=messages,
        regional_scope=query.scope,
        regional_phenomena=query.phenomena,
        weather_snapshots=tuple(
            WeatherSnapshot(
                city=item.city.name,
                date_label="今天",
                provider="Open-Meteo",
                temperature_c=item.weather.temperature_c,
                condition=item.weather.condition,
                humidity_percent=item.weather.humidity_percent,
                wind_speed_mps=item.weather.wind_speed_mps,
                rain_expected=item.weather.rain_expected,
                advice=None,
            )
            for item in regional_result.matches
        ) or (previous_context.weather_snapshots if previous_context else ()),
    )
    payload = {
        "session_id": session_id,
        "provider": "openmeteo",
        "intent": REGIONAL_WEATHER_INTENT,
        "display_mode": "text",
        "scope": query.scope,
        "phenomena": list(query.phenomena),
        "cities": [item.city.name for item in regional_result.matches],
        "results": results,
        "answer": answer,
    }
    return RegionalChatOutcome(payload, context)
