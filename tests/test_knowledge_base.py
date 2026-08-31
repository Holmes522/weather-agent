from pathlib import Path

import pytest

from knowledge_base import (
    KnowledgeBaseError,
    KnowledgeQueryError,
    WeatherKnowledgeBase,
    build_default_knowledge_base,
)


def write_document(
    directory: Path,
    filename: str,
    *,
    title: str,
    source_name: str,
    source_url: str,
    topics: str,
    body: str,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(
        "\n".join(
            [
                "---",
                f"title: {title}",
                f"source_name: {source_name}",
                f"source_url: {source_url}",
                f"topics: {topics}",
                "---",
                body,
            ]
        ),
        encoding="utf-8",
    )


def test_local_knowledge_base_retrieves_relevant_chinese_guidance(tmp_path):
    write_document(
        tmp_path,
        "thunderstorm.md",
        title="雷电天气户外安全",
        source_name="中国气象局",
        source_url="https://www.cma.gov.cn/safety/thunderstorm",
        topics="雷电,雷雨,打雷,爬山,露营,户外运动",
        body=(
            "# 雷电天气户外安全\n"
            "## 户外活动\n"
            "雷电来临时应停止爬山、骑行、露营和水上活动，尽快进入有防雷设施的建筑物。"
        ),
    )
    write_document(
        tmp_path,
        "heat.md",
        title="高温中暑预防",
        source_name="国家卫生健康委员会",
        source_url="https://www.nhc.gov.cn/health/heat",
        topics="高温,炎热,中暑,补水,跑步",
        body="# 高温中暑预防\n## 户外活动\n高温时减少户外锻炼并及时补水。",
    )
    knowledge_base = WeatherKnowledgeBase.from_directory(tmp_path)

    results = knowledge_base.search("外面打雷了还能爬山吗？", limit=2)

    assert results
    assert results[0].title == "雷电天气户外安全"
    assert results[0].section == "户外活动"
    assert "停止爬山" in results[0].content
    assert results[0].source_url.startswith("https://www.cma.gov.cn/")
    assert 0.0 < results[0].score <= 1.0


def test_unrelated_query_returns_no_knowledge(tmp_path):
    write_document(
        tmp_path,
        "rain.md",
        title="暴雨出行安全",
        source_name="应急管理部",
        source_url="https://www.mem.gov.cn/safety/rain",
        topics="暴雨,积水,洪涝,出行",
        body="# 暴雨出行安全\n## 涉水风险\n不要盲目通过积水路段。",
    )
    knowledge_base = WeatherKnowledgeBase.from_directory(tmp_path)

    assert knowledge_base.search("请解释 Python 装饰器的闭包原理") == ()


@pytest.mark.parametrize(
    "source_url",
    [
        "http://www.cma.gov.cn/unsafe",
        "https://example.com/not-official",
        "file:///C:/secret.txt",
    ],
)
def test_knowledge_documents_require_official_https_sources(tmp_path, source_url):
    write_document(
        tmp_path,
        "unsafe.md",
        title="不安全资料",
        source_name="未知来源",
        source_url=source_url,
        topics="天气",
        body="# 不安全资料\n## 内容\n不要加载这个文档。",
    )

    with pytest.raises(KnowledgeBaseError):
        WeatherKnowledgeBase.from_directory(tmp_path)


def test_knowledge_query_and_limit_are_bounded(tmp_path):
    write_document(
        tmp_path,
        "wind.md",
        title="大风安全",
        source_name="应急管理部",
        source_url="https://www.mem.gov.cn/safety/wind",
        topics="大风,刮风,户外",
        body="# 大风安全\n## 出行\n大风时减少户外活动。",
    )
    knowledge_base = WeatherKnowledgeBase.from_directory(tmp_path)

    with pytest.raises(KnowledgeQueryError):
        knowledge_base.search("风" * 201)
    with pytest.raises(KnowledgeQueryError):
        knowledge_base.search("大风怎么办", limit=4)


@pytest.mark.parametrize(
    ("query", "expected_title"),
    [
        ("雷雨天还能露营吗", "雷电天气户外安全指南"),
        ("暴雨积水开车要注意什么", "暴雨洪涝出行安全指南"),
        ("天气太热跑步怎么防中暑", "高温天气健康防护指南"),
        ("寒潮天应该怎么穿衣服", "寒潮与低温出行防护指南"),
        ("风很大还能在户外活动吗", "大风天气安全指南"),
    ],
)
def test_bundled_knowledge_base_covers_common_weather_safety_queries(
    query, expected_title
):
    results = build_default_knowledge_base().search(query)

    assert results
    assert results[0].title == expected_title
    assert {result.title for result in results} == {expected_title}
