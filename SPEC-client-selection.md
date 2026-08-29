# Client Selection Persistence Specification

## Goal

用户离开配置页或刷新聊天页后，天气服务和 AI 模型保持上一次主动选择，直到用户再次切换。

## Browser behavior

- 聊天页同时提供天气服务选择器和 AI 模型选择器（没有 AI 配置时显示天气模式）。
- 选择天气服务后，把 provider ID 写入 `localStorage`。
- 选择 AI 模型后，调用 `PATCH /api/llm/active`，成功后只把配置 ID 写入 `localStorage`。
- 页面加载时仅在保存的 ID 仍存在于当前选项中时恢复；否则使用服务端当前值。
- 从配置页新增模型成功后保存返回的安全配置 ID，回到聊天页自动选中新模型。

## Security

- API Key、Base URL 和完整模型配置不得写入 `localStorage`、DOM data 属性或聊天请求。
- 聊天请求只携带 `provider` 与可选 `llm_id`。

## Acceptance tests

- 模板包含两个可访问的选择器和已保存模型列表。
- 前端脚本只使用约定的两个非敏感 storage key。
- 刷新后恢复有效选择；无效旧 ID 自动回退。
