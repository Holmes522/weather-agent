"""有界、带过期时间的进程内导出文件存储。"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Callable, Dict, Optional
from uuid import uuid4

from weather_export import WeatherArtifact


@dataclass(frozen=True)
class _StoredArtifact:
    session_id: str
    artifact: WeatherArtifact
    expires_at: datetime


class InMemoryExportStore:
    def __init__(
        self,
        ttl_seconds: int = 3600,
        max_items: int = 1000,
        max_items_per_session: int = 20,
        max_file_bytes: int = 2 * 1024 * 1024,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        if min(ttl_seconds, max_items, max_items_per_session, max_file_bytes) < 1:
            raise ValueError("export store limits must be positive")
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_items = max_items
        self._max_items_per_session = max_items_per_session
        self._max_file_bytes = max_file_bytes
        self._clock = clock
        self._items: Dict[str, _StoredArtifact] = {}
        self._lock = Lock()

    def put(self, session_id: str, artifact: WeatherArtifact) -> str:
        if len(artifact.content) > self._max_file_bytes:
            raise ValueError("export file is too large")
        now = self._clock()
        with self._lock:
            self._purge_locked(now)
            owned = [
                (export_id, item)
                for export_id, item in self._items.items()
                if item.session_id == session_id
            ]
            while len(owned) >= self._max_items_per_session:
                victim_id, _ = min(owned, key=lambda pair: pair[1].expires_at)
                self._items.pop(victim_id, None)
                owned = [pair for pair in owned if pair[0] != victim_id]
            while len(self._items) >= self._max_items:
                victim_id = min(self._items, key=lambda key: self._items[key].expires_at)
                self._items.pop(victim_id, None)
            export_id = uuid4().hex
            self._items[export_id] = _StoredArtifact(
                session_id, artifact, now + self._ttl
            )
            return export_id

    def get(
        self, export_id: str, session_id: Optional[str] = None
    ) -> Optional[WeatherArtifact]:
        now = self._clock()
        with self._lock:
            self._purge_locked(now)
            item = self._items.get(export_id)
            if item is None or (
                session_id is not None and item.session_id != session_id
            ):
                return None
            return item.artifact

    def _purge_locked(self, now: datetime) -> None:
        expired = [
            export_id
            for export_id, item in self._items.items()
            if item.expires_at <= now
        ]
        for export_id in expired:
            self._items.pop(export_id, None)
