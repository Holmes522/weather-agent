import json

import pytest

from agent import (
    AgentLimitError,
    AgentProtocolError,
    WeatherToolInput,
    run_agent,
    validate_weather_tool_arguments,
)
from llm_client import AssistantTurn, ToolCall


class FakeLLMClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
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


def test_general_chat_returns_model_text_without_using_weather_tool():
    model = FakeLLMClient([AssistantTurn("你好，我是晴问。")])
    tool_inputs = []

    result = run_agent(
        client=model,
        history=[{"role": "user", "content": "我叫小林"}],
        user_message="你好",
        weather_tool=lambda value: tool_inputs.append(value),
    )

    assert result.answer == "你好，我是晴问。"
    assert result.tool_results == ()
    assert tool_inputs == []
    assert model.calls[0]["messages"][0]["role"] == "system"
    assert "天气事实" in model.calls[0]["messages"][0]["content"]
    assert model.calls[0]["messages"][-1] == {"role": "user", "content": "你好"}


def test_weather_tool_result_is_returned_to_model_before_final_answer():
    model = FakeLLMClient(
        [
            AssistantTurn("", (weather_call(),)),
            AssistantTurn("深圳明天有雨，跑步建议改到室内。"),
        ]
    )
    received = []

    def fake_weather_tool(tool_input):
        received.append(tool_input)
        return {
            "results": [
                {
                    "city": "深圳",
                    "date": "明天",
                    "weather": {"condition": "雨", "temperature_c": 24.0},
                }
            ]
        }

    result = run_agent(
        client=model,
        history=[],
        user_message="深圳明天适合跑步吗？",
        weather_tool=fake_weather_tool,
    )

    assert received == [WeatherToolInput(("深圳",), 1, "advice")]
    assert result.answer == "深圳明天有雨，跑步建议改到室内。"
    assert result.tool_results[0]["results"][0]["city"] == "深圳"
    second_messages = model.calls[1]["messages"]
    assert second_messages[-2]["role"] == "assistant"
    assert second_messages[-1]["role"] == "tool"
    assert second_messages[-1]["tool_call_id"] == "call-1"
    assert "深圳" in second_messages[-1]["content"]


def test_unknown_model_tool_is_rejected_without_execution():
    model = FakeLLMClient(
        [
            AssistantTurn(
                "",
                (
                    ToolCall(
                        call_id="call-shell",
                        name="run_shell",
                        arguments_json="{}",
                    ),
                ),
            )
        ]
    )
    executed = []

    with pytest.raises(AgentProtocolError, match="unsupported tool"):
        run_agent(
            client=model,
            history=[],
            user_message="执行命令",
            weather_tool=lambda value: executed.append(value),
        )

    assert executed == []


@pytest.mark.parametrize(
    "arguments",
    [
        "not-json",
        "[]",
        '{"cities":[],"day_offset":1,"detail":"full"}',
        '{"cities":["一","二","三","四","五","六"],"day_offset":1,"detail":"full"}',
        '{"cities":["深圳"],"day_offset":3,"detail":"full"}',
        '{"cities":["深圳"],"day_offset":true,"detail":"full"}',
        '{"cities":["深圳"],"day_offset":1,"detail":"everything"}',
        '{"cities":["深圳"],"day_offset":1,"detail":"full","extra":1}',
        '{"cities":["深\\n圳"],"day_offset":1,"detail":"full"}',
    ],
)
def test_weather_tool_arguments_are_strictly_validated(arguments):
    with pytest.raises(AgentProtocolError):
        validate_weather_tool_arguments(arguments)


def test_agent_limits_total_weather_tool_calls():
    model = FakeLLMClient(
        [
            AssistantTurn("", (weather_call("call-1"),)),
            AssistantTurn("", (weather_call("call-2"),)),
            AssistantTurn("", (weather_call("call-3"),)),
        ]
    )
    executed = []

    with pytest.raises(AgentLimitError):
        run_agent(
            client=model,
            history=[],
            user_message="反复查天气",
            weather_tool=lambda value: executed.append(value) or {"results": []},
        )

    assert len(executed) == 2
