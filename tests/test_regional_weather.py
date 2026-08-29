from regional_weather import (
    RAIN,
    THUNDERSTORM,
    monitored_cities,
    parse_regional_weather_query,
)


def test_parses_national_thunderstorm_discovery_as_current_search():
    query = parse_regional_weather_query("告诉我现在哪里在打雷和下雨")

    assert query.scope == "中国"
    assert query.phenomena == (THUNDERSTORM,)


def test_parses_explicit_hunan_rain_search():
    query = parse_regional_weather_query("湖南省哪里在下雨")

    assert query.scope == "湖南"
    assert query.phenomena == (RAIN,)


def test_inherits_previous_phenomenon_for_province_follow_up():
    query = parse_regional_weather_query(
        "湖南省有哪些地方",
        previous_scope="中国",
        previous_phenomena=(THUNDERSTORM,),
    )

    assert query.scope == "湖南"
    assert query.phenomena == (THUNDERSTORM,)


def test_hunan_monitoring_catalog_covers_all_prefecture_centres():
    names = {city.name for city in monitored_cities("湖南")}

    assert len(names) == 14
    assert {"长沙", "岳阳", "张家界", "吉首"} <= names


def test_province_places_without_weather_context_is_not_hijacked():
    assert parse_regional_weather_query("湖南省有哪些地方") is None
