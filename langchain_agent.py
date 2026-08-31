"""基于 LangChain/LangGraph 的受限天气 Agent 执行引擎。"""

import json
from typing import Any, Dict, List, Literal, Sequence, Tuple

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
from langchain_core.tools import BaseTool, tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, ConfigDict, Field

from agent import (
    AgentLimitError,
    AgentProtocolError,
    AgentRunResult,
    ChatModel,
    MAX_TOOL_RESULT_CHARACTERS,
    SYSTEM_PROMPT,
    WeatherTool,
    WeatherToolInput,
    normalize_history,
    validate_weather_tool_arguments,
)


class WeatherToolArguments(BaseModel):
    """LangChain 可见的工具参数；执行前还会经过项目自身的严格校验。"""

    model_config = ConfigDict(extra="forbid")

    cities: List[str] = Field(min_length=1, max_length=5)
    day_offset: Literal[0, 1, 2]
    detail: Literal[
        "full",
        "temperature",
        "humidity",
        "wind",
        "rain",
        "advice",
        "brief",
    ]


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
        for call in turn.tool_calls:
            if call.name != "get_weather":
                raise AgentProtocolError("unsupported tool requested")
            # 在 LangGraph 调度工具前执行项目原有安全校验，避免校验错误被模型重试。
            validated = validate_weather_tool_arguments(call.arguments_json)
            tool_calls.append(
                {
                    "name": call.name,
                    "args": {
                        "cities": list(validated.cities),
                        "day_offset": validated.day_offset,
                        "detail": validated.detail,
                    },
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
) -> AgentRunResult:
    """用 LangChain `create_agent` 执行一次有界的聊天/天气工具循环。"""

    tool_results: List[Dict[str, Any]] = []
    tool_inputs: List[WeatherToolInput] = []

    @tool("get_weather", args_schema=WeatherToolArguments)
    def get_weather(cities: List[str], day_offset: int, detail: str) -> str:
        """查询最多五个全球城市今天、明天或后天的真实天气。"""

        raw_arguments = json.dumps(
            {"cities": cities, "day_offset": day_offset, "detail": detail},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        tool_input = validate_weather_tool_arguments(raw_arguments)
        result = weather_tool(tool_input)
        if not isinstance(result, dict):
            raise AgentProtocolError("weather tool result is invalid")
        try:
            serialized = json.dumps(
                result, ensure_ascii=False, separators=(",", ":")
            )
        except (TypeError, ValueError) as error:
            raise AgentProtocolError("weather tool result is invalid") from error
        if len(serialized) > MAX_TOOL_RESULT_CHARACTERS:
            raise AgentLimitError("weather tool result is too large")

        tool_inputs.append(tool_input)
        tool_results.append(result)
        return serialized

    # create_agent 是 LangChain 1.x 的标准 Agent API，执行运行时由 LangGraph 提供。
    # https://docs.langchain.com/oss/python/langchain/agents
    graph = create_agent(
        model=ExistingChatModelAdapter(client=client),
        tools=[get_weather],
        system_prompt=SYSTEM_PROMPT,
        middleware=[
            ToolCallLimitMiddleware(
                tool_name="get_weather", run_limit=2, exit_behavior="error"
            ),
            ModelCallLimitMiddleware(run_limit=3, exit_behavior="error"),
        ],
        name="weather_agent",
    )
    messages: List[BaseMessage] = _history_messages(history)
    messages.append(HumanMessage(content=user_message))

    try:
        # 中间件自身会增加图步骤；业务上限仍由 2 次工具/3 次模型调用控制。
        output = graph.invoke({"messages": messages}, config={"recursion_limit": 32})
    except (ToolCallLimitExceededError, ModelCallLimitExceededError) as error:
        raise AgentLimitError("agent execution limit exceeded") from error

    final_message = _final_answer_message(output.get("messages", []))
    return AgentRunResult(
        answer=final_message.content,
        tool_results=tuple(tool_results),
        tool_inputs=tuple(tool_inputs),
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
