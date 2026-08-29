"""天气导出的聊天响应组装；隔离 Flask 路由与文件生成细节。"""

from typing import Optional, Sequence

from export_store import InMemoryExportStore
from weather_export import (
    WeatherReportContext,
    WeatherSnapshot,
    build_weather_document,
)


def snapshots_from_results(results, provider_name: str):
    snapshots = []
    for result in results:
        if not isinstance(result, dict) or not isinstance(result.get("weather"), dict):
            continue
        weather = result["weather"]
        snapshots.append(
            WeatherSnapshot(
                city=str(result.get("city", "")),
                date_label=str(result.get("date", "")),
                provider=provider_name,
                temperature_c=float(weather["temperature_c"]),
                condition=str(weather["condition"]),
                humidity_percent=int(weather["humidity_percent"]),
                wind_speed_mps=float(weather["wind_speed_mps"]),
                rain_expected=bool(weather["rain_expected"]),
                advice=weather.get("advice"),
            )
        )
    return tuple(snapshots[:35])


def export_prompt_payload(session_id: str, answer: str):
    return {
        "session_id": session_id,
        "intent": "weather_export",
        "display_mode": "text",
        "answer": answer,
    }


def create_export_payload(
    session_id: str,
    snapshots: Sequence[WeatherSnapshot],
    format_name: str,
    export_store: InMemoryExportStore,
    report_context: Optional[WeatherReportContext] = None,
):
    artifact = build_weather_document(snapshots, format_name, report_context)
    export_id = export_store.put(session_id, artifact)
    format_labels = {"docx": "Word", "xlsx": "Excel", "pdf": "PDF", "md": "Markdown"}
    return {
        "session_id": session_id,
        "intent": "weather_export",
        "display_mode": "text",
        "answer": (
            f"已按 {report_context.total_days} 天行程生成 "
            f"{format_labels[format_name]} 天气报告，点击下方按钮下载。"
            if report_context and report_context.total_days
            else f"已生成 {format_labels[format_name]} 天气报告，点击下方按钮下载。"
        ),
        "export": {
            "id": export_id,
            "format": format_name,
            "filename": artifact.filename,
            "download_url": f"/api/exports/{export_id}",
        },
    }
