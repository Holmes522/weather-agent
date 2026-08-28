# 对话式天气 Agent 能力地图

| Module id | Responsibility | Depends on |
|---|---|---|
| `location-understanding` | 多城市提取、动态地理编码、城市名纠错 | — |
| `conversational-intent` | 问题意图识别、按需回答、多轮确认 | `location-understanding` |
| `chat-presentation` | 向后兼容的多城市 JSON 与网页消息展示 | `location-understanding`, `conversational-intent` |

Build order: `location-understanding` → `conversational-intent` → `chat-presentation`
