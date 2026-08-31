import json

import pytest
from langchain_core.messages import HumanMessage

from agent import AgentLimitError, AgentProtocolError, KnowledgeSource, WeatherToolInput
from knowledge_base import KnowledgeChunk
from langgraph_agent import build_langgraph_agent, run_langgraph_agent
from llm_client import AssistantTurn, ToolCall


class FakeLLMClient:
    model = "test-chat-model"
    display_name = "测试模型"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": list(tools or [])})
        return self.responses.pop(0)


def weather_call(call_id="weather-1"):
    return ToolCall(
        call_id=call_id,
        name="get_weather",
        arguments_json=json.dumps(
            {"cities": ["深圳"], "day_offset": 1, "detail": "advice"},
            ensure_ascii=False,
        ),
    )


def knowledge_call(call_id="knowledge-1"):
    return ToolCall(
        call_id=call_id,
        name="search_weather_knowledge",
        arguments_json=json.dumps(
            {"query": "雷雨天气适合爬山吗"}, ensure_ascii=False
        ),
    )


def thunderstorm_chunks(_query):
    return (
        KnowledgeChunk(
            content="雷电来临时应停止爬山和露营。",
            title="雷电天气户外安全指南",
            section="户外活动调整",
            source_name="中国气象局",
            source_url="https://www.cma.gov.cn/safety/thunderstorm",
            score=0.82,
        ),
    )


def test_explicit_langgraph_exposes_named_orchestration_nodes():
    workflow = build_langgraph_agent(
        client=FakeLLMClient([AssistantTurn("你好")]),
        weather_tool=lambda value: {"results": []},
        knowledge_search=thunderstorm_chunks,
    )

    graph_nodes = set(workflow.graph.get_graph().nodes)

    assert {"model", "tools", "finalize"}.issubset(graph_nodes)


def test_compiled_langgraph_budget_is_scoped_to_each_invocation():
    workflow = build_langgraph_agent(
        client=FakeLLMClient([AssistantTurn("第一次"), AssistantTurn("第二次")]),
        weather_tool=lambda value: {"results": []},
    )
    initial_state = {
        "messages": [HumanMessage(content="你好")],
        "answer": "",
        "model_calls": 0,
        "tool_calls": 0,
        "weather_tool_calls": 0,
        "knowledge_tool_calls": 0,
    }

    first = workflow.graph.invoke(initial_state)
    second = workflow.graph.invoke(initial_state)

    assert first["answer"] == "第一次"
    assert second["answer"] == "第二次"
    assert first["model_calls"] == second["model_calls"] == 1


def test_langgraph_general_chat_reaches_finalize_without_tools():
    model = FakeLLMClient([AssistantTurn("你好，我是晴问。")])
    executed = []

    result = run_langgraph_agent(
        client=model,
        history=[{"role": "user", "content": "我叫小林"}],
        user_message="你好",
        weather_tool=lambda value: executed.append(value),
    )

    assert result.answer == "你好，我是晴问。"
    assert result.tool_results == ()
    assert executed == []
    assert model.calls[0]["messages"][0]["role"] == "system"
    assert model.calls[0]["messages"][-1] == {"role": "user", "content": "你好"}


def test_langgraph_routes_tool_result_back_to_model_before_finalize():
    model = FakeLLMClient(
        [
            AssistantTurn("", (weather_call(),)),
            AssistantTurn("深圳明天有雨，建议带伞。"),
        ]
    )
    executed = []

    result = run_langgraph_agent(
        client=model,
        history=[],
        user_message="深圳明天出门要带什么？",
        weather_tool=lambda value: executed.append(value)
        or {"results": [{"city": "深圳", "rain_expected": True}]},
    )

    assert executed == [WeatherToolInput(("深圳",), 1, "advice")]
    assert result.answer == "深圳明天有雨，建议带伞。"
    assert model.calls[1]["messages"][-1]["role"] == "tool"
    assert model.calls[1]["messages"][-1]["tool_call_id"] == "weather-1"


def test_langgraph_combines_parallel_weather_and_rag_tools():
    model = FakeLLMClient(
        [
            AssistantTurn("", (weather_call(), knowledge_call())),
            AssistantTurn("深圳明天有雷雨，不建议爬山。"),
        ]
    )

    result = run_langgraph_agent(
        client=model,
        history=[],
        user_message="深圳明天打雷还适合爬山吗？",
        weather_tool=lambda value: {"results": [{"city": "深圳", "rain": True}]},
        knowledge_search=thunderstorm_chunks,
    )

    assert result.answer == "深圳明天有雷雨，不建议爬山。"
    assert result.knowledge_sources == (
        KnowledgeSource(
            title="雷电天气户外安全指南",
            section="户外活动调整",
            source_name="中国气象局",
            source_url="https://www.cma.gov.cn/safety/thunderstorm",
        ),
    )
    tool_messages = [
        message for message in model.calls[1]["messages"] if message["role"] == "tool"
    ]
    assert len(tool_messages) == 2
    assert {tool["function"]["name"] for tool in model.calls[0]["tools"]} == {
        "get_weather",
        "search_weather_knowledge",
    }


def test_langgraph_rejects_tool_budget_before_any_parallel_execution():
    model = FakeLLMClient(
        [
            AssistantTurn(
                "",
                (
                    weather_call("weather-1"),
                    weather_call("weather-2"),
                    weather_call("weather-3"),
                ),
            )
        ]
    )
    executed = []

    with pytest.raises(AgentLimitError):
        run_langgraph_agent(
            client=model,
            history=[],
            user_message="反复查询天气",
            weather_tool=lambda value: executed.append(value) or {"results": []},
        )

    assert executed == []


def test_langgraph_does_not_swallow_tool_execution_errors():
    class WeatherProviderFailure(Exception):
        pass

    model = FakeLLMClient([AssistantTurn("", (weather_call(),))])

    with pytest.raises(WeatherProviderFailure, match="upstream failed"):
        run_langgraph_agent(
            client=model,
            history=[],
            user_message="深圳明天天气",
            weather_tool=lambda value: (_ for _ in ()).throw(
                WeatherProviderFailure("upstream failed")
            ),
        )


def test_langgraph_rejects_oversized_final_answer():
    model = FakeLLMClient([AssistantTurn("雨" * 4_001)])

    with pytest.raises(AgentProtocolError, match="final answer is invalid"):
        run_langgraph_agent(
            client=model,
            history=[],
            user_message="你好",
            weather_tool=lambda value: {"results": []},
        )
