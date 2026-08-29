# 对话式天气 Agent 能力地图

| Module id | Responsibility | Depends on |
|---|---|---|
| `location-understanding` | 多城市提取、动态地理编码、城市名纠错 | — |
| `conversational-intent` | 问题意图识别、按需回答、多轮确认 | `location-understanding` |
| `chat-presentation` | 向后兼容的多城市 JSON 与网页消息展示 | `location-understanding`, `conversational-intent` |
| `llm-chat` | OpenAI 兼容模型调用、普通聊天与有限历史上下文 | — |
| `weather-tool` | 将现有天气能力封装为参数受验证的只读 Agent 工具 | `location-understanding`, `conversational-intent` |
| `agent-orchestrator` | 驱动模型、天气工具和最终回复，限制工具轮次 | `llm-chat`, `weather-tool` |
| `model-config` | 本机运行时模型配置和生产环境变量配置 | `llm-chat` |
| `agent-presentation` | 展示 AI 状态、通用文本回复和天气卡片 | `agent-orchestrator`, `model-config`, `chat-presentation` |
| `conversation-history` | 匿名会话 CRUD、历史消息重放和响应式侧边栏 | `agent-presentation` |
| `regional-weather-search` | 全国主要城市或省级范围的实时降雨/雷雨批量扫描，并继承范围追问上下文 | `conversational-intent`, `weather-tool` |

Build order: `location-understanding` → `conversational-intent` → `chat-presentation`

AI upgrade build order: `llm-chat` → `weather-tool` → `agent-orchestrator` → `model-config` → `agent-presentation`

History upgrade build order: `agent-presentation` → `conversation-history`

Regional search build order: `weather batch contract` → `regional query parser` → `session context` → `/chat` integration
