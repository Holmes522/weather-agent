# Spec: conversational-intent

## Objective

根据用户真正询问的天气维度组织自然回复，而不是每次都倾倒所有指标。

## Intent Contract

- `full`：明确询问天气总体情况或详情。
- `temperature`、`humidity`、`wind`、`rain`：只回答对应指标。
- `outing`：结合降雨、温度、风和天气状况给出出门建议，并询问是否需要完整天气。
- `brief`：无法归类时给出简短天气结论并提示可继续追问。
- 用户在 `outing` 后回复“需要/可以/好”，复用上次城市和日期，以 `full` 回复。
- “那后天呢？”复用上次城市和上次意图。

## Testing

- 纯函数单元测试覆盖意图和回复文本。
- Flask 集成测试覆盖出行建议、湿度单项、多轮确认及多城市。

## Boundaries

- Always：回复完全基于结构化天气字段。
- Never：编造空气质量、体感温度或天气 API 未提供的信息。

## Success Criteria

1. “深圳明天出门要带什么”只给建议，不展示完整指标卡。
2. “明天湿度如何”只回答湿度。
3. 只有 `full` 意图展示完整温度、天气、湿度和风速。
