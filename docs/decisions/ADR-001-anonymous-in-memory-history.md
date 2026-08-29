# ADR-001: 使用匿名 Cookie 和进程内历史存储

## Status

Accepted

## Date

2026-08-29

## Context

晴问需要常见 AI 聊天产品的历史侧边栏，但当前 MVP 没有账户、数据库或 Redis，并且既有天气上下文已经按 `session_id` 存放在 Python 进程内存中。把完整历史放入浏览器 `localStorage` 会扩大聊天内容在客户端脚本中的暴露面，也无法与服务端天气上下文形成一个一致的删除边界。

## Decision

服务端签发随机的 HttpOnly、SameSite=Lax 匿名 Cookie，用它限定会话列表、详情和删除操作的浏览器范围。历史消息、可重放回复载荷和天气上下文统一保存在 `InMemorySessionStore` 中；既有只使用 `session_id` 的 `/chat` 调用保持兼容。

## Alternatives Considered

- 浏览器 `localStorage`：实现更少，但聊天记录可被页面脚本读取，且删除时难以保证服务端上下文同步清理。
- SQLite：能跨重启保存，但引入持久化迁移、并发和数据保留策略，超出当前免费 MVP 范围。
- Redis 或托管数据库：适合生产多实例和账户体系，但增加部署成本与运维配置。

## Consequences

- 同一浏览器可以新建、切换、恢复和删除当前进程中的历史会话。
- Flask 重启、免费托管实例休眠重启或多 Worker 部署会丢失或分裂历史。
- 匿名 Cookie 不是身份认证，不能提供账户级安全、跨设备同步或可靠的数据主体管理。
- 生产化升级应引入正式登录、持久化存储、保留期限和账户级删除能力。
