"""中文天气问题的最小规则解析器。"""

from dataclasses import dataclass
import re
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class City:
    """允许查询的城市及各天气 Provider 共用的经纬度。"""

    name: str
    latitude: float
    longitude: float
    country_code: str = "CN"


# MVP 使用白名单和坐标，避免把任意用户输入直接交给上游地理编码器。
SUPPORTED_CITIES: Dict[str, City] = {
    "北京": City("北京", 39.9042, 116.4074),
    "上海": City("上海", 31.2304, 121.4737),
    "广州": City("广州", 23.1291, 113.2644),
    "深圳": City("深圳", 22.5431, 114.0579),
    "成都": City("成都", 30.5728, 104.0668),
    "杭州": City("杭州", 30.2741, 120.1551),
    "南京": City("南京", 32.0603, 118.7969),
    "武汉": City("武汉", 30.5928, 114.3055),
    "西安": City("西安", 34.3416, 108.9398),
    "重庆": City("重庆", 29.5630, 106.5516),
    "天津": City("天津", 39.3434, 117.3616),
    "香港": City("香港", 22.3193, 114.1694, "HK"),
    "澳门": City("澳门", 22.1987, 113.5439, "MO"),
}


@dataclass(frozen=True)
class ParsedQuery:
    city: Optional[City]
    day_offset: int
    date_label: str
    location_terms: Tuple[str, ...] = ()


_TIME_PATTERNS = (("后天", 2), ("明天", 1), ("今天", 0))
_CITY_PATTERN = re.compile(
    "|".join(re.escape(city_name) for city_name in sorted(SUPPORTED_CITIES, key=len, reverse=True))
)
_DATE_PATTERN = re.compile("|".join(label for label, _offset in _TIME_PATTERNS))
_LOCATION_END_PATTERN = re.compile(
    r"天气|气温|温度|湿度|风速|风大|刮风|下雨|降雨|有雨|"
    r"出门|带伞|雨伞|带什么|穿什么|穿衣"
)
_LOCATION_SEPARATOR_PATTERN = re.compile(r"(?:和|与|及|、|，|,|/|；|;)" )
_LEADING_FILLER_PATTERN = re.compile(
    r"^(?:请问|麻烦|帮我|替我|给我|我想知道|我想问|想知道|"
    r"查询|查一下|查查|看看|比较一下|比较|那|我在|在)+"
)
_TRAILING_FILLER_PATTERN = re.compile(r"(?:会不会|是否|会|可能|的|呢|吗|如何|怎么样|什么样)+$")
_VALID_LOCATION_PATTERN = re.compile(r"^[\u3400-\u9fffA-Za-zÀ-ÖØ-öø-ÿ .'-]{2,40}$")


def parse_query(message: str) -> ParsedQuery:
    """从中文消息中提取一个或多个地点和相对日期。"""

    location_terms = _extract_location_terms(message)
    city = next(
        (SUPPORTED_CITIES[term] for term in location_terms if term in SUPPORTED_CITIES),
        None,
    )

    for date_label, day_offset in _TIME_PATTERNS:
        if date_label in message:
            return ParsedQuery(city, day_offset, date_label, location_terms)

    return ParsedQuery(city, 0, "今天", location_terms)


def _extract_location_terms(message: str) -> Tuple[str, ...]:
    """提取天气问题中的地点片段；地点是否合法由地理编码边界确认。"""

    text = _DATE_PATTERN.sub("", message.strip())
    text = re.sub(r"(?:会不会|是否|可能会|会)", "", text)
    end_match = _LOCATION_END_PATTERN.search(text)
    candidate_text = text[: end_match.start()] if end_match else text
    candidate_text = candidate_text.strip(" \t\r\n？?！!。.")
    candidate_text = _LEADING_FILLER_PATTERN.sub("", candidate_text)
    candidate_text = _TRAILING_FILLER_PATTERN.sub("", candidate_text)

    terms = []
    for raw_term in _LOCATION_SEPARATOR_PATTERN.split(candidate_text):
        term = raw_term.strip(" \t\r\n？?！!。.的")
        term = _LEADING_FILLER_PATTERN.sub("", term)
        term = _TRAILING_FILLER_PATTERN.sub("", term)
        if term.endswith("市") and term[:-1] in SUPPORTED_CITIES:
            term = term[:-1]
        if not term or not _VALID_LOCATION_PATTERN.fullmatch(term):
            continue
        if term not in terms:
            terms.append(term)
        if len(terms) == 5:
            break

    if terms:
        return tuple(terms)

    # 兼容措辞较复杂但仍包含白名单城市的旧查询。
    known_matches = [match.group(0) for match in _CITY_PATTERN.finditer(message)]
    return tuple(dict.fromkeys(known_matches[:5]))
