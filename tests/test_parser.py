from parser import parse_query


def test_parse_city_and_today():
    result = parse_query("北京今天天气怎么样？")

    assert result.city.name == "北京"
    assert result.day_offset == 0
    assert result.date_label == "今天"


def test_parse_tomorrow_without_city_for_follow_up_question():
    result = parse_query("那后天呢？")

    assert result.city is None
    assert result.day_offset == 2
    assert result.date_label == "后天"


def test_unknown_city_is_not_accepted():
    result = parse_query("纽约明天会下雨吗？")

    assert result.city is None
    assert result.day_offset == 1
    assert result.date_label == "明天"


def test_missing_date_defaults_to_today():
    result = parse_query("上海天气")

    assert result.city.name == "上海"
    assert result.day_offset == 0
    assert result.date_label == "今天"
