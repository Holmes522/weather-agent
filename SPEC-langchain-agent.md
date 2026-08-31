# Spec: LangChain Agent Engine

## Objective

在不改变现有 `/chat`、天气 Provider、导出、历史对话和前端契约的前提下，使用 LangChain `create_agent` 接管模型与天气工具的调用循环。默认启用 LangChain，引入 `native` 回滚模式，并保留应用层对工具参数、调用次数、响应大小和第三方异常的严格控制。

## Tech Stack

- Python 3.10+
- LangChain `>=1.3.18,<1.4`
- Flask 3.1、Requests 2.32、Pytest 8
- 现有 OpenAI Chat Completions 兼容客户端继续负责端点与响应安全校验

版本依据：LangChain v1 使用 `langchain.agents.create_agent` 作为标准 Agent API；该 API 运行于 LangGraph Runtime。LangChain/LangGraph v1 要求 Python 3.10 以上。

## Commands

- 安装：`python -m pip install -r requirements-dev.txt`
- 焦点测试：`python -m pytest tests/test_langchain_agent.py tests/test_ai_chat.py -q`
- 完整测试：`python -m pytest -q`
- 编译：`python -m compileall -q . -x "[\\/]\.venv[\\/]"`
- 前端语法：`node --check static/app.js`

## Project Structure

- `langchain_agent.py`：LangChain 模型适配器、只读天气工具和 Agent 运行入口
- `agent.py`：保留共享工具输入、Prompt、验证规则与原生回滚引擎
- `app.py`：根据配置选择 Agent 运行器，不承载 LangChain 细节
- `config.py`：校验 `AGENT_ENGINE=langchain|native`
- `tests/test_langchain_agent.py`：LangChain 编排、安全边界与兼容性测试

## Runtime Contract

1. Flask 继续从会话存储读取最近 12 条普通消息。
2. LangChain 模型适配器将标准消息转换为现有客户端契约；API Key 不进入 Agent state、日志或响应。
3. `create_agent` 只注册 `get_weather`，工具内部再次调用现有严格验证函数。
4. `ToolCallLimitMiddleware` 将每轮天气工具调用限制为 2 次；`ModelCallLimitMiddleware` 将模型调用限制为 3 次。
5. 工具结果必须是可序列化字典且不超过 20,000 字符。
6. 返回 `AgentRunResult`，让 `/chat` 保持现有天气卡、上下文和导出行为。
7. `AGENT_ENGINE=native` 使用原有运行器，作为明确回滚路径；不做静默降级。

## Code Style

```python
def run_langchain_agent(
    client: ChatModel,
    history: Sequence[Dict[str, str]],
    user_message: str,
    weather_tool: WeatherTool,
) -> AgentRunResult:
    """执行 LangChain 图式 Agent，同时保留应用层安全边界。"""
```

- 使用类型标注和不可变结果类型。
- 框架异常转换为现有 `AgentError`/`LLMClientError`，不向用户暴露内部堆栈。
- 不复制天气业务逻辑；复用 `validate_weather_tool_arguments` 和现有 Provider 执行函数。

## Testing Strategy

- RED：LangChain 普通聊天、一次工具调用、超出工具上限和非法参数测试先失败。
- GREEN：实现最小模型适配器、工具与 `create_agent` 入口。
- API 集成：默认 LangChain 与显式 native 返回兼容 JSON；响应标识实际引擎。
- 回归：现有测试全部通过，测试不得访问真实模型或天气服务。
- CI：Python 3.10 与 3.13 安装依赖、运行测试和编译检查。

## Boundaries

- Always：验证所有模型生成参数；限制调用轮数；隐藏上游错误；保持 API 兼容；提交前扫描密钥。
- Ask first：增加写操作工具、RAG、长期记忆、账户系统或新的外部服务。
- Never：把 API Key 放入 Prompt/Agent state；静默回退到另一引擎；让模型直接执行 URL、命令或文件操作。

## Success Criteria

1. 默认 `langchain` 引擎可完成普通聊天和真实天气工具闭环。
2. `native` 引擎仍可通过环境变量启用，现有行为保持可回滚。
3. `/chat` 的天气结果、历史上下文、导出和错误格式保持兼容，并增加实际 `agent_engine` 标识。
4. 每轮最多 2 次工具调用、最多 3 次模型调用，非法工具参数不会执行天气客户端。
5. 项目要求与 CI 更新为 Python 3.10+，本地虚拟环境安装成功。
6. 完整测试、编译检查、前端语法检查和远端 CI 全部通过。

## Explicitly Out of Scope

- RAG、向量数据库、多智能体、通用规划器
- LangGraph 持久化 Checkpointer（现阶段继续以现有会话存储为唯一事实源）
- 流式输出和异步 Provider 调用
