# Spec: Explicit LangGraph Weather Agent Workflow

## Objective

将默认 AI Agent 从 LangChain `create_agent` 的预构建循环升级为显式 LangGraph `StateGraph`。模型决策、工具执行和最终回答校验必须成为命名节点，并通过条件边形成有界循环；现有天气查询、RAG、历史记录、导出和错误响应保持兼容。

用户可观察的成功结果：`POST /chat` 返回 `agent_engine: "langgraph"`，天气和 RAG 行为不退化；旧环境变量 `AGENT_ENGINE=langchain` 仍可启动，但规范化为新引擎；`native` 继续作为显式回滚路径。

## Assumptions

1. 本次目标是显式编排和可维护性，不同时迁移 Redis/PostgreSQL 持久化。
2. 现有 `InMemorySessionStore` 继续负责对话历史；LangGraph Checkpointer 留作后续独立升级。
3. 不增加新的模型、天气或网络服务，也不改变 API Key 的保存方式。
4. LangChain 模型适配器和工具 schema 继续复用，避免重写已验证的 OpenAI-compatible 边界。

## Tech Stack

- Python 3.10+
- LangChain `>=1.3.18,<1.4.0`
- LangGraph `>=1.2,<1.3`
- `StateGraph`、`MessagesState`、`ToolNode`
- Flask 与现有同步 `POST /chat`

官方设计依据：

- https://docs.langchain.com/oss/python/langgraph/graph-api
- https://docs.langchain.com/oss/python/langchain/tools#toolnode
- https://docs.langchain.com/oss/python/langgraph/use-graph-api
- https://docs.langchain.com/oss/python/releases/langgraph-v1

## Commands

- 焦点测试：`.\.venv\Scripts\python.exe -m pytest tests\test_langgraph_agent.py tests\test_config.py tests\test_ai_chat.py -q`
- 完整测试：`.\.venv\Scripts\python.exe -m pytest -q`
- 编译：`.\.venv\Scripts\python.exe -m compileall -q app.py agent.py langchain_agent.py langgraph_agent.py config.py`
- 依赖检查：`.\.venv\Scripts\python.exe -m pip check`

## Architecture

```text
START
  |
  v
model ---- tool_calls? ----> tools
  |                           |
  | no tool                   |
  v                           |
finalize <--------------------+
  |
  v
 END
```

- `model`：调用已绑定白名单工具的模型；在工具执行前验证工具名、参数和本轮调用预算。
- `tools`：使用 `ToolNode` 执行天气和知识检索；同一模型回合内的独立工具调用可由 LangGraph 并行调度。
- `finalize`：只接受不含工具调用、非空且不超过 4000 字符的最终 AI 文本。
- 条件边：模型有工具调用时进入 `tools`，否则进入 `finalize`；工具执行后固定返回 `model`。
- 运行状态：`messages` 使用 LangGraph 消息 reducer，`answer` 由 `finalize` 写入。

## Runtime Contract

1. 每轮最多 4 次模型调用、3 次全部工具调用、2 次天气工具、1 次知识检索。
2. 不支持的工具名和越界参数必须在执行前失败。
3. Tool 异常不得被模型错误文本吞掉；天气 Provider、地理编码和知识检索异常继续交给 Flask 统一映射。
4. 图递归上限作为第二层 DoS 防护；业务预算是第一层终止条件。
5. 模型输出、天气响应和检索内容均视为不可信数据，不授予新权限。
6. `AGENT_ENGINE` 接受 `langgraph`、兼容别名 `langchain` 和回滚值 `native`；未知值启动失败。

## Project Structure

- `langgraph_agent.py`：显式图状态、节点、边和运行入口。
- `langchain_agent.py`：保留模型适配器、工具 schema 和共享消息转换/校验。
- `app.py`：默认选择 `run_langgraph_agent`。
- `tests/test_langgraph_agent.py`：图节点、路由、限制和工具组合测试。
- `tests/test_config.py`、`tests/test_ai_chat.py`：引擎配置与 API 契约测试。

## Testing Strategy

- RED：先要求显式图暴露 `model/tools/finalize` 节点并验证 API 返回 `langgraph`。
- GREEN：实现最小状态图，复用既有模型和工具边界。
- 回归：现有 LangChain Agent 测试、天气/RAG/API/历史/导出测试全部通过。
- 安全：验证模型无法绕过工具白名单、调用预算和最终输出限制。
- 测试不访问真实模型、天气服务或知识来源网站。

## Boundaries

- Always：保留严格参数校验、调用上限、通用错误响应和 `native` 回滚。
- Ask first：数据库 Checkpointer、跨进程长期记忆、流式 API、人工审批 UI。
- Never：把 API Key 放入图状态；执行模型生成的命令；静默回退到另一个 Agent 引擎。

## Success Criteria

1. 默认配置和 `/chat` 响应均报告 `langgraph`。
2. 编译图包含 `model`、`tools`、`finalize` 三个命名节点和有界循环。
3. 普通聊天、天气工具、天气 + RAG 并行工具调用均返回原有结构。
4. 工具与模型调用上限在执行前生效，异常不会被吞掉。
5. `AGENT_ENGINE=langchain` 被兼容规范化，`native` 路径保持可用。
6. 完整测试、编译、依赖、安全与远端 CI 通过。

## Explicitly Out of Scope

- Redis/PostgreSQL Checkpointer 与跨实例恢复
- SSE/WebSocket 流式进度
- Human-in-the-loop 审批页面
- 多 Agent 或子图架构
