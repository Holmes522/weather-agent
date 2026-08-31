# Implementation Plan: Weather Query Agent MVP

## Overview

实现一个规则驱动的中文天气查询 Agent：解析输入 → 读取会话上下文 → 调用对应 OpenWeatherMap 接口 → 归一化结果 → 返回稳定 JSON。

## Architecture Decisions

- 使用 `session_id` 作为内存字典键；不引入 Flask session 或数据库，符合 MVP 约束。
- 今天使用 Current Weather API；明天/后天使用 5 Day / 3 Hour Forecast API，并按本地日期聚合 3 小时预报条目。
- 城市表保存显示名、英文查询名和国家码，避免把任意用户文本直接传给上游。
- 天气接口、解析器、会话存储和 Flask 路由分离，以便用小测试覆盖。
- 对第三方响应只读取允许字段；缺字段时返回上游数据错误，不暴露原始响应。

## Dependency Graph

```text
config → parser → session_store
config → weather_client → app route
parser + session_store + weather_client → /chat
```

## Task List

### Phase 1: Foundation

- [x] Task 1: 定义配置、城市/日期解析和会话状态接口。
- [x] Task 2: 实现 OpenWeatherMap 客户端和天气结果归一化。

### Checkpoint: Foundation

- [x] 解析器与客户端单元测试通过。

### Phase 2: Core API

- [x] Task 3: 实现 Flask 应用工厂、`POST /chat` 与统一错误响应。
- [x] Task 4: 覆盖会话多轮查询及上游错误的 API 集成测试。

### Checkpoint: Core API

- [x] `/chat` 能在 mock 上游数据下完成今天/明天/后天查询。

### Phase 3: Delivery

- [x] Task 5: 添加依赖、环境变量模板、README 和 curl 示例。
- [x] Task 6: 完成测试、静态检查、秘密扫描和代码审查。

### Checkpoint: Complete

- [x] 全部测试通过。
- [x] `.env` 不在版本控制中。
- [x] 文档能让新用户从安装到 curl 测试走通。

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| 3 小时预报时间戳跨时区 | High | 使用 API 返回的 `city.timezone` 转换到城市本地日期 |
| 预报接口缺少目标日期条目 | Medium | 返回稳定的 `FORECAST_UNAVAILABLE`，不猜测天气 |
| 上游字段变化或异常 | Medium | 做字段类型/存在性校验并隐藏原始错误 |
| 内存会话多进程不共享 | Medium | README 明确 MVP 限制，后续可替换存储实现 |

## Open Questions

- 动态地理编码已由 `location-understanding` 模块实现；高流量时需要决定使用自托管还是商业兼容端点。
- 当前按 `Asia/Shanghai` 作为解析相对日期的默认时区；预报聚合使用城市自身时区。

## AI Agent Upgrade

1. 定义 OpenAI 兼容模型客户端和稳定的模型响应类型。
2. 定义只读 `get_weather` 工具、参数验证和最多两次工具调用的编排循环。
3. 在 `/chat` 中启用 Agent 路径，并保留无模型时的规则天气路径。
4. 增加开发环境模型配置接口与配置页面，生产环境仅使用环境变量。
5. 扩展内存会话为有上限的普通聊天历史，并保持天气上下文兼容。
6. 完成 API、浏览器、安全与回归验证后分阶段提交。

风险与缓解：模型输出不可信，因此工具名称和参数由代码白名单验证；模型服务可能超时或产生费用，因此设置超时、输出上限、历史上限、工具轮次上限和生产限流；自定义端点只允许 HTTPS，只有 loopback Ollama 可使用 HTTP。

## Conversation History Upgrade

1. 扩展内存存储，定义匿名会话摘要和可重放消息契约。
2. 增加会话 CRUD API，并在成功聊天后归档用户与 Agent 回复。
3. 实现桌面侧边栏、移动抽屉和新建/切换/删除交互。
4. 补充 README，完成自动化测试、安全审查和真实浏览器验证。

## Conversational Weather Upgrade

1. `location-understanding`：多城市解析 → 动态地理编码 → 纠错与缓存。
2. `conversational-intent`：意图分类 → 按需回复 → 多轮确认。
3. `chat-presentation`：兼容 JSON 扩展 → 多卡片/文本气泡展示。

风险与缓解：公共 Nominatim 受每秒一次限制，因此只对本地白名单外地点调用，使用进程内缓存和串行限速；后续可通过环境变量切换到自托管或商业兼容端点。

## Multi-provider Extension

- [x] 定义统一 `WeatherProvider` 接口并保持现有 OpenWeather 客户端兼容。
- [x] 增加和风天气 v1 实时天气和每日预报客户端。
- [x] 允许通过 `WEATHER_PROVIDER` 或请求 `provider` 选择服务。
- [x] 验证 API Host 白名单、第三方响应字段和统一错误语义。

## Export and AI Model Profiles Upgrade

1. 保存最近一次结构化天气快照，识别自然语言导出意图并实现有界临时下载存储。
2. 生成 DOCX、XLSX、PDF、Markdown，并通过重开与渲染检查文件有效性。
3. 将单一 AI 客户端替换为线程安全的多配置注册表，补充常见模型服务预设和切换 API。
4. 在配置页展示已保存模型，在聊天页增加 AI 选择器，并只持久化天气 provider ID 与模型配置 ID。
5. 完成焦点测试、完整回归、浏览器验证、安全审查和部署文档更新。

## Itinerary Weather Export Upgrade

1. 在天气导出能力内增加有界行程解析，区分出发地、目的地、顺序、每城停留天数和总天数。
2. 有顺序时按行程日逐城查询；无顺序时生成每城未来 N 天矩阵；Open-Meteo 同城多日只请求一次。
3. 导出文件逐行写入完整天气和出行建议，并增加天气驱动的出行清单。
4. 文件生成成功后返回纯下载响应，不在聊天框重复天气明细。
5. 用截图中的真实句式、无顺序矩阵、四种文件重开、浏览器和完整回归测试验证。

## LangChain Agent Engine Upgrade

1. 将 Python 基线提升到 3.10，固定 LangChain 1.3 稳定版本，并增加 `AGENT_ENGINE` 配置。
2. 新增 LangChain 模型适配器，让现有安全 HTTP 客户端继续支持已配置的 OpenAI 兼容模型。
3. 使用 `create_agent`、只读天气 Tool 和调用限制 Middleware 替换默认手写循环，同时保留 native 回滚路径。
4. 保持 `/chat`、天气卡、会话与导出契约兼容，在响应中暴露实际 Agent 引擎。
5. 完成焦点测试、完整回归、依赖审查、安全审查、README 与远端 CI。

## Weather Knowledge RAG Upgrade

1. 建立固定来源、只读、有限大小的天气安全 Markdown 知识库。
2. 使用 LangChain Embeddings 接口和 InMemoryVectorStore 实现无需外部 Key 的本地检索。
3. 把知识检索注册为 Agentic RAG 工具，与实时天气工具保持独立事实边界。
4. 在 `/chat`、当前聊天和历史对话中展示实际使用的权威来源。
5. 完成检索评测、Agent/API/UI 回归、安全审查、浏览器验证和远端 CI。
