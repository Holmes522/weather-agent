from parser import City
from session_store import ConversationContext, InMemorySessionStore


def test_records_exchange_and_uses_first_message_as_bounded_title():
    store = InMemorySessionStore(max_messages=8)
    store.create_conversation("owner-a", "conversation-a")

    store.record_exchange(
        "owner-a",
        "conversation-a",
        "  深圳明天适合跑步吗？  还需要看看降雨概率  ",
        "明天有雨，建议室内运动。",
        {"answer": "明天有雨，建议室内运动。", "display_mode": "text"},
    )

    conversation = store.get_conversation("owner-a", "conversation-a")
    assert conversation is not None
    assert conversation.title == "深圳明天适合跑步吗？ 还需要看看降雨概率"
    assert len(conversation.title) <= 36
    assert [message.role for message in conversation.messages] == [
        "user",
        "assistant",
    ]
    assert conversation.messages[1].payload["display_mode"] == "text"


def test_history_is_owner_scoped_sorted_and_payload_is_copied():
    store = InMemorySessionStore(max_messages=8)
    payload = {"answer": "北京晴", "weather": {"temperature_c": 20.0}}
    store.create_conversation("owner-a", "older")
    store.record_exchange("owner-a", "older", "北京天气", "北京晴", payload)
    store.create_conversation("owner-b", "private")
    store.create_conversation("owner-a", "newer")

    payload["weather"]["temperature_c"] = -99
    summaries = store.list_conversations("owner-a")
    conversation = store.get_conversation("owner-a", "older")

    assert [summary.session_id for summary in summaries] == ["newer", "older"]
    assert store.get_conversation("owner-a", "private") is None
    assert conversation.messages[1].payload["weather"]["temperature_c"] == 20.0


def test_message_limit_keeps_complete_recent_exchanges():
    store = InMemorySessionStore(max_messages=4)
    store.create_conversation("owner-a", "bounded")

    for index in range(3):
        store.record_exchange(
            "owner-a",
            "bounded",
            f"问题 {index}",
            f"回答 {index}",
            {"answer": f"回答 {index}"},
        )

    conversation = store.get_conversation("owner-a", "bounded")
    assert [message.content for message in conversation.messages] == [
        "问题 1",
        "回答 1",
        "问题 2",
        "回答 2",
    ]


def test_delete_conversation_also_removes_weather_context():
    store = InMemorySessionStore()
    store.create_conversation("owner-a", "delete-me")
    store.set_context(
        "delete-me",
        ConversationContext((City("深圳", 22.54, 114.06),)),
    )

    assert store.delete_conversation("owner-a", "delete-me") is True
    assert store.get_conversation("owner-a", "delete-me") is None
    assert store.get_context("delete-me") is None
    assert store.delete_conversation("owner-a", "delete-me") is False
