import requests

import pytest

from llm_client import (
    LLMDataError,
    LLMUpstreamError,
    OpenAICompatibleClient,
)


class FakeResponse:
    def __init__(self, payload, status_error=None):
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        return self.payload


def test_chat_completion_sends_bounded_openai_compatible_request():
    calls = []

    def fake_post(**kwargs):
        calls.append(kwargs)
        return FakeResponse(
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "你好！"}}
                ]
            }
        )

    client = OpenAICompatibleClient(
        api_key="model-secret",
        base_url="https://models.example.com/v1",
        model="example-chat",
        request_post=fake_post,
    )
    result = client.complete(
        messages=[{"role": "user", "content": "你好"}],
        tools=[{"type": "function", "function": {"name": "get_weather"}}],
    )

    assert result.content == "你好！"
    assert result.tool_calls == ()
    assert calls[0]["url"] == "https://models.example.com/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer model-secret"
    assert calls[0]["json"]["model"] == "example-chat"
    assert calls[0]["json"]["max_tokens"] == 600
    assert calls[0]["json"]["tools"][0]["function"]["name"] == "get_weather"
    assert calls[0]["allow_redirects"] is False
    assert calls[0]["timeout"] == (3.05, 30.0)


def test_tool_calls_are_parsed_without_trusting_arguments():
    response = FakeResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-weather-1",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"cities":["深圳"],"day_offset":1}',
                                },
                            }
                        ],
                    }
                }
            ]
        }
    )
    client = OpenAICompatibleClient(
        api_key="test-key",
        base_url="https://api.example.com/v1/chat/completions",
        model="tool-model",
        request_post=lambda **_kwargs: response,
    )

    result = client.complete(messages=[{"role": "user", "content": "天气"}])

    assert result.content == ""
    assert result.tool_calls[0].call_id == "call-weather-1"
    assert result.tool_calls[0].name == "get_weather"
    assert result.tool_calls[0].arguments_json.startswith("{")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{"message": "bad"}]},
        {"choices": [{"message": {"content": 123}}]},
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "get_weather", "arguments": 7},
                            }
                        ],
                    }
                }
            ]
        },
    ],
)
def test_invalid_model_response_is_rejected(payload):
    client = OpenAICompatibleClient(
        api_key="test-key",
        base_url="https://api.example.com/v1",
        model="test-model",
        request_post=lambda **_kwargs: FakeResponse(payload),
    )

    with pytest.raises(LLMDataError):
        client.complete(messages=[{"role": "user", "content": "你好"}])


def test_network_and_http_details_are_hidden_behind_upstream_error():
    response = FakeResponse(
        {}, status_error=requests.HTTPError("secret upstream response")
    )
    client = OpenAICompatibleClient(
        api_key="test-key",
        base_url="https://api.example.com/v1",
        model="test-model",
        request_post=lambda **_kwargs: response,
    )

    with pytest.raises(LLMUpstreamError, match="model request failed"):
        client.complete(messages=[{"role": "user", "content": "你好"}])


@pytest.mark.parametrize(
    "base_url",
    [
        "http://api.example.com/v1",
        "https://user:password@api.example.com/v1",
        "https://api.example.com/v1?token=secret",
        "ftp://api.example.com/v1",
    ],
)
def test_unsafe_model_base_url_is_rejected(base_url):
    with pytest.raises(ValueError):
        OpenAICompatibleClient(
            api_key="test-key",
            base_url=base_url,
            model="test-model",
        )


def test_loopback_ollama_endpoint_can_run_without_a_real_api_key():
    client = OpenAICompatibleClient(
        api_key=None,
        base_url="http://127.0.0.1:11434/v1",
        model="qwen3:8b",
        request_post=lambda **_kwargs: FakeResponse(
            {"choices": [{"message": {"content": "本地回复"}}]}
        ),
    )

    result = client.complete(messages=[{"role": "user", "content": "你好"}])

    assert result.content == "本地回复"


def test_external_model_endpoint_requires_an_api_key():
    with pytest.raises(ValueError):
        OpenAICompatibleClient(
            api_key=None,
            base_url="https://api.example.com/v1",
            model="test-model",
        )
