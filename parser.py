"""中文天气问题的最小规则解析器。"""

from dataclasses import dataclass
import re
from typing import Dict, Optional


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


_TIME_PATTERNS = (("后天", 2), ("明天", 1), ("今天", 0))
_CITY_PATTERN = re.compile(
    "|".join(re.escape(city_name) for city_name in sorted(SUPPORTED_CITIES, key=len, reverse=True))
)


def parse_query(message: str) -> ParsedQuery:
    """从中文消息中提取城市和相对日期；未写日期时默认今天。"""

    city_match = _CITY_PATTERN.search(message)
    city = SUPPORTED_CITIES.get(city_match.group(0)) if city_match else None

    for date_label, day_offset in _TIME_PATTERNS:
        if date_label in message:
            return ParsedQuery(city, day_offset, date_label)

    return ParsedQuery(city, 0, "今天")
