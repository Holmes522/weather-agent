"""进程内会话存储；生产环境可替换为 Redis 等持久化实现。"""

from threading import Lock
from typing import Dict, Optional

from parser import City


class InMemorySessionStore:
    def __init__(self, max_sessions: int = 10_000):
        self._cities: Dict[str, City] = {}
        self._lock = Lock()
        self._max_sessions = max_sessions

    def get_city(self, session_id: str) -> Optional[City]:
        with self._lock:
            return self._cities.get(session_id)

    def set_city(self, session_id: str, city: City) -> None:
        with self._lock:
            if session_id not in self._cities and len(self._cities) >= self._max_sessions:
                # MVP 的保守上限：淘汰一个最早插入的会话，避免无限增长。
                self._cities.pop(next(iter(self._cities)))
            self._cities[session_id] = city
