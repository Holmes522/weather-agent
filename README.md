# Weather Query Agent MVP

一个带可视化聊天界面的规则驱动中文天气查询 Agent MVP。它提供网页首页和 `POST /chat`，识别城市及“今天/明天/后天”，可自由选择 Open-Meteo、OpenWeatherMap 或和风天气，并用内存字典保存同一 `session_id` 的上一次城市。

## 功能

- 支持示例：`北京今天天气怎么样？`、`上海明天会下雨吗？`
- 支持同一会话追问：`那后天呢？`
- 提供响应式网页聊天界面，以天气卡展示温度、天气、湿度、风速和降雨建议。
- 支持天气 Provider：无需 Key 的 `openmeteo`，以及 `openweather`、`qweather`。
- 可通过环境变量设置默认 Provider，也可在单次请求中选择。
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
├── templates/
│   └── index.html
├── static/
│   ├── app.js
│   └── styles.css
├── requirements.txt
├── .env.example
├── .gitignore
├── SPEC.md
├── tasks/
│   ├── plan.md
│   └── todo.md
└── tests/
    ├── test_app.py
    ├── test_config.py
    ├── test_parser.py
    ├── test_openmeteo_client.py
    ├── test_qweather_client.py
    └── test_weather_client.py
```

## 安装与运行

需要 Python 3.9 或更高版本。使用和风天气时，需要在和风天气控制台创建 API Key，并复制控制台分配的专属 API Host。

### 最快体验（Open-Meteo，无需 API Key）

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:WEATHER_PROVIDER = "openmeteo"
python app.py
```

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:WEATHER_PROVIDER = "qweather"
$env:QWEATHER_API_KEY = "你的和风天气 API Key"
$env:QWEATHER_API_HOST = "控制台中的专属主机名.qweatherapi.com"
python app.py
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export WEATHER_PROVIDER="qweather"
export QWEATHER_API_KEY="你的和风天气 API Key"
export QWEATHER_API_HOST="控制台中的专属主机名.qweatherapi.com"
python app.py
```

服务默认监听 `http://127.0.0.1:5000`。

## 使用可视化平台

保持运行 `python app.py` 的 PowerShell 窗口不要关闭，然后在浏览器打开：

<http://127.0.0.1:5000>

在输入框中直接提问，例如 `北京今天天气怎么样？`。查询成功后可以继续输入 `那后天呢？`，网页会沿用当前页面中的会话 ID，后端会记住上次查询的城市。右上角的数据源下拉框可以自由切换；Open-Meteo 始终可用，另外两个数据源在配置对应凭据后显示。

网页不会接收或保存天气 API Key；Key 始终只由 Flask 后端从环境变量读取。关闭或重启 Flask 后，内存中的多轮会话会清空。

## 测试

测试不会访问真实天气服务，而是对三个 Provider 的上游响应使用可控的测试替身：

```bash
python -m pytest -q
```

## curl 示例

第一次查询时提供一个会话 ID；第二次复用该 ID，服务会记住“上海”：

```bash
curl -X POST http://127.0.0.1:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"上海明天会下雨吗？","session_id":"demo-1","provider":"qweather"}'

curl -X POST http://127.0.0.1:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"那后天呢？","session_id":"demo-1"}'
```

如果不传 `session_id`，服务会生成一个随机会话 ID，并在成功响应中返回；客户端需要保存它以便继续多轮对话。

`provider` 也是可选字段：未传时使用 `WEATHER_PROVIDER`，可选值为 `openmeteo`、`openweather` 或 `qweather`。`openmeteo` 无需凭据；另外两个 Provider 只有配置对应凭据后才能选择。

如果需要同时启用全部 Provider（Open-Meteo 会自动启用）：

```powershell
$env:WEATHER_PROVIDER = "qweather"
$env:QWEATHER_API_KEY = "你的和风天气 API Key"
$env:QWEATHER_API_HOST = "控制台中的专属主机名.qweatherapi.com"
$env:OPENWEATHER_API_KEY = "你的 OpenWeatherMap API Key"
python app.py
```

## 响应示例

```json
{
  "session_id": "demo-1",
  "city": "上海",
  "date": "明天",
  "provider": "qweather",
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
- OpenWeatherMap 的“明天/后天”按 3 小时预报聚合；和风天气使用每日预报中的目标日期条目。
- Open-Meteo 使用当前天气和每日预报变量；非商业 API 无需 Key，商业使用应遵循其许可和客户 API 要求。
- 和风天气 API Host 必须是控制台分配的 `*.qweatherapi.com` 主机名，不能包含 `https://` 或路径。

## 官方接口依据

- Open-Meteo Weather Forecast API：<https://open-meteo.com/en/docs>
- OpenWeatherMap Current Weather API：<https://openweathermap.org/api/current>
- OpenWeatherMap 5 Day / 3 Hour Forecast API：<https://openweathermap.org/api/forecast5>
- 和风天气实时天气 v1：<https://dev.qweather.com/docs/api/weather/weather-current/>
- 和风天气每日预报 v1：<https://dev.qweather.com/docs/api/weather/weather-daily-forecast/>
- 和风天气认证与 API Host：<https://dev.qweather.com/docs/configuration/authentication/>、<https://dev.qweather.com/docs/configuration/api-host/>
- Flask Quickstart：<https://flask.palletsprojects.com/en/stable/quickstart/>
- Requests Quickstart：<https://requests.readthedocs.io/en/latest/user/quickstart/>
