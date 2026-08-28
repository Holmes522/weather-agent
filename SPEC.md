# 天气查询 Agent MVP 规格

> 本文件保留初始 MVP 契约。多城市、动态地理编码、意图化回复和新响应字段由根目录的 `CAPABILITY_MAP.md` 以及三个 `SPEC-*.md` 扩展规格定义。

## Objective

构建一个 Python 3.9+ Flask REST API，让用户用中文自然语言查询一个或多个全球城市的今天、明天或后天天气。系统用规则识别地点、相对日期和问题意图，动态解析白名单外城市，并在内存中按 `session_id` 记住对话上下文。

## Tech Stack

- Python 3.9+
- Flask 3.x
- Requests 2.x
- pytest
- OpenWeatherMap Current Weather API 与 5 Day / 3 Hour Forecast API
- 和风天气 Current Weather v1 与 Daily Forecast v1

## API Contract

`POST /chat`

Request:

```json
{
  "message": "北京今天天气怎么样？",
  "session_id": "demo-session-1",
  "provider": "qweather"
}
```

`session_id` 可选；未提供时服务端生成临时会话 ID，并在响应中返回，调用方应在后续请求中复用它。

`provider` 可选；可选值为 `openweather`、`qweather`，未提供时使用 `WEATHER_PROVIDER` 指定的默认服务。

Success response (`200`):

```json
{
  "session_id": "demo-session-1",
  "city": "北京",
  "date": "今天",
  "provider": "qweather",
  "answer": "北京今天...",
  "weather": {
    "temperature_c": 22.3,
    "condition": "晴",
    "humidity_percent": 45,
    "wind_speed_mps": 3.1,
    "rain_expected": false,
    "advice": "明天暂无明显降雨信号，出行可暂不携带雨具。"
  }
}
```

Error response:

```json
{
  "error": {
    "code": "INVALID_MESSAGE",
    "message": "请提供要查询的天气问题。"
  }
}
```

## Project Structure

```text
weather-agent/
├── app.py                 # Flask 应用工厂与 /chat 路由
├── config.py              # 环境变量配置
├── parser.py              # 中文城市/时间规则解析
├── session_store.py       # 内存会话状态
├── weather_client.py      # 统一模型及 OpenWeatherMap/和风天气客户端
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
└── tests/
    ├── test_config.py
    ├── test_parser.py
    ├── test_qweather_client.py
    ├── test_weather_client.py
    └── test_app.py
```

## Testing Strategy

- 单元测试：解析器、建议生成、外部响应归一化。
- 集成测试：Flask test client 验证 `/chat` 的成功、参数错误、会话延续和外部服务错误。
- 外部天气服务不在测试中真实调用，使用 `requests` 响应桩，避免依赖 API Key、网络和实时天气。

## Boundaries

- Always：在 HTTP 边界限制 JSON 消息长度；验证第三方 JSON 字段；API Key 只从环境变量读取；对外部请求设置超时；不把上游错误细节返回给用户。
- Ask first：更换地理编码供应商、引入数据库或 LLM、增加认证策略。
- Never：提交 `.env` 或真实 API Key；把用户输入拼入 URL；将第三方文本直接当作系统指令执行。

## Success Criteria

1. “北京今天天气怎么样？”能识别北京/今天并调用当前天气接口。
2. “上海明天会下雨吗？”能调用 5 天 3 小时预报，并给出是否有雨及简单建议。
3. 同一 `session_id` 下，“那后天呢？”能复用上一次城市。
4. 请求可选择 OpenWeatherMap 或和风天气，并在响应中返回实际使用的 Provider。
5. 缺少城市、Provider 无效、API Key 缺失、上游失败都有稳定的 JSON 错误响应。
6. `pytest` 全部通过，且项目不依赖真实网络测试。
