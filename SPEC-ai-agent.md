# Spec: 小型 AI 天气 Agent

## Objective

把现有规则式天气查询器升级为只读型 AI Agent。配置大模型后，用户可以进行普通中文聊天；涉及天气时，模型通过受限的 `get_weather` 工具取得真实天气数据后作答。未配置模型时，现有天气查询继续可用。

## Tech Stack

- Python 3.9+、Flask 3.x、Requests 2.x、pytest。
- OpenAI Chat Completions 兼容协议；不新增模型 SDK 依赖。
- 兼容 OpenAI、DeepSeek、OpenRouter，以及本机 Ollama 的 `/v1/chat/completions`。

## Commands

```powershell
python -m pytest -q
python -m compileall app.py agent.py llm_client.py
node --check static\app.js
node --check static\settings.js
python app.py
```

## API Contract

`POST /chat` 保留现有请求字段：

```json
{"message":"深圳明天适合跑步吗？","session_id":"demo-1","provider":"openmeteo"}
```

启用模型后的成功响应仍保留 `session_id`、`answer`、`provider` 和天气兼容字段，并新增：

```json
{
  "mode": "agent",
  "model": "provider-visible-name",
  "tool_used": true,
  "display_mode": "text"
}
```

无天气工具调用时不返回伪造的天气数据。未配置模型且输入不是可解析天气问题时返回 `422 AI_NOT_CONFIGURED`。模型或模型响应异常统一返回 `502 AI_UNAVAILABLE`，不暴露 Key、上游响应或内部异常。

开发环境增加：

- `GET /api/llm`：仅返回是否配置、显示名称和模型名，绝不返回 Key。
- `POST /api/llm`：仅允许本机调用，运行时新增或替换模型客户端。

生产环境继续隐藏全部运行时配置接口；模型凭据必须来自环境变量。

## Agent and Tool Contract

Agent 只有一个只读工具 `get_weather`：

```json
{
  "cities": ["深圳", "广州"],
  "day_offset": 1,
  "detail": "advice"
}
```

- `cities`：1–5 个城市，每项 1–80 字符。
- `day_offset`：只允许 0、1、2。
- `detail`：`full`、`temperature`、`humidity`、`wind`、`rain`、`advice`、`brief`。
- 所有模型参数在代码中重新验证；模型输出不拥有任何权限。
- 每轮最多执行 2 个工具调用，模型最终回复最多 4000 字符。

## Project Structure

```text
agent.py                 # 模型/工具编排与参数校验
llm_client.py            # OpenAI 兼容 HTTP 客户端及响应校验
app.py                   # /chat、/api/llm 与天气工具适配
session_store.py         # 有上限的对话消息历史和天气上下文
templates/settings.html  # 天气与 AI 模型配置
static/settings.js       # 本机模型配置交互
tests/                   # 客户端、编排、配置和 API 测试
```

## Code Style

```python
def validate_tool_arguments(arguments: object) -> WeatherToolInput:
    """只接受契约内字段；模型输出始终视为不可信输入。"""
```

模块使用类型提示、显式异常和小型不可变数据对象。外部 JSON 只在边界校验一次，内部代码使用已验证对象。

## Testing Strategy

- 单元测试：模型请求格式、响应解析、错误隐藏、URL 校验、工具参数校验和轮次上限。
- Flask 集成测试：普通聊天、天气工具、多轮历史、无模型回退、运行时配置和生产禁用。
- 所有模型与天气上游均使用测试替身；完整测试不访问互联网。
- 浏览器运行时验证：配置状态、普通文本、天气工具回答、控制台、安全头和 320/768/1024/1440px 布局。

## Security and Privacy Boundaries

- Always：Key 仅驻留环境变量或当前 Python 进程；请求/响应限长；HTTPS 外部模型端点；仅允许显式 loopback 使用 HTTP；禁用重定向；模型结果仅作为文本或经校验工具参数处理。
- Ask first：增加写操作工具、网页浏览、文件访问、命令执行、跨用户持久记忆或身份认证。
- Never：提交 Key；把 Key、系统提示或其他会话发送给用户；执行模型生成的代码；把模型文本写入 `innerHTML`；允许任意工具名或任意日期范围。

用户消息和有限历史会发送给其配置的模型服务。内存历史最多保留最近 12 条消息，进程重启即清空。

## Success Criteria

1. 配置模型后，“你好”“解释一下湿度”可获得普通 AI 回复。
2. “深圳明天适合跑步吗？”触发天气工具，最终建议引用真实天气数据。
3. “那广州呢？”能利用有限对话上下文继续交流。
4. 明确询问完整天气时仍可展示天气卡；单项和建议问题保持文本回答。
5. 未配置模型时，现有天气查询全部兼容；普通聊天得到清晰配置提示。
6. 非法工具名、畸形 JSON、过多城市、越界日期和第三方异常均安全失败。
7. 运行时配置不返回或持久化 Key，生产环境配置入口保持关闭。

## Official Sources

- OpenAI function calling: https://developers.openai.com/api/docs/guides/function-calling
- OpenAI Chat API: https://developers.openai.com/api/reference/resources/chat
- DeepSeek tool calls: https://api-docs.deepseek.com/guides/tool_calls/
- OpenRouter tool calling: https://openrouter.ai/docs/guides/features/tool-calling
- Ollama OpenAI compatibility: https://docs.ollama.com/api/openai-compatibility
