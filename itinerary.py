"""解析多城市出差/旅行天气导出请求并生成有界查询计划。"""

from dataclasses import dataclass
from datetime import date, timedelta
import re
from typing import Optional, Tuple

from geocoding import CityResolution, CityResolver
from parser import SUPPORTED_CITIES, parse_query
from weather_client import WeatherClientError, WeatherProvider
from weather_export import WeatherSnapshot, build_travel_advice, weather_query_text


MAX_ITINERARY_CITIES = 5
MAX_ITINERARY_DAYS = 7
MAX_FORECAST_OFFSET = 7

_ORDER_RE = re.compile(r"依次|按(?:照)?顺序|先.+再")
_STAY_RE = re.compile(
    r"(?:每(?:个)?城市|每城)\s*(?:待|停留|住)\s*([一二两三四五六七八九十\d]+)\s*天"
)
_TOTAL_RE = re.compile(
    r"(?:出差|行程|旅行|旅程|总共|一共|共|未来)\s*(?:为|是)?\s*"
    r"([一二两三四五六七八九十\d]+)\s*天"
)
_ORIGIN_PATTERNS = (
    re.compile(
        r"(?:我)?(?:目前|现在)?(?:居住|住)在\s*"
        r"([\u3400-\u9fffA-Za-zÀ-ÖØ-öø-ÿ .'-]{2,40}?)"
        r"(?=，|,|。|；|;|还|并|$)"
    ),
    re.compile(
        r"从\s*([\u3400-\u9fffA-Za-zÀ-ÖØ-öø-ÿ .'-]{2,40}?)\s*出发"
    ),
)
_DESTINATION_END_RE = re.compile(
    r"天气|气温|温度|出差|行程|旅行|旅程|每(?:个)?城市|每城|结果|"
    r"还需要|出行需要|需要带"
)
_LOCATION_FILLER_RE = re.compile(
    r"^(?:(?:依次|按(?:照)?顺序)|请|帮我|替我|给我|查看|查询|查一下|"
    r"查查|看看|前往|目的地(?:是|为)?|去|到)+"
)


class ItineraryValidationError(ValueError):
    """行程已识别，但天数或目的地组合超出当前安全边界。"""


class ItineraryCityNotFoundError(ValueError):
    def __init__(self, location: str):
        super().__init__("itinerary city not found")
        self.location = location


@dataclass(frozen=True)
class ItineraryRequest:
    destinations: Tuple[str, ...]
    origin: Optional[str]
    ordered: bool
    total_days: int
    stay_days: Optional[int]
    start_offset: int = 1


@dataclass(frozen=True)
class ItineraryScheduleItem:
    location: str
    day_offset: int
    travel_day: int


def parse_itinerary_request(message: str) -> Optional[ItineraryRequest]:
    """返回行程语义；普通的同句天气导出仍交给既有查询流程。"""

    if not isinstance(message, str):
        return None
    cleaned = weather_query_text(message)
    ordered = bool(_ORDER_RE.search(cleaned))
    stay_match = _STAY_RE.search(cleaned)
    total_match = _TOTAL_RE.search(cleaned)
    if not ordered and stay_match is None and total_match is None:
        return None

    origin, destination_text = _extract_origin(cleaned)
    destinations = _extract_destinations(destination_text, origin)
    if not destinations:
        return None
    if len(destinations) > MAX_ITINERARY_CITIES:
        raise ItineraryValidationError("一次最多安排 5 个目的地。")

    stay_days = _parse_day_number(stay_match.group(1)) if stay_match else None
    explicit_total = _parse_day_number(total_match.group(1)) if total_match else None
    if stay_days is not None and explicit_total is not None:
        expected_total = stay_days * len(destinations)
        if explicit_total != expected_total:
            raise ItineraryValidationError(
                f"总行程 {explicit_total} 天与每城 {stay_days} 天不一致，"
                f"{len(destinations)} 个城市应为 {expected_total} 天。"
            )

    total_days = explicit_total or (stay_days or 1) * len(destinations)
    start_offset = 2 if re.search(r"后天\s*(?:开始|出发|启程)", cleaned) else 1
    if total_days < 1 or total_days > MAX_ITINERARY_DAYS:
        raise ItineraryValidationError("当前一次最多生成未来 7 天的行程天气。")
    if ordered and stay_days is None and total_days < len(destinations):
        raise ItineraryValidationError("按顺序安排行程时，每个目的地至少需要一天。")
    if start_offset + total_days - 1 > MAX_FORECAST_OFFSET:
        raise ItineraryValidationError("行程日期超出当前可查询的未来 7 天范围。")

    return ItineraryRequest(
        destinations=destinations,
        origin=origin,
        ordered=ordered,
        total_days=total_days,
        stay_days=stay_days,
        start_offset=start_offset,
    )


def build_itinerary_schedule(
    request: ItineraryRequest,
) -> Tuple[ItineraryScheduleItem, ...]:
    """有顺序时逐城分配日期；无顺序时生成“城市 × 行程日”矩阵。"""

    if not request.ordered:
        return tuple(
            ItineraryScheduleItem(location, day_offset, travel_day)
            for location in request.destinations
            for travel_day, day_offset in enumerate(
                range(
                    request.start_offset,
                    request.start_offset + request.total_days,
                ),
                start=1,
            )
        )

    if request.stay_days is not None:
        allocations = [request.stay_days] * len(request.destinations)
    else:
        base, remainder = divmod(request.total_days, len(request.destinations))
        if base == 0:
            raise ItineraryValidationError("行程天数不能少于目的地数量。")
        allocations = [
            base + (1 if index < remainder else 0)
            for index in range(len(request.destinations))
        ]

    schedule = []
    travel_day = 1
    for location, allocation in zip(request.destinations, allocations):
        for _ in range(allocation):
            schedule.append(
                ItineraryScheduleItem(
                    location=location,
                    day_offset=request.start_offset + travel_day - 1,
                    travel_day=travel_day,
                )
            )
            travel_day += 1
    return tuple(schedule)


def query_itinerary_weather(
    itinerary_request: ItineraryRequest,
    weather_client: WeatherProvider,
    resolver: CityResolver,
    provider_name: str,
):
    """执行有界预报计划，并返回逐行完整建议和已解析城市。"""

    resolutions = {}
    for location in itinerary_request.destinations:
        known_city = SUPPORTED_CITIES.get(location)
        resolution = (
            CityResolution(known_city)
            if known_city is not None
            else resolver.resolve(location)
        )
        if resolution is None:
            raise ItineraryCityNotFoundError(location)
        resolutions[location] = resolution

    schedule = build_itinerary_schedule(itinerary_request)
    forecast_by_key = {}
    range_getter = getattr(weather_client, "get_forecast_range", None)
    if callable(range_getter):
        for location in itinerary_request.destinations:
            offsets = tuple(
                item.day_offset for item in schedule if item.location == location
            )
            forecasts = tuple(range_getter(resolutions[location].city, offsets))
            if len(forecasts) != len(offsets):
                raise WeatherClientError("天气服务返回的行程日期数量不正确")
            forecast_by_key.update(
                ((location, offset), forecast)
                for offset, forecast in zip(offsets, forecasts)
            )
    else:
        for item in schedule:
            forecast_by_key[(item.location, item.day_offset)] = (
                weather_client.get_forecast(
                    resolutions[item.location].city, item.day_offset
                )
            )

    snapshots = []
    for item in schedule:
        weather = forecast_by_key[(item.location, item.day_offset)]
        snapshots.append(
            WeatherSnapshot(
                city=resolutions[item.location].city.name,
                date_label=_date_label(item.travel_day, item.day_offset),
                provider=provider_name,
                temperature_c=weather.temperature_c,
                condition=weather.condition,
                humidity_percent=weather.humidity_percent,
                wind_speed_mps=weather.wind_speed_mps,
                rain_expected=weather.rain_expected,
                advice=build_travel_advice(
                    weather.temperature_c,
                    weather.condition,
                    weather.humidity_percent,
                    weather.wind_speed_mps,
                    weather.rain_expected,
                ),
            )
        )
    return tuple(snapshots), tuple(
        resolutions[location].city for location in itinerary_request.destinations
    )


def _extract_origin(message: str):
    origin = None
    cleaned = message
    for pattern in _ORIGIN_PATTERNS:
        match = pattern.search(cleaned)
        if match and origin is None:
            origin = match.group(1).strip(" 的")
        cleaned = pattern.sub(" ", cleaned)
    return origin, cleaned


def _extract_destinations(message: str, origin: Optional[str]) -> Tuple[str, ...]:
    end_match = _DESTINATION_END_RE.search(message)
    candidate = message[: end_match.start()] if end_match else message
    parsed = parse_query(f"{candidate}天气")
    destinations = []
    for term in parsed.location_terms:
        normalized = _LOCATION_FILLER_RE.sub("", term).strip(" ，,、的")
        if not normalized or normalized == origin or normalized in destinations:
            continue
        destinations.append(normalized)
    return tuple(destinations[:MAX_ITINERARY_CITIES])


def _parse_day_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    numerals = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    return numerals.get(value, 0)


def _date_label(travel_day: int, day_offset: int) -> str:
    relative = {1: "明天", 2: "后天"}.get(day_offset, f"第{travel_day}天")
    target = date.today() + timedelta(days=day_offset)
    return f"{relative}（{target.isoformat()}）"
