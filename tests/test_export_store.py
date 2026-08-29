from datetime import datetime, timedelta, timezone

from export_store import InMemoryExportStore
from weather_export import WeatherArtifact


def artifact(name="report.md"):
    return WeatherArtifact(name, "text/markdown; charset=utf-8", b"weather")


def test_export_store_uses_unpredictable_ids_and_scopes_to_session():
    store = InMemoryExportStore(ttl_seconds=60)

    first = store.put("session-a", artifact())
    second = store.put("session-a", artifact())

    assert first != second
    assert len(first) >= 32
    assert store.get(first).filename == "report.md"
    assert store.get(first, session_id="session-b") is None


def test_export_store_removes_expired_artifacts():
    now = datetime(2026, 8, 29, tzinfo=timezone.utc)
    store = InMemoryExportStore(ttl_seconds=30, clock=lambda: now)
    export_id = store.put("session-a", artifact())
    store._clock = lambda: now + timedelta(seconds=31)

    assert store.get(export_id) is None


def test_export_store_rejects_oversized_files():
    store = InMemoryExportStore(max_file_bytes=4)

    try:
        store.put("session-a", artifact())
    except ValueError as error:
        assert "too large" in str(error)
    else:
        raise AssertionError("oversized export should be rejected")
