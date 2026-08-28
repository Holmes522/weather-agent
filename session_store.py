"""进程内对话状态；生产环境可替换为 Redis 等持久化实现。"""

from dataclasses import dataclass
from threading import Lock
from typing import Dict, Optional, Tuple

from parser import City


@dataclass(frozen=True)
class ConversationContext:
    cities: Tuple[City, ...]
    day_offset: int = 0
    date_label: str = "今天"
    intent: str = "full"
    offered_full_weather: bool = False


class InMemorySessionStore:
    def __init__(self, max_sessions: int = 10_000):
        self._contexts: Dict[str, ConversationContext] = {}
        self._lock = Lock()
        self._max_sessions = max_sessions

    def get_city(self, session_id: str) -> Optional[City]:
        with self._lock:
            context = self._contexts.get(session_id)
            return context.cities[0] if context and context.cities else None

    def set_city(self, session_id: str, city: City) -> None:
        self.set_context(session_id, ConversationContext((city,)))

    def get_context(self, session_id: str) -> Optional[ConversationContext]:
        with self._lock:
            return self._contexts.get(session_id)

    def set_context(self, session_id: str, context: ConversationContext) -> None:
        with self._lock:
            if (
                session_id not in self._contexts
                and len(self._contexts) >= self._max_sessions
            ):
                # MVP 的保守上限：淘汰一个最早插入的会话，避免无限增长。
                self._contexts.pop(next(iter(self._contexts)))
            self._contexts[session_id] = context
