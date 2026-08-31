import json

import pytest

from agent import AgentLimitError, AgentProtocolError, KnowledgeSource, WeatherToolInput
from knowledge_base import KnowledgeChunk
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


def knowledge_call(call_id="knowledge-1", query="雷雨天爬山安全吗"):
    return ToolCall(
        call_id=call_id,
        name="search_weather_knowledge",
        arguments_json=json.dumps({"query": query}, ensure_ascii=False),
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


def test_langchain_can_combine_live_weather_with_retrieved_knowledge():
    model = FakeLLMClient(
        [
            AssistantTurn("", (weather_call(), knowledge_call())),
            AssistantTurn("深圳明天有雷雨，不建议爬山，请改为室内活动。"),
        ]
    )
    searched = []
    source_url = "https://www.cma.gov.cn/safety/thunderstorm"

    def knowledge_search(query):
        searched.append(query)
        return (
            KnowledgeChunk(
                content="雷电来临时应停止爬山和露营。",
                title="雷电天气户外安全指南",
                section="户外活动调整",
                source_name="中国气象局",
                source_url=source_url,
                score=0.82,
            ),
        )

    result = run_langchain_agent(
        client=model,
        history=[],
        user_message="深圳明天打雷，还适合爬山吗？",
        weather_tool=lambda value: {"results": [{"city": "深圳", "rain": True}]},
        knowledge_search=knowledge_search,
    )

    assert searched == ["雷雨天爬山安全吗"]
    assert result.answer == "深圳明天有雷雨，不建议爬山，请改为室内活动。"
    assert result.knowledge_sources == (
        KnowledgeSource(
            title="雷电天气户外安全指南",
            section="户外活动调整",
            source_name="中国气象局",
            source_url=source_url,
        ),
    )
    assert {tool["function"]["name"] for tool in model.calls[0]["tools"]} == {
        "get_weather",
        "search_weather_knowledge",
    }
    tool_messages = [
        item for item in model.calls[1]["messages"] if item["role"] == "tool"
    ]
    assert len(tool_messages) == 2
    assert any("停止爬山" in item["content"] for item in tool_messages)


def test_langchain_limits_knowledge_search_to_one_call():
    model = FakeLLMClient(
        [
            AssistantTurn("", (knowledge_call("knowledge-1"),)),
            AssistantTurn("", (knowledge_call("knowledge-2"),)),
        ]
    )
    searched = []

    with pytest.raises(AgentLimitError):
        run_langchain_agent(
            client=model,
            history=[],
            user_message="反复搜索雷雨资料",
            weather_tool=lambda value: {"results": []},
            knowledge_search=lambda query: searched.append(query) or (),
        )

    assert searched == ["雷雨天爬山安全吗"]


def test_langchain_rejects_invalid_knowledge_query_before_search():
    model = FakeLLMClient([AssistantTurn("", (knowledge_call(query="雷" * 201),))])
    searched = []

    with pytest.raises(AgentProtocolError):
        run_langchain_agent(
            client=model,
            history=[],
            user_message="查资料",
            weather_tool=lambda value: {"results": []},
            knowledge_search=lambda query: searched.append(query) or (),
        )

    assert searched == []
