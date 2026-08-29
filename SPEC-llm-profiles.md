# AI Model Profiles Specification

## Goal

本机配置页可保存多个 AI 模型连接并自由切换，而不是每次新增时覆盖旧配置。

## Supported presets

- OpenAI、DeepSeek、OpenRouter
- 智谱 GLM、Moonshot Kimi、阿里云百炼通义千问、火山方舟豆包、Google Gemini
- 本机 Ollama
- 任意 OpenAI Chat Completions 兼容 HTTPS 接口

模型 ID 始终由用户按对应控制台填写；页面示例不作为硬编码限制。Claude 直连接口协议不同，本版本可通过 OpenRouter 或自建 OpenAI 兼容网关使用。

## API contract

- `GET /api/llm` 返回当前 `llm` 和 `models` 列表。
- `POST /api/llm` 验证并新增配置，新增项成为当前项，但保留已有项。
- `PATCH /api/llm/active` 接收 `{\"id\": \"...\"}` 并切换当前项。
- `POST /chat` 可选接收 `llm_id`，只允许使用注册表中已存在的配置。
- 所有响应只包含随机配置 ID、服务显示名、模型 ID 和当前状态；不返回 API Key。

## State and limits

- 配置和密钥只保存在当前 Python 进程内，重启后由环境变量配置重新初始化。
- 最多保存 20 个配置；达到上限时拒绝新增，避免无界内存增长。
- 注册表线程安全；读取客户端和切换当前项均为原子操作。

## Acceptance tests

- 连续新增两个配置后两项都存在，且第二项为当前项。
- 可切回第一项，并在聊天时使用指定配置。
- 未知配置 ID、无效端点、缺失模型或密钥返回 422。
- API 响应和页面源码不包含提交的密钥。
