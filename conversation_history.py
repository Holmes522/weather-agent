"""匿名浏览器历史的 Cookie、REST 路由和聊天归档边界。"""

import re
from typing import Dict
from uuid import uuid4

from flask import Flask, g, jsonify, request

from session_store import InMemorySessionStore, StoredConversation


SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
ANONYMOUS_USER_PATTERN = re.compile(r"^[a-f0-9]{32}$")
ANONYMOUS_USER_COOKIE = "weather_agent_user"
ANONYMOUS_COOKIE_MAX_AGE = 365 * 24 * 60 * 60


def register_conversation_history(
    app: Flask, store: InMemorySessionStore, is_production: bool
) -> None:
    """为应用注册匿名身份、历史缓存策略和会话 CRUD 路由。"""

    @app.before_request
    def identify_anonymous_browser():
        cookie_value = request.cookies.get(ANONYMOUS_USER_COOKIE, "")
        g.has_anonymous_cookie = bool(
            ANONYMOUS_USER_PATTERN.fullmatch(cookie_value)
        )
        g.anonymous_user_id = (
            cookie_value if g.has_anonymous_cookie else uuid4().hex
        )

    @app.after_request
    def protect_anonymous_history(response):
        if request.path.startswith("/api/conversations"):
            response.headers["Cache-Control"] = "no-store"
        if not g.get("has_anonymous_cookie", False):
            response.set_cookie(
                ANONYMOUS_USER_COOKIE,
                g.anonymous_user_id,
                max_age=ANONYMOUS_COOKIE_MAX_AGE,
                secure=is_production,
                httponly=True,
                samesite="Lax",
                path="/",
            )
        return response

    @app.get("/api/conversations")
    def list_conversations():
        conversations = store.list_conversations(g.anonymous_user_id)
        return jsonify(
            {
                "conversations": [
                    _conversation_summary_payload(item) for item in conversations
                ]
            }
        )

    @app.post("/api/conversations")
    def create_conversation():
        conversation = store.create_conversation(
            g.anonymous_user_id, f"web-{uuid4()}"
        )
        return (
            jsonify(
                {"conversation": _conversation_detail_payload(conversation)}
            ),
            201,
        )

    @app.get("/api/conversations/<session_id>")
    def get_conversation(session_id: str):
        if not is_valid_session_id(session_id):
            return _invalid_session_response()
        conversation = store.get_conversation(g.anonymous_user_id, session_id)
        if conversation is None:
            return _error_response(
                "CONVERSATION_NOT_FOUND", "没有找到该对话。", 404
            )
        return jsonify(
            {"conversation": _conversation_detail_payload(conversation)}
        )

    @app.delete("/api/conversations/<session_id>")
    def delete_conversation(session_id: str):
        if not is_valid_session_id(session_id):
            return _invalid_session_response()
        store.delete_conversation(g.anonymous_user_id, session_id)
        return "", 204


def is_valid_session_id(session_id: str) -> bool:
    return bool(SESSION_ID_PATTERN.fullmatch(session_id))


def ensure_conversation_for_request(
    store: InMemorySessionStore, session_id: str
) -> bool:
    """绑定带历史 Cookie 的聊天；无 Cookie 的旧 API 调用保持原行为。"""

    if not g.has_anonymous_cookie:
        return not store.has_managed_conversation(session_id)
    try:
        store.create_conversation(g.anonymous_user_id, session_id)
        return True
    except ValueError:
        return False


def record_visible_exchange_for_request(
    store: InMemorySessionStore,
    session_id: str,
    user_message: str,
    response_payload: Dict[str, object],
) -> None:
    if not g.has_anonymous_cookie:
        return
    answer = response_payload.get("answer")
    if not isinstance(answer, str):
        return
    store.record_exchange(
        g.anonymous_user_id,
        session_id,
        user_message,
        answer,
        response_payload,
    )


def _conversation_summary_payload(conversation: StoredConversation):
    return {
        "id": conversation.session_id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
        "message_count": len(conversation.messages),
    }


def _conversation_detail_payload(conversation: StoredConversation):
    payload = _conversation_summary_payload(conversation)
    payload["messages"] = [
        {
            "role": message.role,
            "content": message.content,
            **({"payload": message.payload} if message.payload is not None else {}),
        }
        for message in conversation.messages
    ]
    return payload


def _invalid_session_response():
    return _error_response(
        "INVALID_SESSION",
        "session_id 只能包含字母、数字和 . _ : -。",
        422,
    )


def _error_response(code: str, message: str, status_code: int):
    return jsonify({"error": {"code": code, "message": message}}), status_code
