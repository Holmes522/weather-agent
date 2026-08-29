"""天气问题意图识别与基于结构化数据的回复生成。"""

import re
from typing import Optional

from weather_client import WeatherData


FULL = "full"
TEMPERATURE = "temperature"
HUMIDITY = "humidity"
WIND = "wind"
RAIN = "rain"
OUTING = "outing"
BRIEF = "brief"
FOLLOW_UP = "followup"

_POSITIVE_CONFIRMATION = re.compile(
    r"^(?:需要|要|可以|好|好的|行|告诉我|请告诉我|看看|想看)[。！!？?]*$"
)
_PURE_FOLLOW_UP = re.compile(
    r"^(?:那|那么|然后)?(?:今天|明天|后天)?(?:呢|如何|怎么样|什么样)?[？?。]*$"
)


def is_full_weather_confirmation(message: str) -> bool:
    return bool(_POSITIVE_CONFIRMATION.fullmatch(message.strip()))


def classify_intent(message: str, has_full_weather_offer: bool = False) -> str:
    """按更具体的意图优先分类，避免“天气”覆盖单项问题。"""

    normalized = re.sub(r"\s+", "", message)
    english = re.sub(r"\s+", " ", message).strip().lower()
    if has_full_weather_offer and is_full_weather_confirmation(normalized):
        return FULL
    if re.search(
        r"出门|带什么|带伞|雨伞|穿什么|穿衣|怎么穿|跑步|户外|运动",
        normalized,
    ) or re.search(r"\b(?:go out|going out|umbrella|what to wear|outdoor|exercise)\b", english):
        return OUTING
    if re.search(r"湿度|潮湿|干燥", normalized) or "humidity" in english:
        return HUMIDITY
    if re.search(r"风速|风大|刮风|几级风", normalized) or re.search(
        r"\b(?:wind|windy)\b", english
    ):
        return WIND
    if re.search(r"气温|温度|多少度|冷不冷|热不热", normalized) or re.search(
        r"\b(?:temperature|degrees|hot|cold)\b", english
    ):
        return TEMPERATURE
    if re.search(r"下雨|降雨|有雨|淋雨", normalized) or re.search(
        r"\b(?:rain|raining|rainy)\b", english
    ):
        return RAIN
    if "天气" in normalized or re.search(r"\b(?:weather|forecast)\b", english):
        return FULL
    if _PURE_FOLLOW_UP.fullmatch(normalized):
        return FOLLOW_UP
    return BRIEF


def build_weather_answer(
    city: str,
    date_label: str,
    weather: WeatherData,
    intent: str,
    corrected_from: Optional[str] = None,
) -> str:
    """只使用 WeatherData 中存在的字段生成意图化回复。"""

    prefix = ""
    if corrected_from:
        prefix = f"你输入的“{corrected_from}”可能是“{city}”，已按{city}查询。"

    if intent == HUMIDITY:
        answer = f"{city}{date_label}湿度约 {weather.humidity_percent}%。"
    elif intent == TEMPERATURE:
        answer = f"{city}{date_label}气温约 {weather.temperature_c:.1f}℃。"
    elif intent == WIND:
        answer = f"{city}{date_label}风速约 {weather.wind_speed_mps:.1f} m/s。"
    elif intent == RAIN:
        if weather.rain_expected:
            answer = f"{city}{date_label}有降雨可能，建议带伞。"
        else:
            answer = f"{city}{date_label}暂无明显降雨信号，可以先不带伞。"
    elif intent == OUTING:
        answer = _build_outing_answer(city, date_label, weather)
    elif intent == FULL:
        answer = (
            f"{city}{date_label}：{weather.condition}，气温约 {weather.temperature_c:.1f}℃，"
            f"湿度 {weather.humidity_percent}%，风速 {weather.wind_speed_mps:.1f} m/s。"
        )
        if date_label == "明天":
            answer += (
                "明天可能有雨，建议携带雨具。"
                if weather.rain_expected
                else "明天暂无明显降雨信号，出行可暂不携带雨具。"
            )
    else:
        answer = (
            f"{city}{date_label}预计{weather.condition}。"
            "你想了解温度、湿度、风速，还是出行建议？"
        )
    return f"{prefix}{answer}"


def _build_outing_answer(city: str, date_label: str, weather: WeatherData) -> str:
    suggestions = []
    if weather.rain_expected:
        suggestions.append("有降雨可能，出门建议带伞")
    else:
        suggestions.append("暂无明显降雨信号，可以先不带伞")
    if weather.temperature_c <= 10:
        suggestions.append("气温偏低，注意保暖")
    elif weather.temperature_c >= 30:
        suggestions.append("气温较高，注意补水和防晒")
    if weather.wind_speed_mps >= 8:
        suggestions.append("风比较大，注意避开高空坠物")
    advice = "；".join(suggestions)
    return f"{city}{date_label}{advice}。需要我再告诉你{city}{date_label}的完整天气吗？"
