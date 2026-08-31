"""基于 LangChain/LangGraph 的受限天气 Agent 执行引擎。"""

import json
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ConfigDict, Field

from agent import (
    AgentLimitError,
    AgentProtocolError,
    AgentRunResult,
    ChatModel,
    SYSTEM_PROMPT,
    WeatherTool,
    normalize_history,
    validate_weather_tool_arguments,
)
from agent_tools import create_agent_tool_runtime, validate_knowledge_tool_arguments
from knowledge_base import KnowledgeChunk


class ExistingChatModelAdapter(BaseChatModel):
    """把现有安全的 OpenAI-compatible 客户端接入 LangChain。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    client: Any = Field(exclude=True, repr=False)
    bound_tools: Tuple[Dict[str, Any], ...] = Field(
        default=(), exclude=True, repr=False
    )

    @property
    def _llm_type(self) -> str:
        return "weather-agent-openai-compatible"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        """仅暴露非敏感标识，不把 API Key 送进日志或跟踪。"""

        return {
            "model": getattr(self.client, "model", "unknown"),
            "display_name": getattr(self.client, "display_name", "AI 模型"),
        }

    def bind_tools(
        self,
        tools: Sequence[Dict[str, Any] | type | Any | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> "ExistingChatModelAdapter":
        """绑定 LangChain 工具，并转换为现有客户端理解的 function schema。"""

        if tool_choice not in {None, "auto"}:
            raise AgentProtocolError("unsupported tool choice")
        if kwargs:
            raise AgentProtocolError("unsupported model binding options")
        converted = tuple(convert_to_openai_tool(value) for value in tools)
        return self.model_copy(update={"bound_tools": converted})

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: List[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        if stop:
            raise AgentProtocolError("stop sequences are not supported")
        if kwargs:
            raise AgentProtocolError("unsupported model call options")

        turn = self.client.complete(
            messages=_messages_to_api(messages),
            tools=self.bound_tools,
        )
        tool_calls: List[Dict[str, Any]] = []
        bound_tool_names = {
            value.get("function", {}).get("name") for value in self.bound_tools
        }
        for call in turn.tool_calls:
            if call.name not in bound_tool_names:
                raise AgentProtocolError("unsupported tool requested")
            # 在 LangGraph 调度工具前执行项目安全校验，避免错误参数被模型重试。
            if call.name == "get_weather":
                validated = validate_weather_tool_arguments(call.arguments_json)
                arguments = {
                    "cities": list(validated.cities),
                    "day_offset": validated.day_offset,
                    "detail": validated.detail,
                }
            elif call.name == "search_weather_knowledge":
                arguments = {
                    "query": validate_knowledge_tool_arguments(call.arguments_json)
                }
            else:
                raise AgentProtocolError("unsupported tool requested")
            tool_calls.append(
                {
                    "name": call.name,
                    "args": arguments,
                    "id": call.call_id,
                    "type": "tool_call",
                }
            )

        message = AIMessage(content=turn.content, tool_calls=tool_calls)
        return ChatResult(generations=[ChatGeneration(message=message)])


def run_langchain_agent(
    client: ChatModel,
    history: Sequence[Dict[str, str]],
    user_message: str,
    weather_tool: WeatherTool,
    knowledge_search: Optional[
        Callable[[str], Sequence[KnowledgeChunk]]
    ] = None,
) -> AgentRunResult:
    """用 LangChain `create_agent` 执行一次有界的聊天/天气工具循环。"""

    tool_runtime = create_agent_tool_runtime(weather_tool, knowledge_search)

    # create_agent 是 LangChain 1.x 的标准 Agent API，执行运行时由 LangGraph 提供。
    # https://docs.langchain.com/oss/python/langchain/agents
    tools = list(tool_runtime.tools)
    middleware = [
        ToolCallLimitMiddleware(
            tool_name="get_weather", run_limit=2, exit_behavior="error"
        )
    ]
    if knowledge_search is not None:
        middleware.append(
            ToolCallLimitMiddleware(
                tool_name="search_weather_knowledge",
                run_limit=1,
                exit_behavior="error",
            )
        )
    middleware.extend(
        [
            ToolCallLimitMiddleware(run_limit=3, exit_behavior="error"),
            ModelCallLimitMiddleware(run_limit=4, exit_behavior="error"),
        ]
    )
    graph = create_agent(
        model=ExistingChatModelAdapter(client=client),
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        middleware=middleware,
        name="weather_agent",
    )
    messages: List[BaseMessage] = _history_messages(history)
    messages.append(HumanMessage(content=user_message))

    try:
        # 中间件自身会增加图步骤；业务上限仍由 3 次工具/4 次模型调用控制。
        output = graph.invoke({"messages": messages}, config={"recursion_limit": 32})
    except (ToolCallLimitExceededError, ModelCallLimitExceededError) as error:
        raise AgentLimitError("agent execution limit exceeded") from error

    final_message = _final_answer_message(output.get("messages", []))
    return AgentRunResult(
        answer=final_message.content,
        tool_results=tuple(tool_runtime.tool_results),
        tool_inputs=tuple(tool_runtime.tool_inputs),
        knowledge_sources=tuple(tool_runtime.knowledge_sources),
    )


def _history_messages(history: Sequence[Dict[str, str]]) -> List[BaseMessage]:
    messages: List[BaseMessage] = []
    for item in normalize_history(history):
        message_type = HumanMessage if item["role"] == "user" else AIMessage
        messages.append(message_type(content=item["content"]))
    return messages


def _messages_to_api(messages: Sequence[BaseMessage]) -> List[Dict[str, Any]]:
    converted: List[Dict[str, Any]] = []
    for message in messages:
        content = _text_content(message.content)
        if isinstance(message, SystemMessage):
            converted.append({"role": "system", "content": content})
        elif isinstance(message, HumanMessage):
            converted.append({"role": "user", "content": content})
        elif isinstance(message, AIMessage):
            api_message: Dict[str, Any] = {
                "role": "assistant",
                "content": content or None,
            }
            if message.tool_calls:
                api_message["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(
                                call["args"],
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        },
                    }
                    for call in message.tool_calls
                ]
            converted.append(api_message)
        elif isinstance(message, ToolMessage):
            converted.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": content,
                }
            )
        else:
            raise AgentProtocolError("unsupported LangChain message type")
    return converted


def _text_content(content: object) -> str:
    if not isinstance(content, str):
        raise AgentProtocolError("multimodal model messages are not supported")
    return content


def _final_answer_message(messages: object) -> AIMessage:
    if not isinstance(messages, list):
        raise AgentProtocolError("agent result is invalid")
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            content = _text_content(message.content).strip()
            if not content or len(content) > 4_000:
                raise AgentProtocolError("agent final answer is invalid")
            return AIMessage(content=content)
    raise AgentProtocolError("agent final answer is missing")
