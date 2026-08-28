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

- 当前不支持自动地理编码；新增城市需修改 `parser.py` 城市表。
- 当前按 `Asia/Shanghai` 作为解析相对日期的默认时区；预报聚合使用城市自身时区。

## Multi-provider Extension

- [x] 定义统一 `WeatherProvider` 接口并保持现有 OpenWeather 客户端兼容。
- [x] 增加和风天气 v1 实时天气和每日预报客户端。
- [x] 允许通过 `WEATHER_PROVIDER` 或请求 `provider` 选择服务。
- [x] 验证 API Host 白名单、第三方响应字段和统一错误语义。
