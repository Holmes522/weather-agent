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
    date_is_explicit: bool = False


_TIME_PATTERNS = (
    (r"\bday\s+after\s+tomorrow\b", 2, "后天"),
    ("后天", 2, "后天"),
    (r"\btomorrow\b", 1, "明天"),
    ("明天", 1, "明天"),
    (r"\btoday\b", 0, "今天"),
    ("今天", 0, "今天"),
)
_CITY_PATTERN = re.compile(
    "|".join(re.escape(city_name) for city_name in sorted(SUPPORTED_CITIES, key=len, reverse=True))
)
_DATE_PATTERN = re.compile(
    "|".join(f"(?:{pattern})" for pattern, _offset, _label in _TIME_PATTERNS),
    re.IGNORECASE,
)
_LOCATION_END_PATTERN = re.compile(
    r"天气|气温|温度|湿度|风速|风大|刮风|下雨|降雨|有雨|"
    r"出门|带伞|雨伞|带什么|穿什么|穿衣|适合|跑步|户外|运动"
)
_LOCATION_SEPARATOR_PATTERN = re.compile(r"(?:和|与|及|、|，|,|/|；|;)")
_LEADING_FILLER_PATTERN = re.compile(
    r"^(?:请问|麻烦|帮我|替我|给我|我想知道|我想问|想知道|"
    r"查询|查一下|查查|看看|比较一下|比较|那|我在|在)+"
)
_TRAILING_FILLER_PATTERN = re.compile(
    r"(?:会不会|是否|会|可能|的|呢|吗|如何|怎么样|什么样)+$"
)
_VALID_LOCATION_PATTERN = re.compile(r"^[\u3400-\u9fffA-Za-zÀ-ÖØ-öø-ÿ .'-]{2,40}$")
_QUALIFIED_LOCATION_PATTERN = re.compile(
    r"^[\u3400-\u9fffA-Za-zÀ-ÖØ-öø-ÿ .'-]{2,40},\s*"
    r"[\u3400-\u9fffA-Za-zÀ-ÖØ-öø-ÿ .'-]{2,40}$"
)
_ENGLISH_LOCATION_PATTERNS = (
    re.compile(
        r"^(?:what(?:'s| is)|how(?:'s| is))\s+(?:the\s+)?weather\s+"
        r"(?:like\s+)?(?:in|for)\s+(.+?)\s*[?!.]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:weather|temperature|humidity|wind|rain)\s+(?:in|for)\s+"
        r"(.+?)\s*[?!.]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(.+?)\s+(?:weather|temperature|humidity|wind|rain)\s*[?!.]*$",
        re.IGNORECASE,
    ),
    re.compile(r"^will\s+it\s+rain\s+in\s+(.+?)\s*[?!.]*$", re.IGNORECASE),
)
_CONTEXT_ONLY_PATTERN = re.compile(
    r"^(?:需要|要|可以|好|好的|行|告诉我|请告诉我|看看|想看)[。！!？?]*$"
)
_REGIONAL_DISCOVERY_PATTERN = re.compile(r"哪里|哪些地方|哪些城市|什么地方|有哪些地方")
_REGIONAL_WEATHER_PATTERN = re.compile(r"打雷|雷雨|雷暴|雷电|下雨|降雨|有雨")


def parse_query(message: str) -> ParsedQuery:
    """从中文消息中提取一个或多个地点和相对日期。"""

    location_terms = _extract_location_terms(message)
    city = next(
        (SUPPORTED_CITIES[term] for term in location_terms if term in SUPPORTED_CITIES),
        None,
    )

    for time_pattern, day_offset, date_label in _TIME_PATTERNS:
        if re.search(time_pattern, message, re.IGNORECASE):
            return ParsedQuery(city, day_offset, date_label, location_terms, True)

    return ParsedQuery(city, 0, "今天", location_terms, False)


def _extract_location_terms(message: str) -> Tuple[str, ...]:
    """提取天气问题中的地点片段；地点是否合法由地理编码边界确认。"""

    if _CONTEXT_ONLY_PATTERN.fullmatch(message.strip()):
        return ()
    if _REGIONAL_DISCOVERY_PATTERN.search(message) and _REGIONAL_WEATHER_PATTERN.search(
        message
    ):
        return ()
    text = _DATE_PATTERN.sub("", message.strip())
    english_term = _extract_english_location_term(text)
    if english_term:
        return (english_term,)
    text = re.sub(r"(?:会不会|是否|可能会|会)", "", text)
    end_match = _LOCATION_END_PATTERN.search(text)
    candidate_text = text[: end_match.start()] if end_match else text
    candidate_text = candidate_text.strip(" \t\r\n？?！!。.")
    candidate_text = _LEADING_FILLER_PATTERN.sub("", candidate_text)
    candidate_text = _TRAILING_FILLER_PATTERN.sub("", candidate_text)
    if _QUALIFIED_LOCATION_PATTERN.fullmatch(candidate_text):
        return (re.sub(r"\s*,\s*", ", ", candidate_text),)

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


def _extract_english_location_term(message: str) -> Optional[str]:
    """提取常见英文天气问法中的全球城市或“城市, 国家”地点。"""

    normalized = re.sub(r"\s+", " ", message).strip()
    for pattern in _ENGLISH_LOCATION_PATTERNS:
        match = pattern.fullmatch(normalized)
        if not match:
            continue
        location = match.group(1).strip(" \t\r\n?!. ")
        if _VALID_LOCATION_PATTERN.fullmatch(location):
            return location
        if _QUALIFIED_LOCATION_PATTERN.fullmatch(location):
            return re.sub(r"\s*,\s*", ", ", location)
    return None
