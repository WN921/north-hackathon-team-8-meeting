# Project RFCs

本目录包含项目的 RFC（Request for Comments）文档。

## RFC 是什么

RFC 用于记录技术设计决策。每个 RFC 描述一个特定功能、架构变更或技术决策，包括：

- **问题背景**：为什么需要这个变更
- **设计方案**：如何解决问题
- **权衡取舍**：考虑过的替代方案
- **实现状态**：当前进度

## RFC 状态

| 状态 | 说明 |
|------|------|
| `draft` | 草稿，正在讨论 |
| `accepted` | 已接受，待实现 |
| `implementing` | 实现中 |
| `implemented` | 已实现 |
| `superseded` | 被更新的 RFC 取代 |
| `rejected` | 已拒绝 |

## RFC 列表

### 会务系统

| RFC | 标题 | 状态 | 优先级 | 依赖/关联 |
|-----|------|------|--------|-----------|
| [RFC-0001](./0001-meeting-room-domain.md) | 会务系统领域模型与规则引擎 | draft | P1 | - |
| [RFC-0002](./0002-fastapi-api-agent-contract.md) | FastAPI 后端 API 与 Agent Tool 契约 | draft | P1 | requires RFC-0001; related RFC-0003 |
| [RFC-0003](./0003-nextjs-frontend-interaction.md) | Next.js 前端交互设计 | draft | P1 | requires RFC-0001, RFC-0002 |

## RFC 编号规则

- 使用 4 位数字编号，如 `0001`
- 编号顺序分配，不跳号
- 被 superseded 的 RFC 保留原编号
- 相关功能的 RFC 使用连续编号
