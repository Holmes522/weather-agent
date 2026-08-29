"""线程安全的进程内 AI 模型配置注册表。"""

from dataclasses import dataclass
from threading import RLock
from typing import Dict, Optional, Tuple
from uuid import uuid4

from agent import ChatModel
from llm_client import OpenAICompatibleClient


LLM_PROVIDER_CATALOG = (
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "requires_key": True},
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "requires_key": True},
    {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "requires_key": True},
    {"id": "glm", "name": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4", "requires_key": True},
    {"id": "kimi", "name": "Moonshot Kimi", "base_url": "https://api.moonshot.cn/v1", "requires_key": True},
    {"id": "qwen", "name": "通义千问", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "requires_key": True},
    {"id": "doubao", "name": "豆包（火山方舟）", "base_url": "https://ark.cn-beijing.volces.com/api/v3", "requires_key": True},
    {"id": "gemini", "name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "requires_key": True},
    {"id": "ollama", "name": "Ollama（本机）", "base_url": "http://127.0.0.1:11434/v1", "requires_key": False},
    {"id": "custom", "name": "自定义兼容接口", "base_url": None, "requires_key": True},
)


class LLMRegistryError(ValueError):
    """注册表已满或请求的配置不存在。"""


@dataclass(frozen=True)
class LLMProfile:
    """不含密钥的模型配置引用；真实客户端只保存在服务端内存。"""

    id: str
    client: ChatModel

    @property
    def provider(self) -> str:
        return self.client.display_name

    @property
    def model(self) -> str:
        return self.client.model


class InMemoryLLMRegistry:
    """有界模型注册表；新增配置会成为当前配置，但不会覆盖旧配置。"""

    def __init__(self, initial_client: Optional[ChatModel] = None, max_profiles: int = 20):
        if max_profiles < 1:
            raise ValueError("max_profiles must be positive")
        self._profiles = []
        self._active_id: Optional[str] = None
        self._max_profiles = max_profiles
        self._lock = RLock()
        if initial_client is not None:
            self.add(initial_client)

    def add(self, client: ChatModel) -> LLMProfile:
        with self._lock:
            if len(self._profiles) >= self._max_profiles:
                raise LLMRegistryError("model profile limit reached")
            profile = LLMProfile(uuid4().hex, client)
            self._profiles.append(profile)
            self._active_id = profile.id
            return profile

    def list_profiles(self) -> Tuple[LLMProfile, ...]:
        with self._lock:
            return tuple(self._profiles)

    def active_profile(self) -> Optional[LLMProfile]:
        with self._lock:
            return self._find_locked(self._active_id)

    def select(self, profile_id: str) -> LLMProfile:
        with self._lock:
            profile = self._find_locked(profile_id)
            if profile is None:
                raise LLMRegistryError("model profile not found")
            self._active_id = profile.id
            return profile

    def client_for(self, profile_id: Optional[str] = None) -> Optional[ChatModel]:
        with self._lock:
            target_id = profile_id if profile_id is not None else self._active_id
            profile = self._find_locked(target_id)
            if profile_id is not None and profile is None:
                raise LLMRegistryError("model profile not found")
            return profile.client if profile is not None else None

    def status_payload(self):
        with self._lock:
            profiles = tuple(self._profiles)
            active = self._find_locked(self._active_id)
            active_id = self._active_id

        def serialize(profile: LLMProfile, is_active: bool):
            return {
                "configured": True,
                "id": profile.id,
                "provider": profile.provider,
                "model": profile.model,
                "active": is_active,
            }

        llm = (
            {
                "configured": False,
                "id": None,
                "provider": None,
                "model": None,
            }
            if active is None
            else {
                key: value
                for key, value in serialize(active, True).items()
                if key != "active"
            }
        )
        return {
            "llm": llm,
            "models": [
                serialize(profile, profile.id == active_id)
                for profile in profiles
            ],
        }

    def _find_locked(self, profile_id: Optional[str]) -> Optional[LLMProfile]:
        if profile_id is None:
            return None
        return next(
            (profile for profile in self._profiles if profile.id == profile_id),
            None,
        )


def build_runtime_llm(body: Dict[str, object]) -> OpenAICompatibleClient:
    """根据受信任预设或用户提供的兼容地址构造模型客户端。"""

    provider_id = body.get("provider")
    provider = next(
        (item for item in LLM_PROVIDER_CATALOG if item["id"] == provider_id),
        None,
    )
    if provider is None:
        raise ValueError("unknown LLM provider")
    model = body.get("model")
    api_key = body.get("api_key")
    if not isinstance(model, str) or not isinstance(api_key, str):
        raise ValueError("invalid LLM fields")
    base_url = body.get("base_url") if provider_id == "custom" else provider["base_url"]
    if not isinstance(base_url, str):
        raise ValueError("custom LLM base URL is required")
    return OpenAICompatibleClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        display_name=provider["name"],
    )
