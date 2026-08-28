from parser import parse_query


def test_parse_city_and_today():
    result = parse_query("北京今天天气怎么样？")

    assert result.city.name == "北京"
    assert result.day_offset == 0
    assert result.date_label == "今天"
    assert result.location_terms == ("北京",)


def test_parse_multiple_cities_in_text_order():
    result = parse_query("深圳和广州明天天气什么样")

    assert result.location_terms == ("深圳", "广州")
    assert result.day_offset == 1


def test_parse_tomorrow_without_city_for_follow_up_question():
    result = parse_query("那后天呢？")

    assert result.city is None
    assert result.day_offset == 2
    assert result.date_label == "后天"


def test_unknown_city_is_not_accepted():
    result = parse_query("纽约明天会下雨吗？")

    assert result.city is None
    assert result.location_terms == ("纽约",)
    assert result.day_offset == 1
    assert result.date_label == "明天"


def test_follow_up_without_city_has_no_location_terms():
    result = parse_query("那后天呢？")

    assert result.location_terms == ()


def test_extracts_misspelled_city_as_location_term_for_resolution():
    result = parse_query("大利天气如何")

    assert result.city is None
    assert result.location_terms == ("大利",)


def test_limits_a_single_message_to_five_cities():
    result = parse_query("北京、上海、广州、深圳、成都、杭州明天天气")

    assert result.location_terms == ("北京", "上海", "广州", "深圳", "成都")


def test_missing_date_defaults_to_today():
    result = parse_query("上海天气")

    assert result.city.name == "上海"
    assert result.day_offset == 0
    assert result.date_label == "今天"
