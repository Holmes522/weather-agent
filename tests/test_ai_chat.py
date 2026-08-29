import json

from app import create_app
from config import Settings
from llm_client import AssistantTurn, LLMUpstreamError, ToolCall
from weather_client import WeatherData


class FakeWeatherClient:
    def __init__(self):
        self.calls = []

    def get_current(self, city):
        self.calls.append(("current", city.name, 0))
        return WeatherData(27.0, "多云", 64, 2.5, False)

    def get_forecast(self, city, day_offset):
        self.calls.append(("forecast", city.name, day_offset))
        return WeatherData(24.0, "雨", 82, 3.0, True)


class FakeLLMClient:
    model = "test-chat-model"
    display_name = "测试模型"

    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def complete(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        if self.error:
            raise self.error
        return self.responses.pop(0)


class FakeRegionalWeatherClient:
    def __init__(self):
        self.calls = []

    def get_current_many(self, cities):
        self.calls.append(tuple(city.name for city in cities))
        return tuple(
            WeatherData(25.0, "雷雨", 85, 3.0, True)
            if city.name == "长沙"
            else WeatherData(25.0, "晴", 50, 2.0, False)
            for city in cities
        )


def weather_tool_turn(city="深圳", day_offset=1, detail="advice"):
    return AssistantTurn(
        "",
        (
            ToolCall(
                call_id="call-weather",
                name="get_weather",
                arguments_json=json.dumps(
                    {
                        "cities": [city],
                        "day_offset": day_offset,
                        "detail": detail,
                    },
                    ensure_ascii=False,
                ),
            ),
        ),
    )


def test_configured_model_can_answer_general_chat_without_weather():
    weather = FakeWeatherClient()
    model = FakeLLMClient([AssistantTurn("你好，我可以陪你聊天，也可以帮你查天气。")])
    app = create_app(
        settings=Settings(api_key="test-key"),
        weather_client=weather,
        llm_client=model,
    )

    response = app.test_client().post(
        "/chat", json={"message": "你好，你能做什么？", "session_id": "ai-general"}
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["answer"].startswith("你好")
    assert body["mode"] == "agent"
    assert body["model"] == "测试模型"
    assert body["tool_used"] is False
    assert body["display_mode"] == "text"
    assert weather.calls == []


def test_regional_live_weather_is_grounded_before_the_configured_model():
    weather = FakeWeatherClient()
    regional = FakeRegionalWeatherClient()
    model = FakeLLMClient([AssistantTurn("我需要你先提供城市。")])
    app = create_app(
        settings=Settings(api_key="test-key"),
        weather_client=weather,
        llm_client=model,
        regional_weather_client=regional,
    )

    response = app.test_client().post(
        "/chat",
        json={"message": "哪里在打雷下雨", "session_id": "ai-regional"},
    )

    assert response.status_code == 200
    assert response.get_json()["cities"] == ["长沙"]
    assert regional.calls
    assert model.calls == []
    assert weather.calls == []


def test_agent_calls_real_weather_provider_and_returns_compatible_payload():
    weather = FakeWeatherClient()
    model = FakeLLMClient(
        [
            weather_tool_turn(),
            AssistantTurn("深圳明天有雨，不太适合户外跑步，建议改到室内。"),
        ]
    )
    app = create_app(
        settings=Settings(api_key="test-key"),
        weather_client=weather,
        llm_client=model,
    )

    response = app.test_client().post(
        "/chat",
        json={"message": "深圳明天适合跑步吗？", "session_id": "ai-weather"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["mode"] == "agent"
    assert body["tool_used"] is True
    assert body["city"] == "深圳"
    assert body["date"] == "明天"
    assert body["weather"]["rain_expected"] is True
    assert body["display_mode"] == "text"
    assert "室内" in body["answer"]
    assert weather.calls == [("forecast", "深圳", 1)]


def test_agent_full_weather_request_keeps_weather_card_presentation():
    model = FakeLLMClient(
        [weather_tool_turn(detail="full"), AssistantTurn("深圳明天完整天气如下。")]
    )
    app = create_app(
        settings=Settings(api_key="test-key"),
        weather_client=FakeWeatherClient(),
        llm_client=model,
    )

    response = app.test_client().post(
        "/chat", json={"message": "深圳明天天气怎么样？", "session_id": "ai-card"}
    )

    assert response.status_code == 200
    assert response.get_json()["display_mode"] == "weather_cards"


def test_agent_remembers_recent_general_conversation():
    model = FakeLLMClient(
        [AssistantTurn("很高兴认识你，小林。"), AssistantTurn("记得，你叫小林。")]
    )
    app = create_app(
        settings=Settings(api_key="test-key"),
        weather_client=FakeWeatherClient(),
        llm_client=model,
    )
    http = app.test_client()

    assert http.post(
        "/chat", json={"message": "我叫小林", "session_id": "ai-memory"}
    ).status_code == 200
    response = http.post(
        "/chat", json={"message": "我叫什么？", "session_id": "ai-memory"}
    )

    assert response.status_code == 200
    second_request_messages = model.calls[1]["messages"]
    assert {"role": "user", "content": "我叫小林"} in second_request_messages
    assert {"role": "assistant", "content": "很高兴认识你，小林。"} in second_request_messages


def test_general_chat_without_model_returns_configuration_hint():
    app = create_app(
        settings=Settings(api_key="test-key"),
        weather_client=FakeWeatherClient(),
    )

    response = app.test_client().post(
        "/chat", json={"message": "你好", "session_id": "no-model"}
    )

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "AI_NOT_CONFIGURED"


def test_model_failure_is_hidden_from_user():
    model = FakeLLMClient(error=LLMUpstreamError("secret model detail"))
    app = create_app(
        settings=Settings(api_key="test-key"),
        weather_client=FakeWeatherClient(),
        llm_client=model,
    )

    response = app.test_client().post(
        "/chat", json={"message": "你好", "session_id": "ai-error"}
    )

    assert response.status_code == 502
    assert response.get_json()["error"] == {
        "code": "AI_UNAVAILABLE",
        "message": "AI 服务暂时不可用，请稍后重试。",
    }
    assert "secret model detail" not in response.get_data(as_text=True)


def test_home_announces_when_ai_chat_is_enabled():
    model = FakeLLMClient([AssistantTurn("unused")])
    app = create_app(
        settings=Settings(api_key="test-key"),
        weather_client=FakeWeatherClient(),
        llm_client=model,
    )

    html = app.test_client().get("/").get_data(as_text=True)

    assert "AI 对话已开启" in html
    assert "有什么想聊的？" in html
    assert 'data-prompt="你好，你能做什么？"' in html


def test_home_explains_weather_only_mode_without_ai_model():
    app = create_app(
        settings=Settings(api_key="test-key"),
        weather_client=FakeWeatherClient(),
    )

    html = app.test_client().get("/").get_data(as_text=True)

    assert "天气模式" in html
    assert "配置 AI 后还能进行通用聊天" in html


def test_explicit_weather_question_never_uses_an_ungrounded_model_answer():
    weather = FakeWeatherClient()
    model = FakeLLMClient([AssistantTurn("我猜明天一定是晴天。")])
    app = create_app(
        settings=Settings(api_key="test-key"),
        weather_client=weather,
        llm_client=model,
    )

    response = app.test_client().post(
        "/chat",
        json={"message": "深圳明天适合跑步吗？", "session_id": "grounded-weather"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert "我猜" not in body["answer"]
    assert body["intent"] == "outing"
    assert body["weather"]["rain_expected"] is True
    assert weather.calls == [("forecast", "深圳", 1)]


def test_weather_concept_explanation_does_not_require_live_weather_data():
    weather = FakeWeatherClient()
    model = FakeLLMClient([AssistantTurn("湿度表示空气中水汽含量的相对程度。")])
    app = create_app(
        settings=Settings(api_key="test-key"),
        weather_client=weather,
        llm_client=model,
    )

    response = app.test_client().post(
        "/chat", json={"message": "解释一下什么是湿度", "session_id": "concept"}
    )

    assert response.status_code == 200
    assert response.get_json()["mode"] == "agent"
    assert "水汽" in response.get_json()["answer"]
    assert weather.calls == []


def test_weather_question_without_city_never_uses_model_guess():
    weather = FakeWeatherClient()
    model = FakeLLMClient([AssistantTurn("明天晴朗，最高温度 28℃。")])
    app = create_app(
        settings=Settings(api_key="test-key"),
        weather_client=weather,
        llm_client=model,
    )

    response = app.test_client().post(
        "/chat", json={"message": "明天天气怎么样？", "session_id": "missing-city"}
    )

    assert response.status_code == 422
    assert response.get_json()["error"] == {
        "code": "CITY_NOT_FOUND",
        "message": "请提供要查询的城市。",
    }
    assert weather.calls == []
