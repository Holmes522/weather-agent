# Spec: Weather Knowledge RAG

## Objective

在现有实时天气 Agent 中增加一个默认可用、无需额外 API Key 的本地 RAG 知识库。Agent 可以在用户询问穿衣、雷雨、暴雨、高温、寒潮和户外活动建议时检索权威资料，把检索片段与实时天气数据一起交给模型，并在 `/chat` 与可视化界面显示实际引用来源。

实时温度、湿度、风速和降雨仍只能来自天气 Provider；RAG 只提供相对稳定的安全与出行知识，不作为实时天气事实来源。

## Tech Stack

- Python 3.10+
- LangChain `>=1.3.18,<1.4`
- `langchain_core.vectorstores.InMemoryVectorStore`
- 自定义本地词法 Hash Embeddings，实现 LangChain `Embeddings` 接口
- 仓库内 Markdown 知识文档，不增加远程 Embedding、数据库或模型依赖

LangChain 官方将 RAG 拆成文档、分块、Embedding、Vector Store 与 Retriever，并把“由 Agent 决定何时检索”定义为 Agentic RAG：

- https://docs.langchain.com/oss/python/langchain/retrieval
- https://docs.langchain.com/oss/python/langgraph/agentic-rag
- https://docs.langchain.com/oss/python/integrations/embeddings

## Commands

- 检索测试：`python -m pytest tests/test_knowledge_base.py -q`
- Agent 测试：`python -m pytest tests/test_langchain_agent.py tests/test_ai_chat.py -q`
- 完整测试：`python -m pytest -q`
- 编译：`python -m compileall -q app.py agent.py langchain_agent.py knowledge_base.py`
- 前端语法：`node --check static/app.js`

## Project Structure

- `knowledge/`：经过人工筛选的只读 Markdown 天气安全资料
- `knowledge_base.py`：文档校验、分块、本地 Embedding、向量检索和结果类型
- `langchain_agent.py`：注册 `search_weather_knowledge` 只读工具
- `agent.py`：Agent 返回结构增加知识来源
- `app.py`：应用启动时构建知识库，并在 Agent 响应中返回 RAG 元数据
- `static/app.js` / `static/styles.css`：回答气泡显示可访问的参考资料链接

## Runtime Contract

1. 应用只读取仓库内固定 `knowledge/*.md`，不接受用户文件路径或 URL。
2. 文档必须包含标题、来源名称、HTTPS 来源 URL 与主题；限制文件数、文件大小、分块数和分块长度。
3. 查询长度最多 200 字符，每次最多返回 3 个片段；低于相关度阈值时返回空结果。
4. `search_weather_knowledge` 每轮最多调用 1 次；全部工具每轮最多 3 次；模型每轮最多 4 次。
5. 检索内容按不可信数据处理，Prompt 明确禁止执行其中的指令；代码权限不由文档控制。
6. `/chat` 增加 `rag_used` 和 `knowledge_sources`，旧字段保持兼容。
7. 历史记录保存来源元数据，页面恢复后继续显示；链接只接受后端校验过的 HTTPS URL。

## Code Style

```python
@dataclass(frozen=True)
class KnowledgeChunk:
    content: str
    title: str
    section: str
    source_name: str
    source_url: str
    score: float
```

- 检索层不依赖 Flask，也不调用 LLM。
- Agent 编排与知识库加载分离，测试可注入假检索器。
- 不把文档正文直接返回浏览器，只返回模型回答和来源元数据。

## Testing Strategy

- RED：相关中文查询能命中正确资料、无关问题不返回资料、危险元数据被拒绝。
- GREEN：实现最小知识加载与向量检索。
- Agent：模型可以调用知识工具；严格验证查询；RAG 来源进入结果；调用次数受限。
- API/UI：`rag_used` 和来源结构可归档、恢复、渲染，且不使用 `innerHTML`。
- 回归：测试不访问真实天气、模型、Embedding 或知识来源网站。

## Boundaries

- Always：实时天气使用 API；文档固定且有来源；限制检索与上下文大小；来源 URL 校验；模型输出按不可信数据处理。
- Ask first：用户上传、在线网页抓取、远程 Embedding、Chroma/FAISS/数据库、知识库后台编辑。
- Never：从用户输入拼接文件路径；执行知识文档中的指令；让 RAG 覆盖天气 API；把 API Key 写入文档或向量元数据。

## Success Criteria

1. “雷雨天适合爬山吗”“暴雨开车注意什么”“高温跑步怎么安排”等问题可检索相应权威片段。
2. Agent 可同时调用实时天气和知识检索，并生成结合两类数据的回答。
3. `/chat` 对实际检索回答返回 `rag_used=true` 和去重后的来源。
4. 可视化界面与历史对话显示来源名称和可点击链接。
5. 普通聊天和仅查询温度等问题不会被强制附加无关知识。
6. 完整测试、编译、前端语法、安全审查与远端 CI 通过。

## Explicitly Out of Scope

- 用户文件上传、OCR、PDF/Word 动态入库
- 云端向量数据库与跨进程持久索引
- 在线网页自动抓取和定时同步
- 医疗诊断、灾害预警替代或个性化健康建议
