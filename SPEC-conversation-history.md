# Spec: 匿名历史会话与侧边栏

## Objective

为晴问增加常见 AI 聊天产品的会话管理体验：桌面端左侧显示历史会话，用户可以创建、切换和删除会话；右侧显示当前会话的完整消息。历史与天气上下文按同一会话 ID 隔离。

## Tech Stack and Commands

- Python 3.9+、Flask、进程内线程安全存储、原生 HTML/CSS/JavaScript、pytest。
- 测试：`.\.venv\Scripts\python.exe -m pytest -q`
- Python 检查：`.\.venv\Scripts\python.exe -m compileall -q .`
- JavaScript 检查：`node --check static\app.js`
- 运行：`.\.venv\Scripts\python.exe app.py`

## API Contract

所有会话接口使用服务端签发的匿名、HttpOnly、SameSite=Lax 浏览器 Cookie 隔离数据；Cookie 不是账户认证，不能替代正式登录。

- `GET /api/conversations`：按最近更新时间倒序返回当前浏览器的会话摘要。
- `POST /api/conversations`：创建空会话，返回 `201`。
- `GET /api/conversations/<session_id>`：返回会话摘要和可重新渲染的消息。
- `DELETE /api/conversations/<session_id>`：幂等删除会话及其天气上下文，返回 `204`。

摘要字段：`id`、`title`、`created_at`、`updated_at`、`message_count`。消息字段：`role`、`content`，Agent 回复可额外包含经过 JSON 复制的 `payload`。既有 `POST /chat` 请求和响应保持兼容。

## Project Structure

- `session_store.py`：会话元数据、展示消息、上下文和线程安全 CRUD。
- `conversation_history.py`：匿名浏览器 Cookie、REST 会话接口和成功回复归档。
- `app.py`：把聊天回复交给历史模块保存，同时保持 `/chat` 兼容。
- `templates/index.html`：侧边栏和移动端控制按钮。
- `static/app.js`：加载、新建、切换、删除和重放历史消息。
- `static/styles.css`：桌面双栏与移动抽屉布局。
- `tests/`：存储、API 和页面契约测试。

## Testing Strategy

- 单元测试：标题生成、消息上限、排序、所有者隔离和删除上下文。
- Flask 集成测试：创建、聊天归档、列表、详情、删除和非法 ID。
- 浏览器验证：新建两段会话、切换后重放、删除、移动端抽屉、键盘焦点、控制台和网络请求。

## Boundaries

- Always：服务端校验会话 ID；按匿名 Cookie 隔离；输出用 `textContent`；每个匿名浏览器最多保留最近 100 段会话和每段最近 100 条展示消息；删除或淘汰时同时清理天气上下文。
- Ask first：引入数据库、账户登录、跨设备同步、导出或分享会话。
- Never：把聊天历史放进 URL；使用 `innerHTML` 渲染消息；把匿名 ID 当成真正身份认证；把其他浏览器的会话返回给当前请求。

## Success Criteria

1. 桌面端左侧可见“新建对话”和按最近使用排序的历史列表。
2. 新建会话后右侧清空并显示欢迎页；第一条消息自动成为最多 36 字符的标题。
3. 切换会话能恢复用户消息、AI 文本和天气卡片；各会话的城市上下文互不串线。
4. 删除会话后无法再读取，同时清除其多轮天气上下文。
5. 320px 下侧边栏变为可关闭抽屉，所有控件支持键盘并有可访问名称。
6. Flask 重启后历史清空；README 明确这是内存版限制和后续数据库升级方向。
