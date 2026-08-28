# Weather Query Agent MVP

一个规则驱动的中文天气查询 Agent MVP。它提供 `POST /chat`，识别城市和“今天/明天/后天”，调用 OpenWeatherMap，并用内存字典保存同一 `session_id` 的上一次城市。

## 功能

- 支持示例：`北京今天天气怎么样？`、`上海明天会下雨吗？`
- 支持同一会话追问：`那后天呢？`
- 返回摄氏温度、天气状况、湿度、风速、是否预期下雨，以及明天的简单建议。
- 当前内置城市：北京、上海、广州、深圳、成都、杭州、南京、武汉、西安、重庆、天津、香港、澳门。

## 项目结构

```text
.
├── app.py
├── config.py
├── parser.py
├── session_store.py
├── weather_client.py
├── requirements.txt
├── .env.example
├── .gitignore
├── SPEC.md
├── tasks/
│   ├── plan.md
│   └── todo.md
└── tests/
    ├── test_app.py
    ├── test_parser.py
    └── test_weather_client.py
```

## 安装与运行

需要 Python 3.9 或更高版本，以及一个 OpenWeatherMap API Key。

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:OPENWEATHER_API_KEY = "你的 OpenWeatherMap API Key"
python app.py
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export OPENWEATHER_API_KEY="你的 OpenWeatherMap API Key"
python app.py
```

服务默认监听 `http://127.0.0.1:5000`。

## 测试

测试不会访问真实 OpenWeatherMap，而是对上游响应使用可控的测试替身：

```bash
python -m pytest -q
```

## curl 示例

第一次查询时提供一个会话 ID；第二次复用该 ID，服务会记住“上海”：

```bash
curl -X POST http://127.0.0.1:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"上海明天会下雨吗？","session_id":"demo-1"}'

curl -X POST http://127.0.0.1:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"那后天呢？","session_id":"demo-1"}'
```

如果不传 `session_id`，服务会生成一个随机会话 ID，并在成功响应中返回；客户端需要保存它以便继续多轮对话。

## 响应示例

```json
{
  "session_id": "demo-1",
  "city": "上海",
  "date": "明天",
  "answer": "上海明天：雨，气温约 25.0℃，湿度 80%，风速 2.0 m/s。明天可能有雨，建议携带雨具。",
  "weather": {
    "temperature_c": 25.0,
    "condition": "雨",
    "humidity_percent": 80,
    "wind_speed_mps": 2.0,
    "rain_expected": true,
    "advice": "明天可能有雨，建议携带雨具。"
  }
}
```

## MVP 限制

- 会话状态只在当前 Python 进程内存中；重启服务或使用多进程部署后不会共享。生产化时可把 `InMemorySessionStore` 替换成 Redis 等实现。
- 城市使用白名单坐标，不接入自动地理编码；增加城市需修改 `parser.py`。
- “明天/后天”的预报依赖 5 Day / 3 Hour Forecast API 的 3 小时条目；服务按 OpenWeatherMap 返回的城市时区聚合目标日期。

## 官方接口依据

- OpenWeatherMap Current Weather API：<https://openweathermap.org/api/current>
- OpenWeatherMap 5 Day / 3 Hour Forecast API：<https://openweathermap.org/api/forecast5>
- Flask Quickstart：<https://flask.palletsprojects.com/en/stable/quickstart/>
- Requests Quickstart：<https://requests.readthedocs.io/en/latest/user/quickstart/>
