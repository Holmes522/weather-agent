"""进程内对话状态和匿名历史；生产环境可替换为数据库或 Redis。"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Dict, Optional, Tuple

from parser import City
from weather_export import WeatherReportContext, WeatherSnapshot


@dataclass(frozen=True)
class ConversationMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ConversationContext:
    cities: Tuple[City, ...]
    day_offset: int = 0
    date_label: str = "今天"
    intent: str = "full"
    offered_full_weather: bool = False
    messages: Tuple[ConversationMessage, ...] = ()
    regional_scope: str = ""
    regional_phenomena: Tuple[str, ...] = ()
    weather_snapshots: Tuple[WeatherSnapshot, ...] = ()
    weather_report_context: Optional[WeatherReportContext] = None


@dataclass(frozen=True)
class DisplayMessage:
    role: str
    content: str
    payload: Optional[Dict[str, object]] = None


@dataclass(frozen=True)
class StoredConversation:
    owner_id: str
    session_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    messages: Tuple[DisplayMessage, ...] = ()


class InMemorySessionStore:
    def __init__(
        self,
        max_sessions: int = 10_000,
        max_messages: int = 100,
        max_conversations_per_owner: int = 100,
    ):
        self._contexts: Dict[str, ConversationContext] = {}
        self._conversations: Dict[str, StoredConversation] = {}
        self._lock = Lock()
        self._max_sessions = max(1, max_sessions)
        self._max_conversations_per_owner = max(1, max_conversations_per_owner)
        # Exchanges are stored as user/assistant pairs, so keep an even limit.
        self._max_messages = max(2, max_messages - (max_messages % 2))

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
            self._evict_if_needed(session_id)
            self._contexts[session_id] = context

    def create_conversation(
        self, owner_id: str, session_id: str
    ) -> StoredConversation:
        with self._lock:
            existing = self._conversations.get(session_id)
            if existing is not None:
                if existing.owner_id != owner_id:
                    raise ValueError("conversation id already exists")
                return self._copy_conversation(existing)
            self._evict_if_needed(session_id)
            self._evict_owner_if_needed(owner_id)
            now = datetime.now(timezone.utc)
            conversation = StoredConversation(
                owner_id=owner_id,
                session_id=session_id,
                title="新对话",
                created_at=now,
                updated_at=now,
            )
            self._conversations[session_id] = conversation
            return self._copy_conversation(conversation)

    def record_exchange(
        self,
        owner_id: str,
        session_id: str,
        user_message: str,
        assistant_message: str,
        payload: Dict[str, object],
    ) -> StoredConversation:
        with self._lock:
            existing = self._conversations.get(session_id)
            if existing is not None and existing.owner_id != owner_id:
                raise ValueError("conversation belongs to another owner")
            if existing is None:
                self._evict_if_needed(session_id)
                self._evict_owner_if_needed(owner_id)
                now = datetime.now(timezone.utc)
                existing = StoredConversation(
                    owner_id=owner_id,
                    session_id=session_id,
                    title="新对话",
                    created_at=now,
                    updated_at=now,
                )

            title = existing.title
            if not existing.messages:
                normalized = " ".join(user_message.split())
                title = normalized[:36] or "新对话"
            messages = (
                *existing.messages,
                DisplayMessage("user", user_message),
                DisplayMessage("assistant", assistant_message, deepcopy(payload)),
            )[-self._max_messages :]
            updated = StoredConversation(
                owner_id=existing.owner_id,
                session_id=existing.session_id,
                title=title,
                created_at=existing.created_at,
                updated_at=datetime.now(timezone.utc),
                messages=messages,
            )
            self._conversations[session_id] = updated
            return self._copy_conversation(updated)

    def list_conversations(self, owner_id: str) -> Tuple[StoredConversation, ...]:
        with self._lock:
            conversations = sorted(
                (
                    item
                    for item in self._conversations.values()
                    if item.owner_id == owner_id
                ),
                key=lambda item: item.updated_at,
                reverse=True,
            )
            return tuple(self._copy_conversation(item) for item in conversations)

    def get_conversation(
        self, owner_id: str, session_id: str
    ) -> Optional[StoredConversation]:
        with self._lock:
            conversation = self._conversations.get(session_id)
            if conversation is None or conversation.owner_id != owner_id:
                return None
            return self._copy_conversation(conversation)

    def has_managed_conversation(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._conversations

    def delete_conversation(self, owner_id: str, session_id: str) -> bool:
        with self._lock:
            conversation = self._conversations.get(session_id)
            if conversation is None or conversation.owner_id != owner_id:
                return False
            del self._conversations[session_id]
            self._contexts.pop(session_id, None)
            return True

    def _evict_if_needed(self, incoming_session_id: str) -> None:
        known_ids = set(self._contexts) | set(self._conversations)
        if incoming_session_id in known_ids or len(known_ids) < self._max_sessions:
            return
        victim = next(iter(self._conversations), None)
        if victim is None:
            victim = next(iter(self._contexts))
        self._conversations.pop(victim, None)
        self._contexts.pop(victim, None)

    def _evict_owner_if_needed(self, owner_id: str) -> None:
        owner_conversations = [
            item
            for item in self._conversations.values()
            if item.owner_id == owner_id
        ]
        if len(owner_conversations) < self._max_conversations_per_owner:
            return
        victim = min(owner_conversations, key=lambda item: item.updated_at)
        self._conversations.pop(victim.session_id, None)
        self._contexts.pop(victim.session_id, None)

    @staticmethod
    def _copy_conversation(conversation: StoredConversation) -> StoredConversation:
        return StoredConversation(
            owner_id=conversation.owner_id,
            session_id=conversation.session_id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            messages=tuple(
                DisplayMessage(message.role, message.content, deepcopy(message.payload))
                for message in conversation.messages
            ),
        )
