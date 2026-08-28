from app import create_app
from config import Settings
from weather_client import WeatherData


class FakeWeatherClient:
    def get_current(self, city):
        return WeatherData(22.0, "晴", 50, 2.0, False)

    def get_forecast(self, city, day_offset):
        return WeatherData(20.0, "阴", 60, 3.0, False)


def create_local_app():
    return create_app(
        settings=Settings(default_provider="openmeteo"),
        weather_clients={"openmeteo": FakeWeatherClient()},
        default_provider="openmeteo",
    )


def test_settings_page_renders_provider_configuration_form():
    response = create_local_app().test_client().get("/settings")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="provider-config-form"' in html
    assert 'id="provider-type"' in html
    assert 'id="provider-api-key"' in html
    assert 'id="qweather-api-host"' in html
    assert '/static/settings.js' in html


def test_provider_status_exposes_configuration_state_but_not_credentials():
    app = create_local_app()

    response = app.test_client().get("/api/providers")

    assert response.status_code == 200
    body = response.get_json()
    assert body["providers"] == [
        {
            "id": "openmeteo",
            "name": "Open-Meteo",
            "configured": True,
            "required_fields": [],
        },
        {
            "id": "openweather",
            "name": "OpenWeather",
            "configured": False,
            "required_fields": ["api_key"],
        },
        {
            "id": "qweather",
            "name": "和风天气",
            "configured": False,
            "required_fields": ["api_key", "api_host"],
        },
        {
            "id": "weatherapi",
            "name": "WeatherAPI.com",
            "configured": False,
            "required_fields": ["api_key"],
        },
        {
            "id": "visualcrossing",
            "name": "Visual Crossing",
            "configured": False,
            "required_fields": ["api_key"],
        },
    ]
    assert "runtime-secret-key" not in response.get_data(as_text=True)


def test_runtime_openweather_configuration_adds_provider_without_returning_key():
    app = create_local_app()
    http = app.test_client()

    response = http.post(
        "/api/providers",
        json={"provider": "openweather", "api_key": "runtime-secret-key"},
    )

    assert response.status_code == 201
    assert response.get_json() == {
        "provider": {
            "id": "openweather",
            "name": "OpenWeather",
            "configured": True,
        }
    }
    assert "runtime-secret-key" not in response.get_data(as_text=True)
    assert '<option value="openweather">OpenWeather</option>' in http.get(
        "/"
    ).get_data(as_text=True)


def test_runtime_qweather_configuration_rejects_invalid_host():
    response = create_local_app().test_client().post(
        "/api/providers",
        json={
            "provider": "qweather",
            "api_key": "runtime-secret-key",
            "api_host": "https://console.qweather.com/project/example",
        },
    )

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "INVALID_PROVIDER_CONFIG"
    assert "runtime-secret-key" not in response.get_data(as_text=True)


def test_runtime_weatherapi_configuration_adds_common_provider():
    app = create_local_app()
    http = app.test_client()

    response = http.post(
        "/api/providers",
        json={"provider": "weatherapi", "api_key": "runtime-secret-key"},
    )

    assert response.status_code == 201
    assert response.get_json()["provider"] == {
        "id": "weatherapi",
        "name": "WeatherAPI.com",
        "configured": True,
    }
    assert "runtime-secret-key" not in response.get_data(as_text=True)


def test_runtime_configuration_rejects_missing_api_key():
    response = create_local_app().test_client().post(
        "/api/providers",
        json={"provider": "openweather", "api_key": " "},
    )

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "INVALID_PROVIDER_CONFIG"


def test_provider_configuration_is_blocked_for_non_local_clients():
    app = create_local_app()
    http = app.test_client()

    response = http.post(
        "/api/providers",
        json={"provider": "openweather", "api_key": "runtime-secret-key"},
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "LOCAL_ACCESS_REQUIRED"
    providers = http.get("/api/providers").get_json()["providers"]
    openweather = next(item for item in providers if item["id"] == "openweather")
    assert openweather["configured"] is False


def test_provider_settings_page_is_blocked_for_non_local_clients():
    response = create_local_app().test_client().get(
        "/settings",
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "LOCAL_ACCESS_REQUIRED"
