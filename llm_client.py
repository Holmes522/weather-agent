"""OpenAI Chat Completions 兼容客户端，负责模型边界校验。"""

from dataclasses import dataclass
import ipaddress
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import requests


class LLMClientError(Exception):
    """模型调用或模型响应无效。"""


class LLMUpstreamError(LLMClientError):
    """模型网络、HTTP 状态或 JSON 解码失败。"""


class LLMDataError(LLMClientError):
    """模型响应不符合 Chat Completions 契约。"""


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments_json: str

    def as_api_value(self) -> Dict[str, Any]:
        return {
            "id": self.call_id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments_json,
            },
        }


@dataclass(frozen=True)
class AssistantTurn:
    content: str
    tool_calls: Tuple[ToolCall, ...] = ()

    def as_api_message(self) -> Dict[str, Any]:
        message: Dict[str, Any] = {
            "role": "assistant",
            "content": self.content or None,
        }
        if self.tool_calls:
            message["tool_calls"] = [call.as_api_value() for call in self.tool_calls]
        return message


RequestPost = Callable[..., Any]


class OpenAICompatibleClient:
    """通过受限 HTTP 请求调用兼容 `/chat/completions` 的模型服务。

    工具消息格式依据：
    https://developers.openai.com/api/docs/guides/function-calling
    """

    DEFAULT_TIMEOUT: Tuple[float, float] = (3.05, 30.0)
    MAX_RESPONSE_CHARACTERS = 4_000
    MAX_ARGUMENT_CHARACTERS = 8_000
    MAX_TOOL_CALLS_PER_RESPONSE = 8

    def __init__(
        self,
        api_key: Optional[str],
        base_url: str,
        model: str,
        request_post: RequestPost = requests.post,
        timeout: Tuple[float, float] = DEFAULT_TIMEOUT,
        max_tokens: int = 600,
        display_name: str = "AI 模型",
    ):
        endpoint, is_loopback = _model_endpoint(base_url)
        normalized_key = api_key.strip() if isinstance(api_key, str) else ""
        if not is_loopback and not normalized_key:
            raise ValueError("external model endpoint requires an API key")
        if len(normalized_key) > 2_048 or "\r" in normalized_key or "\n" in normalized_key:
            raise ValueError("model API key is invalid")

        normalized_model = model.strip() if isinstance(model, str) else ""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}", normalized_model):
            raise ValueError("model name is invalid")
        if (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or not 1 <= max_tokens <= 4_096
        ):
            raise ValueError("max_tokens is invalid")
        normalized_display_name = (
            display_name.strip() if isinstance(display_name, str) else ""
        )
        if not normalized_display_name or len(normalized_display_name) > 80:
            raise ValueError("display name is invalid")

        self._api_key = normalized_key
        self._endpoint = endpoint
        self._model = normalized_model
        self._request_post = request_post
        self._timeout = timeout
        self._max_tokens = max_tokens
        self._display_name = normalized_display_name

    @property
    def model(self) -> str:
        return self._model

    @property
    def display_name(self) -> str:
        return self._display_name

    def complete(
        self,
        messages: Sequence[Dict[str, Any]],
        tools: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> AssistantTurn:
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": list(messages),
            "max_tokens": self._max_tokens,
            "temperature": 0.3,
            "stream": False,
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        try:
            response = self._request_post(
                url=self._endpoint,
                headers=headers,
                json=payload,
                timeout=self._timeout,
                allow_redirects=False,
            )
            response.raise_for_status()
            response_payload = response.json()
        except (requests.RequestException, TimeoutError, ValueError) as error:
            raise LLMUpstreamError("model request failed") from error

        return _parse_assistant_turn(response_payload)


def _model_endpoint(base_url: object) -> Tuple[str, bool]:
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("model base URL is required")
    normalized = base_url.strip().rstrip("/")
    if len(normalized) > 2_048:
        raise ValueError("model base URL is too long")

    parsed = urlparse(normalized)
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    is_loopback = hostname == "localhost"
    try:
        if hostname and ipaddress.ip_address(hostname).is_loopback:
            is_loopback = True
    except ValueError:
        pass

    if (
        not hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.params
        or parsed.scheme not in {"http", "https"}
        or (parsed.scheme == "http" and not is_loopback)
    ):
        raise ValueError("model base URL is unsafe")

    endpoint = (
        normalized
        if parsed.path.rstrip("/").endswith("/chat/completions")
        else f"{normalized}/chat/completions"
    )
    return endpoint, is_loopback


def _parse_assistant_turn(payload: object) -> AssistantTurn:
    if not isinstance(payload, dict):
        raise LLMDataError("model response must be an object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise LLMDataError("model response choices are invalid")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise LLMDataError("model response message is invalid")

    raw_content = message.get("content")
    if raw_content is None:
        content = ""
    elif isinstance(raw_content, str):
        content = raw_content.strip()
    else:
        raise LLMDataError("model response content is invalid")
    if len(content) > OpenAICompatibleClient.MAX_RESPONSE_CHARACTERS:
        raise LLMDataError("model response content is too long")

    raw_tool_calls = message.get("tool_calls", [])
    if not isinstance(raw_tool_calls, list):
        raise LLMDataError("model tool calls are invalid")
    if len(raw_tool_calls) > OpenAICompatibleClient.MAX_TOOL_CALLS_PER_RESPONSE:
        raise LLMDataError("model returned too many tool calls")

    tool_calls: List[ToolCall] = []
    for raw_call in raw_tool_calls:
        tool_calls.append(_parse_tool_call(raw_call))
    if not content and not tool_calls:
        raise LLMDataError("model response is empty")
    return AssistantTurn(content=content, tool_calls=tuple(tool_calls))


def _parse_tool_call(raw_call: object) -> ToolCall:
    if not isinstance(raw_call, dict) or raw_call.get("type") != "function":
        raise LLMDataError("model tool call is invalid")
    call_id = raw_call.get("id")
    function = raw_call.get("function")
    if (
        not isinstance(call_id, str)
        or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", call_id)
        or not isinstance(function, dict)
    ):
        raise LLMDataError("model tool call identity is invalid")
    name = function.get("name")
    arguments = function.get("arguments")
    if (
        not isinstance(name, str)
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name)
        or not isinstance(arguments, str)
        or len(arguments) > OpenAICompatibleClient.MAX_ARGUMENT_CHARACTERS
    ):
        raise LLMDataError("model tool call function is invalid")
    return ToolCall(call_id=call_id, name=name, arguments_json=arguments)
