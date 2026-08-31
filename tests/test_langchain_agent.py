import json

import pytest

from agent import AgentLimitError, AgentProtocolError, WeatherToolInput
from langchain_agent import ExistingChatModelAdapter, run_langchain_agent
from llm_client import AssistantTurn, ToolCall


class FakeLLMClient:
    model = "test-chat-model"
    display_name = "测试模型"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self._api_key = "must-not-appear"

    def complete(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": list(tools or [])})
        return self.responses.pop(0)


def weather_call(call_id="call-1", arguments=None):
    return ToolCall(
        call_id=call_id,
        name="get_weather",
        arguments_json=json.dumps(
            arguments
            or {"cities": ["深圳"], "day_offset": 1, "detail": "advice"},
            ensure_ascii=False,
        ),
    )


def test_langchain_general_chat_preserves_history_without_running_tool():
    model = FakeLLMClient([AssistantTurn("你好，我是晴问。")])
    executed = []

    result = run_langchain_agent(
        client=model,
        history=[{"role": "user", "content": "我叫小林"}],
        user_message="你好",
        weather_tool=lambda value: executed.append(value),
    )

    assert result.answer == "你好，我是晴问。"
    assert result.tool_inputs == ()
    assert result.tool_results == ()
    assert executed == []
    sent = model.calls[0]["messages"]
    assert sent[0]["role"] == "system"
    assert {"role": "user", "content": "我叫小林"} in sent
    assert sent[-1] == {"role": "user", "content": "你好"}
    assert model.calls[0]["tools"][0]["function"]["name"] == "get_weather"


def test_langchain_weather_tool_result_returns_to_model_before_final_answer():
    model = FakeLLMClient(
        [
            AssistantTurn("", (weather_call(),)),
            AssistantTurn("深圳明天有雨，建议带伞。"),
        ]
    )
    executed = []

    def weather_tool(tool_input):
        executed.append(tool_input)
        return {"results": [{"city": "深圳", "rain_expected": True}]}

    result = run_langchain_agent(
        client=model,
        history=[],
        user_message="深圳明天出门要带什么？",
        weather_tool=weather_tool,
    )

    assert executed == [WeatherToolInput(("深圳",), 1, "advice")]
    assert result.answer == "深圳明天有雨，建议带伞。"
    assert result.tool_inputs == (WeatherToolInput(("深圳",), 1, "advice"),)
    assert result.tool_results[0]["results"][0]["rain_expected"] is True
    second_messages = model.calls[1]["messages"]
    assert second_messages[-2]["role"] == "assistant"
    assert second_messages[-2]["tool_calls"][0]["id"] == "call-1"
    assert second_messages[-1]["role"] == "tool"
    assert second_messages[-1]["tool_call_id"] == "call-1"
    assert "深圳" in second_messages[-1]["content"]


def test_langchain_rejects_invalid_tool_arguments_before_execution():
    model = FakeLLMClient(
        [
            AssistantTurn(
                "",
                (
                    weather_call(
                        arguments={
                            "cities": ["一", "二", "三", "四", "五", "六"],
                            "day_offset": 1,
                            "detail": "full",
                        }
                    ),
                ),
            )
        ]
    )
    executed = []

    with pytest.raises(AgentProtocolError):
        run_langchain_agent(
            client=model,
            history=[],
            user_message="查询这些城市",
            weather_tool=lambda value: executed.append(value),
        )

    assert executed == []


def test_langchain_limits_weather_tool_calls_to_two():
    model = FakeLLMClient(
        [
            AssistantTurn("", (weather_call("call-1"),)),
            AssistantTurn("", (weather_call("call-2"),)),
            AssistantTurn("", (weather_call("call-3"),)),
        ]
    )
    executed = []

    with pytest.raises(AgentLimitError):
        run_langchain_agent(
            client=model,
            history=[],
            user_message="反复查天气",
            weather_tool=lambda value: executed.append(value) or {"results": []},
        )

    assert len(executed) == 2


def test_langchain_adapter_does_not_expose_wrapped_client_secrets():
    adapter = ExistingChatModelAdapter(client=FakeLLMClient([AssistantTurn("你好")]))

    assert "must-not-appear" not in repr(adapter)
    assert "must-not-appear" not in str(adapter._identifying_params)


def test_langchain_rejects_invalid_weather_tool_result():
    model = FakeLLMClient([AssistantTurn("", (weather_call(),))])

    with pytest.raises(AgentProtocolError, match="result is invalid"):
        run_langchain_agent(
            client=model,
            history=[],
            user_message="深圳明天天气",
            weather_tool=lambda value: ["not", "an", "object"],
        )


def test_langchain_does_not_swallow_weather_provider_errors():
    class WeatherProviderFailure(Exception):
        pass

    model = FakeLLMClient([AssistantTurn("", (weather_call(),))])

    def failing_weather_tool(value):
        raise WeatherProviderFailure("upstream failed")

    with pytest.raises(WeatherProviderFailure, match="upstream failed"):
        run_langchain_agent(
            client=model,
            history=[],
            user_message="深圳明天天气",
            weather_tool=failing_weather_tool,
        )
