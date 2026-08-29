from app import create_app
from config import Settings
from weather_client import WeatherData


class FakeWeatherClient:
    def get_current(self, _city):
        return WeatherData(22.0, "晴", 45, 2.0, False)

    def get_forecast(self, _city, _day_offset):
        return WeatherData(19.0, "雨", 80, 3.0, True)


def build_app():
    return create_app(
        settings=Settings(api_key="test-key"),
        weather_client=FakeWeatherClient(),
    )


def test_conversation_api_creates_lists_and_restores_chat_messages():
    http = build_app().test_client()

    created = http.post("/api/conversations")
    session_id = created.get_json()["conversation"]["id"]
    chat = http.post(
        "/chat",
        json={"message": "北京今天天气怎么样？", "session_id": session_id},
    )
    listing = http.get("/api/conversations")
    detail = http.get(f"/api/conversations/{session_id}")

    assert created.status_code == 201
    assert chat.status_code == 200
    assert listing.status_code == 200
    assert listing.get_json()["conversations"][0]["title"] == "北京今天天气怎么样？"
    assert listing.get_json()["conversations"][0]["message_count"] == 2
    assert detail.status_code == 200
    messages = detail.get_json()["conversation"]["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "北京今天天气怎么样？"
    assert messages[1]["payload"]["weather"]["temperature_c"] == 22.0
    assert messages[1]["payload"]["display_mode"] == "weather_cards"


def test_conversation_history_is_isolated_by_anonymous_browser_cookie():
    app = build_app()
    first_browser = app.test_client()
    second_browser = app.test_client()

    created = first_browser.post("/api/conversations")
    session_id = created.get_json()["conversation"]["id"]

    assert first_browser.get(f"/api/conversations/{session_id}").status_code == 200
    assert second_browser.get(f"/api/conversations/{session_id}").status_code == 404
    assert second_browser.get("/api/conversations").get_json() == {
        "conversations": []
    }


def test_cookie_less_chat_cannot_reuse_a_browser_managed_session():
    app = build_app()
    browser = app.test_client()
    session_id = browser.post("/api/conversations").get_json()["conversation"]["id"]
    api_client_without_cookies = app.test_client(use_cookies=False)

    response = api_client_without_cookies.post(
        "/chat", json={"message": "那明天呢？", "session_id": session_id}
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


def test_delete_conversation_is_idempotent_and_removes_history():
    http = build_app().test_client()
    session_id = http.post("/api/conversations").get_json()["conversation"]["id"]
    assert http.post(
        "/chat", json={"message": "深圳天气", "session_id": session_id}
    ).status_code == 200

    assert http.delete(f"/api/conversations/{session_id}").status_code == 204
    assert http.delete(f"/api/conversations/{session_id}").status_code == 204
    response = http.get(f"/api/conversations/{session_id}")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


def test_conversation_api_rejects_invalid_session_id():
    response = build_app().test_client().get("/api/conversations/bad$id")

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "INVALID_SESSION"


def test_anonymous_history_cookie_is_http_only_and_same_site():
    response = build_app().test_client().get("/api/conversations")
    cookie = response.headers["Set-Cookie"]

    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Path=/" in cookie
    assert response.headers["Cache-Control"] == "no-store"


def test_home_renders_accessible_conversation_history_controls():
    html = build_app().test_client().get("/").get_data(as_text=True)

    assert 'id="conversation-sidebar"' in html
    assert 'id="new-conversation-button"' in html
    assert 'id="conversation-list"' in html
    assert 'id="sidebar-toggle"' in html
    assert 'aria-controls="conversation-sidebar"' in html
    assert 'aria-expanded="false"' in html
    assert 'id="current-conversation-title"' in html
    assert "新建对话" in html
    assert "历史对话" in html
