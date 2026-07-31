# Agent Instructions

本仓库是北坡内部黑客马拉松第八组的作品，当前主题是本地可运行的会务系统。

## 项目目标

交付一个本地可运行的会务系统，支持登录用户查询会议室、配置不可预约规则、创建/取消/修改预约，并通过日历与平面图直观理解会议室状态。

## RFC 源文档

实现和后续设计必须以 RFC 为单一事实来源：

| RFC | 主题 | 说明 |
|---|---|---|
| [RFC-0001](./docs/rfcs/0001-meeting-room-domain.md) | 会务系统领域模型与规则引擎 | 房间、组合空间、规则、预约、冲突校验、状态版本 |
| [RFC-0002](./docs/rfcs/0002-fastapi-api-agent-contract.md) | FastAPI 后端 API 与 Agent Tool 契约 | FastAPI、SQLite、本地登录、OpenAPI、幂等、状态版本、错误码 |
| [RFC-0003](./docs/rfcs/0003-nextjs-frontend-interaction.md) | Next.js 前端交互设计 | 登录、会议室列表、日历、自然语言查询、规则配置、预约详情、平面图 |

## 源码目录结构

```text
/
├── AGENTS.md
├── README.md
├── docs/rfcs/
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── auth/
│   │   ├── core/
│   │   ├── domain/
│   │   ├── nl/
│   │   ├── repositories/
│   │   ├── schemas/
│   │   └── services/
│   ├── scripts/
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── app/
│   ├── components/
│   ├── lib/api/
│   ├── lib/state/
│   ├── assets/floor-plan/
│   ├── styles/
│   └── tests/
├── acceptance/
├── demo/
└── diagrams/
```

## 目录职责

| 目录 | 用途 |
|---|---|
| `backend/` | FastAPI 后端源码、领域模型、规则引擎、SQLite 仓储、API 路由、后端测试 |
| `frontend/` | Next.js 前端源码、页面、组件、API Client、状态管理、静态 SVG 平面图资源 |
| `docs/rfcs/` | RFC 设计源文档；实现和后续设计以 RFC 为单一事实来源 |
| `acceptance/` | 端到端验收场景、手动验证脚本、检查清单 |
| `demo/` | 演示账号、演示数据、seed 脚本和演示流程 |
| `diagrams/` | 架构图、流程图、时序图、平面图源文件 |

## 后续实现约定

1. 先阅读对应 RFC，再修改实现代码；不要把规则硬编码在前端或 Agent prompt 中。
2. 领域模型、规则引擎、组合空间约束和状态版本由后端 `backend/app/domain/` 统一维护。
3. FastAPI 是前端和 Agent Tool 的唯一后端边界；Next.js 不直接访问 SQLite。
4. 自然语言配置直接写入系统状态；自然语言预约先返回候选，用户确认后再创建。
5. 所有写操作必须考虑 `idempotency_key`、`expected_state_revision` 和结构化错误返回。
6. 前端只展示 FastAPI 返回的结构化状态；冲突、午餐、临时禁用、组合空间约束都由后端判断。
7. 本期不接入真实 NAC Agent、不做管理员/成员分级、不做真实地图服务、不做多实例并发控制。
8. 新增目录或占位说明时，优先补充到对应源码或辅助目录，并在 README 中保持索引可追踪。

## 核心验收场景

- 登录后可以查询会议室列表，默认空间包含活动室、会议室一、会议室二、503、505、506。
- 下周二 10:00-11:00 查询小会议室时，503、506 可用，505 因周二全天不可用被排除。
- 明天中午预约活动室时，因午餐规则被拒绝。
- 创建会议室一+会议室二组合预约后，成员房间不能再被分别预约。
- “504 全天临时维修”后改为“只停用下午”时，只更新同一条规则。
- 取消预约后对应时段释放，并可重新预约。
- 平面图状态必须与日历、规则和预约状态一致。
- Swagger/OpenAPI 必须能展示所有 API、请求和响应模型。
