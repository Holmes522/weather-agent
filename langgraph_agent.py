"""使用显式 LangGraph StateGraph 编排天气与 RAG Agent。"""

from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from agent import (
    AgentLimitError,
    AgentProtocolError,
    AgentRunResult,
    ChatModel,
    SYSTEM_PROMPT,
    WeatherTool,
)
from agent_tools import AgentToolRuntime, create_agent_tool_runtime
from knowledge_base import KnowledgeChunk
from langchain_agent import (
    ExistingChatModelAdapter,
    final_answer_message,
    history_messages,
)


MAX_MODEL_CALLS = 4
MAX_TOTAL_TOOL_CALLS = 3
MAX_WEATHER_TOOL_CALLS = 2
MAX_KNOWLEDGE_TOOL_CALLS = 1
GRAPH_RECURSION_LIMIT = 16


class WeatherAgentGraphState(MessagesState):
    """显式图状态；消息由 LangGraph reducer 追加，答案只由 finalize 写入。"""

    answer: str
    model_calls: int
    tool_calls: int
    weather_tool_calls: int
    knowledge_tool_calls: int


@dataclass(frozen=True)
class LangGraphAgentWorkflow:
    """一次请求独享的编译图及其受限工具运行时。"""

    graph: Any
    tool_runtime: AgentToolRuntime


def build_langgraph_agent(
    client: ChatModel,
    weather_tool: WeatherTool,
    knowledge_search: Optional[
        Callable[[str], Sequence[KnowledgeChunk]]
    ] = None,
) -> LangGraphAgentWorkflow:
    """构建 model → tools → model / finalize 的显式有界状态图。"""

    tool_runtime = create_agent_tool_runtime(weather_tool, knowledge_search)
    bound_model = ExistingChatModelAdapter(client=client).bind_tools(
        tool_runtime.tools
    )

    def model_node(state: WeatherAgentGraphState) -> Dict[str, object]:
        model_calls = state.get("model_calls", 0)
        if model_calls >= MAX_MODEL_CALLS:
            raise AgentLimitError("agent model call limit exceeded")
        response = bound_model.invoke(
            [SystemMessage(content=SYSTEM_PROMPT), *state["messages"]]
        )
        if not isinstance(response, AIMessage):
            raise AgentProtocolError("agent model result is invalid")
        return {
            "messages": [response],
            "model_calls": model_calls + 1,
            **_next_tool_budget(response, state),
        }

    def route_after_model(
        state: WeatherAgentGraphState,
    ) -> Literal["tools", "finalize"]:
        message = _last_ai_message(state.get("messages"))
        return "tools" if message.tool_calls else "finalize"

    def finalize_node(state: WeatherAgentGraphState) -> Dict[str, str]:
        message = final_answer_message(state.get("messages"))
        return {"answer": message.content}

    # 官方建议在需要细粒度工具工作流时使用 ToolNode，并用条件边构建循环。
    # https://docs.langchain.com/oss/python/langchain/tools#toolnode
    builder = StateGraph(WeatherAgentGraphState)
    builder.add_node("model", model_node)
    builder.add_node(
        "tools",
        ToolNode(list(tool_runtime.tools), handle_tool_errors=False),
    )
    builder.add_node("finalize", finalize_node)
    builder.add_edge(START, "model")
    builder.add_conditional_edges(
        "model",
        route_after_model,
        {"tools": "tools", "finalize": "finalize"},
    )
    builder.add_edge("tools", "model")
    builder.add_edge("finalize", END)
    return LangGraphAgentWorkflow(
        graph=builder.compile(),
        tool_runtime=tool_runtime,
    )


def run_langgraph_agent(
    client: ChatModel,
    history: Sequence[Dict[str, str]],
    user_message: str,
    weather_tool: WeatherTool,
    knowledge_search: Optional[
        Callable[[str], Sequence[KnowledgeChunk]]
    ] = None,
) -> AgentRunResult:
    """执行一次显式 LangGraph 工作流并返回兼容的结构化结果。"""

    workflow = build_langgraph_agent(client, weather_tool, knowledge_search)
    messages: List[BaseMessage] = history_messages(history)
    messages.append(HumanMessage(content=user_message))
    try:
        output = workflow.graph.invoke(
            {
                "messages": messages,
                "answer": "",
                "model_calls": 0,
                "tool_calls": 0,
                "weather_tool_calls": 0,
                "knowledge_tool_calls": 0,
            },
            config={"recursion_limit": GRAPH_RECURSION_LIMIT},
        )
    except GraphRecursionError as error:
        raise AgentLimitError("agent graph recursion limit exceeded") from error

    answer = output.get("answer") if isinstance(output, dict) else None
    if not isinstance(answer, str) or not answer:
        raise AgentProtocolError("agent final answer is missing")
    runtime = workflow.tool_runtime
    return AgentRunResult(
        answer=answer,
        tool_results=tuple(runtime.tool_results),
        tool_inputs=tuple(runtime.tool_inputs),
        knowledge_sources=tuple(runtime.knowledge_sources),
    )


def _next_tool_budget(
    message: AIMessage,
    state: WeatherAgentGraphState,
) -> Dict[str, int]:
    proposed = Counter(call.get("name") for call in message.tool_calls)
    if None in proposed:
        raise AgentProtocolError("agent tool call is invalid")
    next_total = state.get("tool_calls", 0) + sum(proposed.values())
    next_weather = state.get("weather_tool_calls", 0) + proposed["get_weather"]
    next_knowledge = (
        state.get("knowledge_tool_calls", 0)
        + proposed["search_weather_knowledge"]
    )
    if (
        next_total > MAX_TOTAL_TOOL_CALLS
        or next_weather > MAX_WEATHER_TOOL_CALLS
        or next_knowledge > MAX_KNOWLEDGE_TOOL_CALLS
    ):
        raise AgentLimitError("agent tool call limit exceeded")
    return {
        "tool_calls": next_total,
        "weather_tool_calls": next_weather,
        "knowledge_tool_calls": next_knowledge,
    }


def _last_ai_message(messages: object) -> AIMessage:
    if not isinstance(messages, list) or not messages:
        raise AgentProtocolError("agent graph messages are invalid")
    message = messages[-1]
    if not isinstance(message, AIMessage):
        raise AgentProtocolError("agent graph route is invalid")
    return message
