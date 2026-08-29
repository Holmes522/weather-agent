import pytest

from llm_registry import InMemoryLLMRegistry, LLMRegistryError


class FakeClient:
    def __init__(self, name, model):
        self.display_name = name
        self.model = model


def test_registry_keeps_multiple_profiles_and_switches_active_client():
    registry = InMemoryLLMRegistry()
    first = registry.add(FakeClient("OpenAI", "gpt-test"))
    second = registry.add(FakeClient("Kimi", "kimi-test"))

    assert [item.id for item in registry.list_profiles()] == [first.id, second.id]
    assert registry.active_profile().id == second.id
    assert registry.select(first.id).id == first.id
    assert registry.client_for(first.id).display_name == "OpenAI"


def test_registry_rejects_unknown_profile_and_is_bounded():
    registry = InMemoryLLMRegistry(max_profiles=1)
    registry.add(FakeClient("OpenAI", "gpt-test"))

    with pytest.raises(LLMRegistryError):
        registry.add(FakeClient("Kimi", "kimi-test"))
    with pytest.raises(LLMRegistryError):
        registry.select("missing")
