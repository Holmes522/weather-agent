# Weather Query Agent MVP

一个带可视化聊天界面的规则驱动中文天气查询 Agent MVP。它提供网页首页和 `POST /chat`，识别城市及“今天/明天/后天”，支持五种常用天气数据源，并用内存字典保存同一 `session_id` 的上一次城市。

## 功能

- 支持示例：`北京今天天气怎么样？`、`上海明天会下雨吗？`
- 支持同一会话追问：`那后天呢？`
- 提供响应式网页聊天界面，以天气卡展示温度、天气、湿度、风速和降雨建议。
- 支持天气 Provider：无需 Key 的 `openmeteo`，以及 `openweather`、`qweather`、`weatherapi`、`visualcrossing`。
- 可通过环境变量设置默认 Provider，也可在单次请求中选择。
- 提供仅限本机访问的 API 配置页，可在运行期间新增或更新天气服务凭据。
- 返回摄氏温度、天气状况、湿度、风速、是否预期下雨，以及明天的简单建议。
- 当前内置城市：北京、上海、广州、深圳、成都、杭州、南京、武汉、西安、重庆、天津、香港、澳门。

## 项目结构

```text
.
├── app.py
├── config.py
├── parser.py
├── rate_limiter.py
├── session_store.py
├── weather_client.py
├── wsgi.py
├── render.yaml
├── templates/
│   ├── index.html
│   └── settings.html
├── static/
│   ├── app.js
│   ├── settings.js
│   ├── settings.css
│   └── styles.css
├── requirements.txt
├── requirements-dev.txt
├── DEPLOYMENT.md
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
    ├── test_common_provider_clients.py
    ├── test_deployment.py
    ├── test_production.py
    ├── test_provider_config.py
    ├── test_qweather_client.py
    └── test_weather_client.py
```

## 安装与运行

需要 Python 3.9 或更高版本。使用和风天气时，需要在和风天气控制台创建 API Key，并复制控制台分配的专属 API Host。

### 最快体验（Open-Meteo，无需 API Key）

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python app.py
```

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
$env:WEATHER_PROVIDER = "qweather"
$env:QWEATHER_API_KEY = "你的和风天气 API Key"
$env:QWEATHER_API_HOST = "控制台中的专属主机名.qweatherapi.com"
python app.py
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
export WEATHER_PROVIDER="qweather"
export QWEATHER_API_KEY="你的和风天气 API Key"
export QWEATHER_API_HOST="控制台中的专属主机名.qweatherapi.com"
python app.py
```

服务默认监听 `http://127.0.0.1:5000`。

## 使用可视化平台

保持运行 `python app.py` 的 PowerShell 窗口不要关闭，然后在浏览器打开：

<http://127.0.0.1:5000>

在输入框中直接提问，例如 `北京今天天气怎么样？`。查询成功后可以继续输入 `那后天呢？`，网页会沿用当前页面中的会话 ID，后端会记住上次查询的城市。右上角的数据源下拉框可以自由切换；Open-Meteo 始终可用，其他数据源在配置对应凭据后显示。

点击聊天页右上角的“配置 API”，或直接打开 <http://127.0.0.1:5000/settings>，可以选择 OpenWeather、和风天气、WeatherAPI.com 或 Visual Crossing 并输入配置。Key 只发送到本机 Flask，保存在当前 Python 进程内存中，不写入浏览器、本地文件、日志或 Git；重启 Flask 后运行时配置会清空。配置页和配置接口只允许从 `127.0.0.1` 或 `::1` 访问。

如果希望重启后仍自动加载 Provider，请继续使用环境变量方式配置。

## 免费部署到 Render

仓库根目录已经包含可直接使用的 `render.yaml`：默认创建 Render 免费 Web Service，以 Open-Meteo 作为无需 Key 的天气数据源，并使用 Gunicorn 启动生产服务。

1. 登录 <https://dashboard.render.com/>；
2. 选择 **New → Blueprint**；
3. 连接 GitHub 仓库 `Holmes522/weather-agent`；
4. 确认 Blueprint 并等待部署完成。

生产环境会自动关闭 `/settings` 和 `/api/providers`，并对 `/chat` 启用每个客户端每分钟 30 次的内存限流。详细操作、验证和回滚步骤见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## 测试

测试不会访问真实天气服务，而是对五个 Provider 的上游响应使用可控的测试替身：

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

`provider` 也是可选字段：未传时使用 `WEATHER_PROVIDER`，可选值为 `openmeteo`、`openweather`、`qweather`、`weatherapi` 或 `visualcrossing`。`openmeteo` 无需凭据；其他 Provider 只有配置对应凭据后才能选择。

如果需要同时启用全部 Provider（Open-Meteo 会自动启用）：

```powershell
$env:WEATHER_PROVIDER = "qweather"
$env:QWEATHER_API_KEY = "你的和风天气 API Key"
$env:QWEATHER_API_HOST = "控制台中的专属主机名.qweatherapi.com"
$env:OPENWEATHER_API_KEY = "你的 OpenWeatherMap API Key"
$env:WEATHERAPI_API_KEY = "你的 WeatherAPI.com API Key"
$env:VISUAL_CROSSING_API_KEY = "你的 Visual Crossing API Key"
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
- 通过网页新增的 Provider 凭据同样只保存在当前进程内存中；配置页是本地开发功能，不应直接暴露到公网。
- 当 `APP_ENV=production` 时，配置页和配置接口直接返回 404；天气凭据必须通过托管平台的环境变量设置。
- 免费部署使用单 Worker，以保证当前内存会话和限流状态一致；扩容前应迁移到 Redis。
- 城市使用白名单坐标，不接入自动地理编码；增加城市需修改 `parser.py`。
- OpenWeatherMap 的“明天/后天”按 3 小时预报聚合；和风天气使用每日预报中的目标日期条目。
- Open-Meteo 使用当前天气和每日预报变量；非商业 API 无需 Key，商业使用应遵循其许可和客户 API 要求。
- 和风天气 API Host 必须是控制台分配的 `*.qweatherapi.com` 主机名，不能包含 `https://` 或路径。

## 官方接口依据

- Open-Meteo Weather Forecast API：<https://open-meteo.com/en/docs>
- WeatherAPI.com API：<https://www.weatherapi.com/docs/>
- Visual Crossing Timeline Weather API：<https://www.visualcrossing.com/resources/documentation/weather-api/timeline-weather-api/>
- OpenWeatherMap Current Weather API：<https://openweathermap.org/api/current>
- OpenWeatherMap 5 Day / 3 Hour Forecast API：<https://openweathermap.org/api/forecast5>
- 和风天气实时天气 v1：<https://dev.qweather.com/docs/api/weather/weather-current/>
- 和风天气每日预报 v1：<https://dev.qweather.com/docs/api/weather/weather-daily-forecast/>
- 和风天气认证与 API Host：<https://dev.qweather.com/docs/configuration/authentication/>、<https://dev.qweather.com/docs/configuration/api-host/>
- Flask Quickstart：<https://flask.palletsprojects.com/en/stable/quickstart/>
- Flask 生产部署：<https://flask.palletsprojects.com/en/stable/deploying/>
- Flask Gunicorn：<https://flask.palletsprojects.com/en/stable/deploying/gunicorn/>
- Flask 反向代理配置：<https://flask.palletsprojects.com/en/stable/deploying/proxy_fix/>
- Render Flask 部署：<https://render.com/docs/deploy-flask>
- Render Blueprint：<https://render.com/docs/blueprint-spec>
- Requests Quickstart：<https://requests.readthedocs.io/en/latest/user/quickstart/>
