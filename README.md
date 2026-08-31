# Weather Query Agent MVP

一个以天气为核心的轻量 AI Agent。它提供网页首页和 `POST /chat`：未配置模型时仍是免费的规则天气助手；配置 OpenAI 兼容模型后，可以进行普通聊天、多轮对话，并由模型按需组合实时天气工具与本地天气知识 RAG。

## 功能

- 支持示例：`深圳和广州明天天气什么样？`、`东京明天天气怎么样？`、`What's the weather in Paris, France tomorrow?`、`现在哪里在打雷下雨？`。
- 支持同一会话追问：`那后天呢？`，以及在建议后回复 `需要` 查看完整天气。
- 支持区域天气现象追问：先问全国哪里在打雷下雨，再问 `湖南省有哪些地方？`，系统会继承雷雨条件并缩小到湖南。
- 网页左侧提供历史对话栏，可新建、切换、恢复和删除对话；手机端显示为抽屉。
- 可把最近一次真实天气结果或多城市逐日行程导出为 Word、Excel、PDF 或 Markdown，并在聊天中直接下载。
- 只有明确询问完整天气时才显示天气卡；湿度、温度、风、降雨和出行问题只回答对应内容。
- 常用城市使用本地坐标，其他全球城市通过 Nominatim 动态解析并缓存结果；支持中文、英文及“城市, 国家/地区”地点写法。
- 支持已确认的常见城市错别字，例如把 `大利` 纠正为 `大理`。
- 支持天气 Provider：无需 Key 的 `openmeteo`，以及 `openweather`、`qweather`、`weatherapi`、`visualcrossing`。
- 可通过环境变量设置默认 Provider，也可在单次请求中选择。
- 提供仅限本机访问的 API 配置页，可在运行期间新增或更新天气服务凭据。
- 返回摄氏温度、天气状况、湿度、风速、是否预期下雨，以及明天的简单建议。
- 一次请求最多提取 5 个城市，并按用户输入顺序返回结果。
- 可选连接 OpenAI、DeepSeek、OpenRouter、智谱 GLM、Kimi、通义千问、豆包、Gemini、本机 Ollama 或自定义 OpenAI 兼容接口。
- 本机配置页可同时保存最多 20 个 AI 模型配置并自由切换；新增模型不会覆盖旧模型。
- 默认 LangChain Agent 拥有只读的 `get_weather` 和 `search_weather_knowledge` 工具；可以把实时天气与雷雨、暴雨、高温、寒冷、大风等权威安全资料组合成建议，并在回答下方显示实际来源。
- RAG 使用仓库内经过校验的 Markdown 和本地 Hash Embeddings，不需要额外的 Embedding API Key；实时天气仍只来自天气 Provider，知识库不能替代官方预警。
- Agent 不能执行命令、浏览网页、读取任意文件或控制电脑。
- 默认使用 LangChain `create_agent`（由 LangGraph 运行）编排模型与工具；可通过环境变量明确回滚到原生引擎。
- 模型参数、工具参数和第三方响应均在代码边界校验；每轮最多两次天气工具、一次知识检索、三次全部工具和四次模型调用。

## 项目结构

```text
.
├── app.py
├── agent.py
├── langchain_agent.py
├── knowledge_base.py
├── knowledge/
│   ├── thunderstorm-safety.md
│   ├── heavy-rain-flood-safety.md
│   ├── heat-health-safety.md
│   ├── cold-weather-safety.md
│   └── strong-wind-safety.md
├── llm_client.py
├── llm_registry.py
├── weather_export.py
├── export_store.py
├── export_chat.py
├── config.py
├── conversation.py
├── geocoding.py
├── parser.py
├── rate_limiter.py
├── regional_chat.py
├── regional_weather.py
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
├── SPEC-rag-weather-knowledge.md
├── tasks/
│   ├── plan.md
│   └── todo.md
└── tests/
    ├── test_app.py
    ├── test_agent.py
    ├── test_ai_chat.py
    ├── test_llm_client.py
    ├── test_llm_config.py
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

需要 Python 3.10 或更高版本。使用和风天气时，需要在和风天气控制台创建 API Key，并复制控制台分配的专属 API Host。

### 最快体验（天气模式，无需任何 API Key）

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

### 开启 AI Agent 模式

保持 Flask 运行，在浏览器打开 <http://127.0.0.1:5000/settings>，找到“连接 AI 模型”：

1. 选择 OpenAI、DeepSeek、OpenRouter、智谱 GLM、Moonshot Kimi、通义千问、豆包、Google Gemini、本机 Ollama 或自定义兼容接口；
2. 输入该服务实际存在且支持工具调用的模型 ID；
3. 在线服务输入 API Key；Ollama 本机模式不需要真实 Key；
4. 保存后新模型会成为当前模型，但以前保存的模型仍显示在“已保存模型”中，可以随时切换；
5. 返回聊天页后，右上角“AI 模型”下拉框也可切换当前模型。

例如使用 DeepSeek 环境变量持久配置：

```powershell
$env:LLM_BASE_URL = "https://api.deepseek.com"
$env:LLM_API_KEY = "你的 DeepSeek API Key"
$env:LLM_MODEL = "deepseek-v4-flash"
$env:LLM_DISPLAY_NAME = "DeepSeek"
python app.py
```

例如连接已在本机运行并已拉取模型的 Ollama：

```powershell
$env:LLM_BASE_URL = "http://127.0.0.1:11434/v1"
$env:LLM_MODEL = "qwen3:8b"
$env:LLM_DISPLAY_NAME = "Ollama（本机）"
Remove-Item Env:LLM_API_KEY -ErrorAction SilentlyContinue
python app.py
```

外部自定义模型地址必须使用 HTTPS；只有 `localhost`、`127.0.0.1` 或 `::1` 可以使用 HTTP。选择的模型必须支持 OpenAI 风格的 Chat Completions 和 function/tool calling。

默认 Agent 引擎为 LangChain，无需额外配置。遇到框架兼容问题时，可以在启动 Flask 前显式切回原有受限循环；系统不会在运行中静默切换：

```powershell
$env:AGENT_ENGINE = "native"
python app.py
```

恢复默认引擎：

```powershell
$env:AGENT_ENGINE = "langchain"
python app.py
```

Claude 官方直连接口不是 OpenAI Chat Completions 协议，因此本版本不伪装成直连预设；如需使用 Claude，可在 OpenRouter 中填写对应 Claude 模型 ID，或使用受信任的 OpenAI 兼容网关。

## 使用可视化平台

保持运行 `python app.py` 的 PowerShell 窗口不要关闭，然后在浏览器打开：

<http://127.0.0.1:5000>

在输入框中可以直接询问完整天气、单项指标或出行建议。启用 AI 后还可以进行基础问答、解释、写作和总结；天气问题会自动调用真实数据源。左侧可以新建、切换和删除历史对话，切换后会恢复用户消息、AI 文本、天气卡片和导出下载入口；手机端点击左上角菜单按钮打开历史抽屉。进入配置页再返回时也会恢复离开前的当前对话。后端最多给模型使用最近 12 条普通对话消息，并为每个会话单独记住天气上下文。右上角可以自由切换天气数据源和已保存的 AI 模型；浏览器只记住天气服务 ID、模型配置 ID 和当前对话 ID，API Key 不会写入浏览器存储。

RAG 示例：`深圳明天打雷还适合爬山吗？` 会让 Agent 同时查询深圳明天的实时天气和雷电安全资料；`雷雨天气户外应该注意什么？` 只检索稳定知识，不会为无关城市发起天气请求。实际使用知识库时，回答下方会显示可点击的官方来源，切换历史对话后来源仍会恢复。RAG 默认随 LangChain 引擎启用，不需要环境变量；切换到 `AGENT_ENGINE=native` 时只保留原生天气工具循环。

全球城市可以直接输入中文或英文名称，例如 `纽约明天天气`、`Tokyo tomorrow weather`。遇到同名城市时建议同时提供国家或地区，例如 `Paris, France明天天气怎么样？` 或 `What's the weather in Paris, France tomorrow?`。询问“可以查询国外城市吗”时，系统只说明能力范围，不会把“国外”误当成城市查询。

天气导出示例：先问 `深圳和广州明天天气怎么样？`，再问 `把刚才天气导出为 Excel`；也可以一句话发送 `把深圳和广州明天天气导出为 PDF`。行程示例：`依次查看北京、深圳、广州、长沙的天气，输出 Excel，我住在杭州，每个城市待一天` 会按明天起逐城分配日期；如果只说 `北京和深圳出差 3 天，输出 Excel` 而没有说明顺序，则文件会包含两座城市各自未来 3 天的数据。文件生成后聊天区只显示下载入口，逐行建议和汇总出行清单都写入文件。支持 `Word`/`docx`、`Excel`/`xlsx`/`execl`、`PDF` 和 `Markdown`/`md`。导出链接保存在当前服务进程中，约 1 小时后失效。

点击聊天页左下角的“配置 Agent”，或直接打开 <http://127.0.0.1:5000/settings>，可以配置天气数据源与 AI 模型。Key 只发送到本机 Flask，保存在当前 Python 进程内存中，不写入浏览器、本地文件、日志或 Git；重启 Flask 后运行时配置会清空。配置页和配置接口只允许从 `127.0.0.1` 或 `::1` 访问。

如果希望重启后仍自动加载 Provider，请继续使用环境变量方式配置。

## 免费部署到 Render

仓库根目录已经包含可直接使用的 `render.yaml`：默认创建 Render 免费 Web Service，以 Open-Meteo 作为无需 Key 的天气数据源，并使用 Gunicorn 启动生产服务。

1. 登录 <https://dashboard.render.com/>；
2. 选择 **New → Blueprint**；
3. 连接 GitHub 仓库 `Holmes522/weather-agent`；
4. 确认 Blueprint 并等待部署完成。

生产环境会自动关闭 `/settings` 和 `/api/providers`，并对 `/chat` 启用每个客户端每分钟 30 次的内存限流。详细操作、验证和回滚步骤见 [DEPLOYMENT.md](DEPLOYMENT.md)。

如需在 Render 开启 AI，把 `LLM_BASE_URL`、`LLM_MODEL`、`LLM_DISPLAY_NAME` 和对应的 `LLM_API_KEY` 作为 Secret 环境变量配置。Blueprint 已设置 `AGENT_ENGINE=langchain`；紧急回滚时在 Render 环境变量中改为 `native` 并重新部署。生产环境同时关闭 `/api/llm`；不要把真实 Key 写进 `render.yaml` 或提交到 Git。

## 测试

测试不会访问真实天气或模型服务，而是对五个天气 Provider 和模型响应使用可控的测试替身：

```bash
python -m pytest -q
```

## curl 示例

第一次查询时提供一个会话 ID；第二次复用该 ID，服务会记住“深圳”和“明天”：

```bash
curl -X POST http://127.0.0.1:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"深圳明天出门要带什么？","session_id":"demo-1","provider":"openmeteo"}'

curl -X POST http://127.0.0.1:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"需要","session_id":"demo-1","provider":"openmeteo"}'
```

如果不传 `session_id`，服务会生成一个随机会话 ID，并在成功响应中返回；客户端需要保存它以便继续多轮对话。

网页历史使用以下同源接口，并由服务端签发的匿名 HttpOnly Cookie 自动隔离当前浏览器的数据：

- `GET /api/conversations`：列出历史会话；
- `POST /api/conversations`：新建空会话；
- `GET /api/conversations/<session_id>`：读取一段对话及其可重放消息；
- `DELETE /api/conversations/<session_id>`：删除历史及对应天气上下文。

这些接口是匿名 MVP 方案，不是账户系统。使用脚本直接调用 `/chat` 时仍可只传 `session_id`；若还要使用历史接口，请让 HTTP 客户端保留服务端 Cookie。

`provider` 也是可选字段：未传时使用 `WEATHER_PROVIDER`，可选值为 `openmeteo`、`openweather`、`qweather`、`weatherapi` 或 `visualcrossing`。`openmeteo` 无需凭据；其他 Provider 只有配置对应凭据后才能选择。

配置模型后，成功响应增加 `mode: "agent"`、`model`、`tool_used`、`rag_used` 和 `knowledge_sources`。只有实际检索到知识时 `rag_used` 才为 `true`，来源项包含标题、章节、来源名称和官方 HTTPS URL；普通聊天返回空来源数组。天气工具调用仍返回兼容的 `city`、`weather` 与 `results`。未配置模型时，非天气消息返回 `AI_NOT_CONFIGURED`，不会把普通问题误当成城市查询。

本机模型配置接口为：`GET /api/llm` 列出已保存模型，`POST /api/llm` 新增并设为当前模型，`PATCH /api/llm/active` 按安全配置 ID 切换。`POST /chat` 可选传入 `llm_id`。这些接口从不返回 API Key，生产环境会关闭配置接口。

导出成功时响应增加 `export.format`、`export.filename` 和 `export.download_url`。下载地址为同源 `GET /api/exports/<随机ID>`，返回附件且禁止缓存。

区域查询使用无需 Key 的 Open-Meteo 多坐标当前天气接口，与页面当前选择的单城市天气 Provider 相互独立。例如：

```powershell
$body = @{ message = "告诉我现在哪里在打雷下雨"; session_id = "storm-demo" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:5000/chat" -ContentType "application/json; charset=utf-8" -Body $body

$body = @{ message = "湖南省有哪些地方"; session_id = "storm-demo" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:5000/chat" -ContentType "application/json; charset=utf-8" -Body $body
```

区域响应的 `intent` 为 `regional_weather`，并返回 `scope`、`phenomena`、匹配的 `cities` 和 `results`。即使当前没有匹配地点也会返回 200 和空列表，同时保留上下文供下一轮缩小范围。

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
  "city": "深圳",
  "cities": ["深圳", "广州"],
  "date": "明天",
  "provider": "openmeteo",
  "agent_engine": "langchain",
  "intent": "full",
  "display_mode": "weather_cards",
  "answer": "深圳明天：……\n广州明天：……",
  "weather": {
    "temperature_c": 25.0,
    "condition": "雨",
    "humidity_percent": 80,
    "wind_speed_mps": 2.0,
    "rain_expected": true,
    "advice": "明天可能有雨，建议携带雨具。"
  },
  "results": [
    {"city": "深圳", "date": "明天", "corrected_from": null, "answer": "……", "weather": {}},
    {"city": "广州", "date": "明天", "corrected_from": null, "answer": "……", "weather": {}}
  ]
}
```

为兼容已有调用方，顶层 `city` 和 `weather` 始终对应第一个结果；新界面使用 `results` 展示全部城市。

## MVP 限制

- 会话状态和左侧历史只在当前 Python 进程内存中；每个匿名浏览器最多保留最近 100 段会话、每段最近 100 条展示消息。重启服务或使用多进程部署后不会共享，也不能跨浏览器或跨设备同步。匿名 Cookie 只用于区分浏览器，不等同于登录认证。生产化时应增加账户系统，并把 `InMemorySessionStore` 替换成数据库或 Redis 等实现。
- 通过网页新增的 Provider 凭据同样只保存在当前进程内存中；配置页是本地开发功能，不应直接暴露到公网。
- 普通聊天能力取决于用户配置的第三方模型；消息和最近有限历史会发送给该服务，费用与数据处理规则以对应服务为准。
- 运行时新增的天气服务和 AI 模型配置只保存在当前进程；浏览器只保存选择 ID，重启 Flask 后需要重新添加。环境变量模型会在启动时自动恢复。
- 行程导出一次最多 5 个目的地、未来 7 天和 35 条天气记录，单文件最多 2 MiB；临时下载存储有数量上限并约 1 小时过期，不适合作为长期文件存储。个别天气服务或套餐的预报天数可能更短，超出时会返回天气服务不可用提示。
- Agent 只有只读实时天气和固定天气知识检索工具，不具备 Codex 或 Claude Code 的文件、终端、网页浏览和代码执行能力。
- 本地 Hash Embeddings 适合当前小型、固定、中文天气知识库，但语义召回能力弱于商用 Embedding 模型；知识更新需要人工审查并提交 Markdown，服务启动后不在线抓取网页。
- 天气工具只支持今天、明天和后天；每轮最多两次天气工具、一次知识检索、三次全部工具和四次模型调用，模型回复最多 4000 字符。
- 当 `APP_ENV=production` 时，配置页和配置接口直接返回 404；天气凭据必须通过托管平台的环境变量设置。
- 免费部署使用单 Worker，以保证当前内存会话和限流状态一致；扩容前应迁移到 Redis。
- 公共 Nominatim 服务限制整个应用每秒最多一次请求；项目会缓存结果并串行调用，适合中低流量演示。全球检索范围取决于 OpenStreetMap 的地点数据，同名或较小聚落建议补充国家/地区。高流量部署应通过 `GEOCODING_API_URL` 切换到自托管或商业兼容端点。
- 城市错别字纠正使用已确认别名表，避免把真实但不常见的地点误改成另一个城市；可在 `geocoding.py` 中审慎扩充。
- OpenWeatherMap 的“明天/后天”按 3 小时预报聚合；和风天气使用每日预报中的目标日期条目。
- Open-Meteo 使用当前天气和每日预报变量；非商业 API 无需 Key，商业使用应遵循其许可和客户 API 要求。
- “哪里在下雨/打雷”是有界监测，不是全国实时雷达：全国范围覆盖省会及主要城市，湖南范围覆盖 14 个地级行政中心。回答会显示实际监测点数量，未纳入目录的县区或局地天气可能遗漏。
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
- Nominatim Search API：<https://nominatim.org/release-docs/latest/api/Search/>
- Nominatim 公共服务使用策略：<https://operations.osmfoundation.org/policies/nominatim/>
- OpenAI function calling：<https://developers.openai.com/api/docs/guides/function-calling>
- LangChain Agents：<https://docs.langchain.com/oss/python/langchain/agents>
- LangChain Tools：<https://docs.langchain.com/oss/python/langchain/tools>
- LangChain Middleware：<https://docs.langchain.com/oss/python/langchain/middleware/overview>
- LangChain Retrieval：<https://docs.langchain.com/oss/python/langchain/retrieval>
- LangGraph Agentic RAG：<https://docs.langchain.com/oss/python/langgraph/agentic-rag>
- LangChain Embeddings：<https://docs.langchain.com/oss/python/integrations/embeddings>
- 中国气象局雷电安全规范：<https://www.cma.gov.cn/zfxxgk/gknr/flfgbz/bz/202505/P020250512117538288150.pdf>
- 应急管理部暴雨洪涝防范：<https://www.mem.gov.cn/xw/xwfbh/2025n08y05xwfbh/>
- 国家卫生健康委高温健康防护：<https://www.nhc.gov.cn/zyjks/c100152/202406/0f0267211d25499b86d30f0f40a394cb.shtml>
- 智谱 GLM Chat Completions：<https://docs.bigmodel.cn/cn/guide/models/text/glm-4.5>
- Moonshot Kimi API：<https://platform.kimi.com/docs/api/overview>
- 阿里云百炼 OpenAI 兼容 API：<https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions>
- 火山方舟 Chat Completions：<https://www.volcengine.com/docs/82379/1494384>
- Gemini OpenAI 兼容接口：<https://ai.google.dev/gemini-api/docs/openai>
- DeepSeek tool calls：<https://api-docs.deepseek.com/guides/tool_calls/>
- OpenRouter tool calling：<https://openrouter.ai/docs/guides/features/tool-calling>
- Ollama OpenAI compatibility：<https://docs.ollama.com/api/openai-compatibility>
- Render Flask 部署：<https://render.com/docs/deploy-flask>
- Render Blueprint：<https://render.com/docs/blueprint-spec>
- Requests Quickstart：<https://requests.readthedocs.io/en/latest/user/quickstart/>
