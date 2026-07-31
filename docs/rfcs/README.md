
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
| [RFC-0001](./0001-meeting-room-domain.md) | 会务系统领域模型与规则引擎 | draft | P1 | 定义 Topic A 会务领域、固定空间关系、规则状态和前端/API/Agent 共享语义 |
| [RFC-0002](./0002-fastapi-api-agent-contract.md) | FastAPI 后端 API 与 Agent Tool 契约 | draft | P1 | requires RFC-0001; related RFC-0003；覆盖本地 Agent runtime、nex-agi/Nex-N2-Pro、OpenAPI 契约和完整 API 端口 |
| [RFC-0003](./0003-nextjs-frontend-interaction.md) | Next.js 前端交互设计 | draft | P1 | requires RFC-0001, RFC-0002；覆盖本地 Web 启动入口、真实前端操作闭环、Agent 驱动页面和静态 SVG 平面图 |

## RFC 编号规则

- 使用 4 位数字编号，如 `0001`
- 编号顺序分配，不跳号
- 被 superseded 的 RFC 保留原编号
- 相关功能的 RFC 使用连续编号

## 本期会务系统范围摘要

- 只覆盖 Topic A 会务系统，不覆盖 Topic B 点餐系统。
- 本地可运行 Web 应用由 Next.js、FastAPI 和本地 Agent runtime 组成。
- 自然语言配置、自然语言预约候选、结构化状态写入和冲突校验都必须真实进入系统状态。
- LLM API 固定使用 nex-agi/Nex-N2-Pro。
- 固定空间关系不可改变：活动室午餐不可预约；会议室一/二可合并；503/505/506 是小会议室；505 每周二全天不可用。
- 本期默认初始化 504 作为动态禁用和平面图演示房间，502 不作为默认房间或可用结果。
- 本期不接入真实日历、支付、餐厅、会议室或其他外部生产系统；管理员/RBAC、强制调整预约和真实地图服务留作后续。
