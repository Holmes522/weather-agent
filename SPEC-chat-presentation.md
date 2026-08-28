# Spec: chat-presentation

## Objective

让 `/chat` 和网页同时支持多城市及对话式简短回复，并保持现有单城市调用方兼容。

## API Contract

成功响应继续保留 `city`、`date`、`weather`、`answer`，它们对应第一个结果；新增：

```json
{
  "intent": "full",
  "display_mode": "weather_cards",
  "cities": ["深圳", "广州"],
  "results": [
    {
      "city": "深圳",
      "date": "明天",
      "answer": "...",
      "weather": {}
    }
  ]
}
```

- `display_mode=weather_cards`：网页逐城市显示完整天气卡。
- `display_mode=text`：网页只显示 `answer` 对话气泡。
- 所有错误继续使用现有 `{ "error": { "code", "message" } }`。

## Success Criteria

1. 旧客户端读取首个 `city` 和 `weather` 不会失败。
2. 新客户端可遍历 `results` 显示所有城市。
3. 非完整天气问题在网页中不显示未被询问的指标。
