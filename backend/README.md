# 后端源码结构

`backend/` 是 FastAPI 后端源码根目录。实现必须优先遵循 `docs/rfcs/` 中的 RFC，尤其是 RFC-0001 与 RFC-0002。

## 目录职责

- `app/main.py`：FastAPI 应用入口、路由注册、全局异常处理、OpenAPI 元数据。
- `app/api/`：API 边界。
  - `routes/`：按资源拆分 FastAPI `APIRouter`。
  - `deps.py`：依赖注入、本地登录上下文、数据库会话。
- `app/auth/`：本地登录与用户会话相关逻辑。
- `app/core/`：配置、常量、错误码、工具函数。
- `app/domain/`：领域模型与规则引擎，是后端的核心边界。
  - `models/`：领域模型，如房间、组合空间、规则、预约、状态版本。
  - `booking.py`：预约领域服务。
  - `composite_room.py`：组合空间约束。
  - `room.py`：会议室领域服务。
  - `rule_engine.py`：不可预约规则、午餐规则、临时禁用规则等规则引擎。
  - `state_revision.py`：状态版本与乐观并发控制。
- `app/nl/`：自然语言配置和自然语言预约候选生成。
- `app/repositories/`：SQLite 仓储，隔离数据库访问。
- `app/schemas/`：Pydantic 请求/响应模型。
- `app/services/`：应用服务，编排领域服务、仓储和外部边界。
- `scripts/`：数据库初始化、seed 数据、本地演示脚本。
- `tests/`：后端单元测试与集成测试。

## 实现原则

1. 领域模型、规则引擎、组合空间约束和状态版本由 `app/domain/` 统一维护。
2. FastAPI 是前端和 Agent Tool 的唯一后端边界；不要绕过 API 直接访问 SQLite。
3. 写操作统一考虑 `idempotency_key`、`expected_state_revision` 和结构化错误返回。
4. 自然语言配置直接写入系统状态；自然语言预约先返回候选，用户确认后再创建。
5. OpenAPI/Swagger 必须能展示所有 API、请求和响应模型。
