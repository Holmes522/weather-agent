from conversation import build_weather_answer, classify_intent
from weather_client import WeatherData


def test_classifies_specific_weather_dimensions_before_full_weather():
    assert classify_intent("明天湿度如何") == "humidity"
    assert classify_intent("广州明天气温多少") == "temperature"
    assert classify_intent("深圳明天风大吗") == "wind"
    assert classify_intent("上海明天会下雨吗") == "rain"
    assert classify_intent("北京明天天气怎么样") == "full"


def test_classifies_outing_question_as_advice_instead_of_full_weather():
    assert classify_intent("深圳明天出门要带什么") == "outing"
    assert classify_intent("明天要带伞吗") == "outing"
    assert classify_intent("深圳明天适合跑步吗") == "outing"


def test_outing_answer_uses_rain_data_and_offers_full_weather():
    weather = WeatherData(25.0, "雨", 80, 2.0, True)

    answer = build_weather_answer("深圳", "明天", weather, "outing")

    assert "带伞" in answer
    assert "完整天气" in answer
    assert "湿度" not in answer
    assert "风速" not in answer


def test_humidity_answer_only_contains_requested_metric():
    weather = WeatherData(25.0, "阴", 73, 2.0, False)

    answer = build_weather_answer("深圳", "明天", weather, "humidity")

    assert answer == "深圳明天湿度约 73%。"


def test_corrected_city_is_explained_in_answer():
    weather = WeatherData(20.0, "晴", 45, 1.0, False)

    answer = build_weather_answer(
        "大理", "今天", weather, "full", corrected_from="大利"
    )

    assert answer.startswith("你输入的“大利”可能是“大理”")
    assert "大理今天" in answer
