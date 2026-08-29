"""有界的区域实时降雨/雷雨搜索。"""

from dataclasses import dataclass
import re
from typing import Optional, Protocol, Sequence, Tuple

from parser import City
from weather_client import WeatherData, WeatherDataError


RAIN = "rain"
THUNDERSTORM = "thunderstorm"
REGIONAL_WEATHER_INTENT = "regional_weather"


class RegionalWeatherProvider(Protocol):
    def get_current_many(self, cities: Sequence[City]) -> Tuple[WeatherData, ...]:
        ...


@dataclass(frozen=True)
class MonitoredLocation:
    city: City
    province: str


@dataclass(frozen=True)
class RegionalWeatherQuery:
    scope: str
    phenomena: Tuple[str, ...]


@dataclass(frozen=True)
class RegionalWeatherMatch:
    city: City
    weather: WeatherData


@dataclass(frozen=True)
class RegionalWeatherResult:
    query: RegionalWeatherQuery
    monitored_count: int
    matches: Tuple[RegionalWeatherMatch, ...]


_DISCOVERY_PATTERN = re.compile(r"哪里|哪些地方|哪些城市|什么地方|有哪些地方")
_THUNDER_PATTERN = re.compile(r"打雷|雷雨|雷暴|雷电")
_RAIN_PATTERN = re.compile(r"下雨|降雨|有雨|正在下雨")

_PROVINCE_ALIASES = {
    "全国": "中国",
    "中国": "中国",
    "北京市": "北京",
    "北京": "北京",
    "天津市": "天津",
    "天津": "天津",
    "上海市": "上海",
    "上海": "上海",
    "重庆市": "重庆",
    "重庆": "重庆",
    "河北省": "河北",
    "河北": "河北",
    "山西省": "山西",
    "山西": "山西",
    "内蒙古自治区": "内蒙古",
    "内蒙古": "内蒙古",
    "辽宁省": "辽宁",
    "辽宁": "辽宁",
    "吉林省": "吉林",
    "吉林": "吉林",
    "黑龙江省": "黑龙江",
    "黑龙江": "黑龙江",
    "江苏省": "江苏",
    "江苏": "江苏",
    "浙江省": "浙江",
    "浙江": "浙江",
    "安徽省": "安徽",
    "安徽": "安徽",
    "福建省": "福建",
    "福建": "福建",
    "江西省": "江西",
    "江西": "江西",
    "山东省": "山东",
    "山东": "山东",
    "河南省": "河南",
    "河南": "河南",
    "湖北省": "湖北",
    "湖北": "湖北",
    "湖南省": "湖南",
    "湖南": "湖南",
    "广东省": "广东",
    "广东": "广东",
    "广西壮族自治区": "广西",
    "广西": "广西",
    "海南省": "海南",
    "海南": "海南",
    "四川省": "四川",
    "四川": "四川",
    "贵州省": "贵州",
    "贵州": "贵州",
    "云南省": "云南",
    "云南": "云南",
    "西藏自治区": "西藏",
    "西藏": "西藏",
    "陕西省": "陕西",
    "陕西": "陕西",
    "甘肃省": "甘肃",
    "甘肃": "甘肃",
    "青海省": "青海",
    "青海": "青海",
    "宁夏回族自治区": "宁夏",
    "宁夏": "宁夏",
    "新疆维吾尔自治区": "新疆",
    "新疆": "新疆",
    "香港特别行政区": "香港",
    "香港": "香港",
    "澳门特别行政区": "澳门",
    "澳门": "澳门",
    "台湾省": "台湾",
    "台湾": "台湾",
}


def _spot(name: str, latitude: float, longitude: float, province: str) -> MonitoredLocation:
    return MonitoredLocation(City(name, latitude, longitude), province)


# 全国查询覆盖省会和主要城市；湖南查询额外覆盖全部地级行政中心。
MONITORED_LOCATIONS: Tuple[MonitoredLocation, ...] = (
    _spot("北京", 39.9042, 116.4074, "北京"),
    _spot("天津", 39.3434, 117.3616, "天津"),
    _spot("上海", 31.2304, 121.4737, "上海"),
    _spot("重庆", 29.5630, 106.5516, "重庆"),
    _spot("石家庄", 38.0428, 114.5149, "河北"),
    _spot("太原", 37.8706, 112.5489, "山西"),
    _spot("呼和浩特", 40.8426, 111.7492, "内蒙古"),
    _spot("沈阳", 41.8057, 123.4315, "辽宁"),
    _spot("长春", 43.8171, 125.3235, "吉林"),
    _spot("哈尔滨", 45.8038, 126.5350, "黑龙江"),
    _spot("南京", 32.0603, 118.7969, "江苏"),
    _spot("杭州", 30.2741, 120.1551, "浙江"),
    _spot("合肥", 31.8206, 117.2272, "安徽"),
    _spot("福州", 26.0745, 119.2965, "福建"),
    _spot("南昌", 28.6820, 115.8579, "江西"),
    _spot("济南", 36.6512, 117.1201, "山东"),
    _spot("郑州", 34.7466, 113.6254, "河南"),
    _spot("武汉", 30.5928, 114.3055, "湖北"),
    _spot("长沙", 28.2282, 112.9388, "湖南"),
    _spot("株洲", 27.8277, 113.1339, "湖南"),
    _spot("湘潭", 27.8297, 112.9441, "湖南"),
    _spot("衡阳", 26.8932, 112.5719, "湖南"),
    _spot("邵阳", 27.2389, 111.4677, "湖南"),
    _spot("岳阳", 29.3571, 113.1289, "湖南"),
    _spot("常德", 29.0316, 111.6985, "湖南"),
    _spot("张家界", 29.1171, 110.4792, "湖南"),
    _spot("益阳", 28.5539, 112.3550, "湖南"),
    _spot("郴州", 25.7705, 113.0147, "湖南"),
    _spot("永州", 26.4204, 111.6134, "湖南"),
    _spot("怀化", 27.5695, 110.0016, "湖南"),
    _spot("娄底", 27.7001, 111.9935, "湖南"),
    _spot("吉首", 28.2624, 109.6982, "湖南"),
    _spot("广州", 23.1291, 113.2644, "广东"),
    _spot("深圳", 22.5431, 114.0579, "广东"),
    _spot("南宁", 22.8170, 108.3665, "广西"),
    _spot("海口", 20.0440, 110.1999, "海南"),
    _spot("成都", 30.5728, 104.0668, "四川"),
    _spot("贵阳", 26.6470, 106.6302, "贵州"),
    _spot("昆明", 25.0389, 102.7183, "云南"),
    _spot("拉萨", 29.6520, 91.1721, "西藏"),
    _spot("西安", 34.3416, 108.9398, "陕西"),
    _spot("兰州", 36.0611, 103.8343, "甘肃"),
    _spot("西宁", 36.6171, 101.7782, "青海"),
    _spot("银川", 38.4872, 106.2309, "宁夏"),
    _spot("乌鲁木齐", 43.8256, 87.6168, "新疆"),
    _spot("香港", 22.3193, 114.1694, "香港"),
    _spot("澳门", 22.1987, 113.5439, "澳门"),
    _spot("台北", 25.0330, 121.5654, "台湾"),
)


def parse_regional_weather_query(
    message: str,
    previous_scope: str = "",
    previous_phenomena: Sequence[str] = (),
) -> Optional[RegionalWeatherQuery]:
    """识别显式区域查询，或继承上一轮现象的省份追问。"""

    normalized = re.sub(r"\s+", "", message)
    if "明天" in normalized or "后天" in normalized:
        return None
    scope = _extract_scope(normalized)
    is_discovery = bool(_DISCOVERY_PATTERN.search(normalized))
    has_thunder = bool(_THUNDER_PATTERN.search(normalized))
    has_rain = bool(_RAIN_PATTERN.search(normalized))

    if is_discovery and (has_thunder or has_rain):
        phenomena = (THUNDERSTORM,) if has_thunder else (RAIN,)
        return RegionalWeatherQuery(scope or "中国", phenomena)
    if is_discovery and scope and previous_phenomena:
        allowed = tuple(
            item for item in previous_phenomena if item in {RAIN, THUNDERSTORM}
        )
        if allowed:
            return RegionalWeatherQuery(scope, allowed)
    return None


def monitored_cities(scope: str) -> Tuple[City, ...]:
    locations = (
        MONITORED_LOCATIONS
        if scope == "中国"
        else tuple(item for item in MONITORED_LOCATIONS if item.province == scope)
    )
    return tuple(item.city for item in locations)


def search_regional_weather(
    provider: RegionalWeatherProvider, query: RegionalWeatherQuery
) -> RegionalWeatherResult:
    cities = monitored_cities(query.scope)
    if not cities:
        return RegionalWeatherResult(query, 0, ())
    weather_items = provider.get_current_many(cities)
    if len(weather_items) != len(cities):
        raise WeatherDataError("regional weather result count does not match locations")
    matches = tuple(
        RegionalWeatherMatch(city, weather)
        for city, weather in zip(cities, weather_items)
        if _matches(weather, query.phenomena)
    )
    return RegionalWeatherResult(query, len(cities), matches)


def build_regional_weather_answer(result: RegionalWeatherResult) -> str:
    scope_label = "全国" if result.query.scope == "中国" else result.query.scope
    phenomenon = "正在打雷下雨" if THUNDERSTORM in result.query.phenomena else "正在下雨"
    coverage = f"当前监测的{scope_label}{result.monitored_count}个主要城市"
    if not result.matches:
        return (
            f"在{coverage}中，暂未发现{phenomenon}的地点。"
            "天气变化较快，结果仅代表当前模型数据，不等同于完整天气雷达。"
        )
    names = "、".join(item.city.name for item in result.matches)
    return (
        f"根据 Open-Meteo 当前数据，在{coverage}中，{names}{phenomenon}。"
        "结果仅覆盖监测城市，天气变化较快。"
    )


def _extract_scope(message: str) -> str:
    for alias in sorted(_PROVINCE_ALIASES, key=len, reverse=True):
        if alias in message:
            return _PROVINCE_ALIASES[alias]
    return ""


def _matches(weather: WeatherData, phenomena: Sequence[str]) -> bool:
    if THUNDERSTORM in phenomena:
        return "雷" in weather.condition
    return RAIN in phenomena and weather.rain_expected
