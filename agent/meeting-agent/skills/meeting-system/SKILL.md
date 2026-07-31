---
name: meeting-system
description: |
  会务系统知识库。需要理解或操作会务 Agent 时加载本 skill：领域模型、FastAPI 契约、自然语言流程、前端状态展示和验收边界都放在 references/ 下。
---

# 会务系统知识库

本 skill 是 `meeting_assistant` 的会务系统知识入口。加载技能后，先读取 `{path_to_skill_folder}/references/INDEX.md`，再根据任务读取对应 reference；不要凭记忆直接构造未列出的文件路径。

## 何时使用

- 查询会议室、可用时段、日历或平面图状态；
- 解释预约冲突、午餐规则、固定空间关系、动态禁用规则；
- 创建、取消、修改预约；
- 配置规则、房间、开放时段；
- 核对 RFC-0002 API 路径、公共字段、错误码、幂等和状态版本；
- 需要向用户解释前端闭环和验收场景。

## 知识库导航方法

1. 先读取 `{path_to_skill_folder}/references/INDEX.md`；
2. 查询领域约束读 `references/domain.md`；
3. 查询工具/API 契约读 `references/api-contract.md`；
4. 查询自然语言、前端展示和验收闭环读 `references/frontend-flow.md`。

## references 文件清单

- `references/INDEX.md`：索引文件；
- `references/domain.md`：领域模型、固定空间关系、规则引擎和状态版本；
- `references/api-contract.md`：FastAPI API、工具封装、错误码、幂等和状态版本；
- `references/frontend-flow.md`：前端交互、自然语言流程、日历/平面图闭环和验收场景。

## 工具使用提醒

- 只通过 Agent 工具调用 FastAPI 操作会务系统；
- 不直接访问 SQLite、仓储、领域服务代码；
- 写操作必须先确认，并由工具补齐 `idempotency_key`、`expected_state_revision`、`workspace_id`、`actor_id` 和 `dry_run`；
- 遇到 `STATE_REVISION_CONFLICT`、`PROTECTED_RULE`、`LLM_PROVIDER_ERROR`、`BOOKING_CONFLICT` 等结构化错误时，保留错误码并解释下一步。
