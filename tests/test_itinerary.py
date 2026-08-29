import pytest

from itinerary import (
    ItineraryValidationError,
    build_itinerary_schedule,
    parse_itinerary_request,
)


def test_ordered_one_day_per_city_assigns_consecutive_forecast_days():
    request = parse_itinerary_request(
        "依次帮我查看，北京，深圳，广州，长沙，的天气，结果输出excel表，"
        "我目前居住在杭州，还需要告诉我出行需要带什么，每个城市待一天"
    )

    assert request is not None
    assert request.destinations == ("北京", "深圳", "广州", "长沙")
    assert request.origin == "杭州"
    assert request.ordered is True
    assert request.total_days == 4
    assert [(item.location, item.day_offset) for item in build_itinerary_schedule(request)] == [
        ("北京", 1),
        ("深圳", 2),
        ("广州", 3),
        ("长沙", 4),
    ]


def test_unordered_trip_builds_every_city_for_every_future_trip_day():
    request = parse_itinerary_request("北京和深圳出差3天，结果输出Excel")

    assert request is not None
    assert request.destinations == ("北京", "深圳")
    assert request.ordered is False
    assert request.total_days == 3
    assert [(item.location, item.day_offset) for item in build_itinerary_schedule(request)] == [
        ("北京", 1),
        ("北京", 2),
        ("北京", 3),
        ("深圳", 1),
        ("深圳", 2),
        ("深圳", 3),
    ]


def test_plain_weather_export_is_not_misclassified_as_an_itinerary():
    assert parse_itinerary_request("把深圳和广州明天天气导出为 PDF") is None


def test_ordered_trip_rejects_fewer_days_than_destinations():
    with pytest.raises(ItineraryValidationError):
        parse_itinerary_request("依次去北京和深圳出差1天，导出Excel")
