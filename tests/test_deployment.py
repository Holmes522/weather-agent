import importlib
import sys


def test_wsgi_entrypoint_loads_free_openmeteo_configuration(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WEATHER_PROVIDER", "openmeteo")
    sys.modules.pop("wsgi", None)

    wsgi = importlib.import_module("wsgi")

    response = wsgi.app.test_client().get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
