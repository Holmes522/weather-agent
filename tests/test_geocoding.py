import requests

import pytest

from geocoding import GeocodingError, NominatimCityResolver


class FakeResponse:
    def __init__(self, payload, status_error=None):
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        return self.payload


def city_payload(name="纽约", country_code="us", latitude="40.7127", longitude="-74.0060"):
    return [
        {
            "name": name,
            "lat": latitude,
            "lon": longitude,
            "addresstype": "city",
            "importance": 0.88,
            "address": {"city": name, "country_code": country_code},
        }
    ]


def test_resolves_any_city_with_nominatim_and_validates_coordinates():
    calls = []

    def fake_get(**kwargs):
        calls.append(kwargs)
        return FakeResponse(city_payload())

    resolver = NominatimCityResolver(request_get=fake_get, min_interval_seconds=0)
    resolution = resolver.resolve("纽约")

    assert resolution.city.name == "纽约"
    assert resolution.city.latitude == pytest.approx(40.7127)
    assert resolution.city.longitude == pytest.approx(-74.0060)
    assert resolution.city.country_code == "US"
    assert resolution.corrected_from is None
    assert calls[0]["params"]["q"] == "纽约"
    assert calls[0]["params"]["featureType"] == "settlement"
    assert "weather-agent" in calls[0]["headers"]["User-Agent"]


def test_corrects_confirmed_alias_before_geocoding():
    queries = []

    def fake_get(**kwargs):
        queries.append(kwargs["params"]["q"])
        return FakeResponse(city_payload(name="大理市", country_code="cn", latitude="25.59", longitude="100.24"))

    resolver = NominatimCityResolver(request_get=fake_get, min_interval_seconds=0)
    resolution = resolver.resolve("大利")

    assert resolution.city.name == "大理"
    assert resolution.corrected_from == "大利"
    assert queries == ["大理"]


def test_reuses_cached_resolution_without_calling_upstream_twice():
    call_count = 0

    def fake_get(**_kwargs):
        nonlocal call_count
        call_count += 1
        return FakeResponse(city_payload())

    resolver = NominatimCityResolver(request_get=fake_get, min_interval_seconds=0)

    assert resolver.resolve("纽约") == resolver.resolve("纽约")
    assert call_count == 1


def test_unknown_city_returns_none_instead_of_previous_session_city():
    resolver = NominatimCityResolver(
        request_get=lambda **_kwargs: FakeResponse([]),
        min_interval_seconds=0,
    )

    assert resolver.resolve("不存在城") is None


@pytest.mark.parametrize("payload", [{}, [{"name": "坏数据", "lat": "nan", "lon": "x"}]])
def test_rejects_invalid_geocoding_payload(payload):
    resolver = NominatimCityResolver(
        request_get=lambda **_kwargs: FakeResponse(payload),
        min_interval_seconds=0,
    )

    with pytest.raises(GeocodingError):
        resolver.resolve("坏数据")


def test_hides_network_errors_behind_geocoding_error():
    response = FakeResponse([], status_error=requests.HTTPError("upstream secret"))
    resolver = NominatimCityResolver(
        request_get=lambda **_kwargs: response,
        min_interval_seconds=0,
    )

    with pytest.raises(GeocodingError):
        resolver.resolve("纽约")
