from io import BytesIO

from openpyxl import load_workbook

from app import create_app
from config import Settings
from weather_client import WeatherData


class FakeWeatherClient:
    def get_current(self, city):
        return WeatherData(22.0, "晴", 50, 2.0, False)

    def get_forecast(self, city, day_offset):
        return WeatherData(25.0, "雨", 80, 3.0, True)


def local_app():
    return create_app(settings=Settings(), weather_client=FakeWeatherClient())


def test_follow_up_exports_last_weather_result_as_download():
    http = local_app().test_client()
    http.post(
        "/chat",
        json={"message": "深圳明天天气怎么样", "session_id": "export-follow-up"},
    )

    response = http.post(
        "/chat",
        json={"message": "把刚才天气导出为 Excel", "session_id": "export-follow-up"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["intent"] == "weather_export"
    assert body["export"]["format"] == "xlsx"
    download = http.get(body["export"]["download_url"])
    assert download.status_code == 200
    assert download.headers["Cache-Control"] == "no-store"
    assert "attachment" in download.headers["Content-Disposition"]
    workbook = load_workbook(BytesIO(download.data))
    assert workbook.active["A2"].value == "深圳"


def test_query_and_export_can_happen_in_one_message():
    http = local_app().test_client()

    response = http.post(
        "/chat",
        json={"message": "把深圳和广州明天天气导出为 PDF", "session_id": "export-inline"},
    )

    body = response.get_json()
    assert response.status_code == 200
    assert body["cities"] == ["深圳", "广州"]
    assert body["export"]["format"] == "pdf"
    assert http.get(body["export"]["download_url"]).data.startswith(b"%PDF")


def test_export_without_format_asks_for_format():
    http = local_app().test_client()
    http.post(
        "/chat",
        json={"message": "北京今天天气", "session_id": "export-no-format"},
    )

    response = http.post(
        "/chat",
        json={"message": "把它导出来", "session_id": "export-no-format"},
    )

    assert response.status_code == 200
    assert "Word、Excel、PDF 或 Markdown" in response.get_json()["answer"]


def test_export_without_weather_snapshot_does_not_invent_data():
    response = local_app().test_client().post(
        "/chat",
        json={"message": "导出为 PDF", "session_id": "export-empty"},
    )

    assert response.status_code == 200
    assert "先查询天气" in response.get_json()["answer"]


def test_unknown_export_id_returns_404():
    response = local_app().test_client().get("/api/exports/not-a-real-id")

    assert response.status_code == 404
