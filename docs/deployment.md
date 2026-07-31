# 会务系统正式部署手册

本文档是北坡内部黑客马拉松第八组会务系统的正式部署手册，面向本地开发、演示验收和后续单机部署。部署目标是启动 FastAPI 后端、Next.js 前端和必要的本地数据初始化流程，使系统能够支持登录、会议室查询、规则配置、预约创建/取消/修改、日历视图和平面图状态展示。

> 当前仓库的实现状态需要部署人员注意：RFC-0001、RFC-0002、RFC-0003 已定义目标架构和验收契约，但当前代码仍在补齐后端 API、SQLite 初始化脚本、前端 API Client 和端到端流程。本手册采用“正式部署流程 + 当前实现状态检查”的写法，避免把尚未实现的能力误认为已上线能力。

## 1. 部署范围

### 1.1 本次部署包含

- FastAPI 后端服务；
- Next.js 前端服务；
- SQLite 本地数据库；
- 演示账号与演示数据初始化；
- Swagger/OpenAPI 文档；
- 本地验收场景验证；
- 静态 SVG 平面图资源；
- 本地 Agent runtime 配置位。

### 1.2 本次部署不包含

- 真实 NAC Agent 接入；
- 真实日历、支付、餐厅、会议室系统接入；
- 管理员/成员分级权限；
- 多实例并发控制；
- 真实地图服务；
- 生产级高可用、自动扩缩容和集中式监控。

### 1.3 目标运行架构

```text
用户浏览器
  -> Next.js 前端
  -> FastAPI 后端
  -> SQLite 数据库
  -> 领域模型/规则引擎
```

FastAPI 是前端和 Agent Tool 的唯一后端边界。Next.js 不直接访问 SQLite，业务规则、冲突校验、状态版本、幂等控制均由后端维护。

## 2. 环境要求

### 2.1 系统工具

| 工具 | 版本要求 | 用途 |
|---|---:|---|
| Python | `3.12` 或更高 | 后端运行 |
| Node.js | `20` 或更高 | 前端运行 |
| npm | 随 Node.js 安装 | 前端依赖安装 |
| Git | 最新稳定版 | 源码拉取与版本管理 |

### 2.2 目录要求

部署时建议使用项目根目录：

```bash
cd north-hackathon-team-8-meeting
```

### 2.3 环境变量

| 变量名 | 作用 | 示例值 |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | 前端访问后端 API 的地址 | `http://127.0.0.1:8000` |
| `LLM_PROVIDER` | 本地 Agent runtime provider | `nex-agi` |
| `LLM_MODEL` | 本地 Agent runtime model | `Nex-N2-Pro` |
| `NEX_AGI_API_KEY` | Nex-N2-Pro API Key | `***` |

> 如果当前部署只做本地基础验证，可以先不配置真实 LLM。但若执行 RFC 中要求的自然语言 Agent 验收，必须补齐 `LLM_PROVIDER`、`LLM_MODEL`、`NEX_AGI_API_KEY`。

## 3. 后端部署

### 3.1 创建虚拟环境

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell：

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3.2 安装后端依赖

```bash
pip install -e .
```

### 3.3 初始化 SQLite 数据库

后端使用 SQLite 作为本地数据库。部署时必须确保数据库包含：

- 演示账号；
- 默认会议室；
- 固定规则；
- 开放时段；
- 演示预约；
- 状态版本初始值。

当前仓库中 `demo/seed/` 用于沉淀演示数据，但截至本手册编写时，可执行的数据库初始化脚本仍需补齐。正式部署前必须完成以下任一动作：

1. 补齐并执行 `backend/scripts/init_db.py`；
2. 补齐并执行 `backend/scripts/seed_demo.py`；
3. 通过已实现的 API 完成初始数据写入。

推荐在后续补齐以下脚本：

```bash
python scripts/init_db.py
python scripts/seed_demo.py
```

### 3.4 配置后端环境变量

```bash
export LLM_PROVIDER=nex-agi
export LLM_MODEL=Nex-N2-Pro
export NEX_AGI_API_KEY=your-api-key
```

如果只做本地健康检查和基础 API 验证，可以暂不启动真实 Agent，但必须在部署记录中注明该限制。

### 3.5 启动 FastAPI

开发或演示调试时可使用：

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

单机部署或验收环境建议使用不带 `--reload` 的启动方式：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

启动后访问：

- API 服务：<http://127.0.0.1:8000>
- Swagger/OpenAPI：<http://127.0.0.1:8000/docs>
- ReDoc：<http://127.0.0.1:8000/redoc>

### 3.6 后端健康检查

```bash
curl -s http://127.0.0.1:8000/health
```

期望返回：

```json
{"status":"ok"}
```

> 当前 `backend/app/main.py` 已实现 `/health`。若后续 RFC-0002 要求 `/api/health` 包含 SQLite 可用性、LLM provider/model 和 `state_revision`，部署手册应同步更新。

## 4. 前端部署

### 4.1 安装前端依赖

```bash
cd frontend
npm install
```

### 4.2 配置前端 API 地址

前端通过 `NEXT_PUBLIC_API_BASE_URL` 指向 FastAPI。

```bash
export NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

如果后续补充 `.env.local`，建议写入：

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

### 4.3 启动 Next.js

```bash
npm run dev
```

启动后访问：

- 前端页面：<http://localhost:3000>

### 4.4 前端健康检查

访问：

```text
http://localhost:3000
```

确认可以进入登录页。

> 当前前端页面骨架已存在，但 API Client 仍处于占位状态。正式部署前必须补齐登录、会议室、规则、预约、日历和平面图相关 API 调用。

## 5. 演示数据部署

### 5.1 演示账号

| 用户名 | 密码 | 说明 |
|---|---|---|
| `demo` | `demo-password` | 本地演示账号，业务权限为普通成员 |

### 5.2 默认会议室

部署完成后，默认空间应包含：

- 活动室
- 会议室一
- 会议室二
- 503
- 505
- 506

### 5.3 固定规则

部署完成后，应至少包含以下固定规则：

- 活动室午餐时段不可预约；
- 505 每周二全天不可用；
- 会议室一和会议室二可组合使用。

### 5.4 演示数据检查

部署完成后，应能验证：

- 会议室列表存在；
- 规则列表存在；
- 日历状态可解释；
- 平面图状态可解释；
- 演示账号可以登录；
- 写操作返回 `state_revision`。

## 6. 验收流程

### 6.1 后端验收

访问 Swagger/OpenAPI：

```text
http://127.0.0.1:8000/docs
```

确认以下内容：

- 登录 API 存在；
- 会议室查询 API 存在；
- 规则配置 API 存在；
- 预约创建/修改/取消 API 存在；
- 日历 API 存在；
- 平面图 API 存在；
- 请求和响应模型包含 `idempotency_key`、`expected_state_revision`、`state_revision`；
- 错误响应为结构化错误模型。

### 6.2 前端验收

访问：

```text
http://localhost:3000
```

确认以下内容：

- 可以进入登录页；
- 登录后可进入首页；
- 可以查看会议室列表；
- 可以进入日历视图；
- 可以进入自然语言查询入口；
- 可以配置规则；
- 可以查看预约详情；
- 可以取消或修改预约；
- 平面图状态与日历、规则和预约状态一致。

### 6.3 核心验收场景

按照 `acceptance/README.md` 执行：

- 登录后查询会议室列表；
- 查询下周二 10:00-11:00 的小会议室；
- 验证 503、506 可用，505 因周二全天不可用被排除；
- 验证明天中午预约活动室时因午餐规则被拒绝；
- 验证组合空间预约后成员房间不能再被分别预约；
- 验证“504 全天临时维修”后改为“只停用下午”时只更新同一条规则；
- 验证取消预约后对应时段释放并可重新预约；
- 验证平面图状态与日历、规则和预约状态一致；
- 验证 Swagger/OpenAPI 能展示所有 API、请求和响应模型。

## 7. 运维要求

### 7.1 启动顺序

推荐顺序：

1. 启动 SQLite 初始化流程；
2. 启动 FastAPI 后端；
3. 确认 `/health` 和 Swagger 正常；
4. 启动 Next.js 前端；
5. 执行端到端验收。

### 7.2 日志

后端日志应至少记录：

- 服务启动状态；
- API 请求错误；
- 规则冲突；
- 状态版本冲突；
- 幂等键冲突；
- LLM provider/model 状态。

前端日志应至少记录：

- API 请求失败；
- 登录失败；
- 状态版本冲突；
- 用户可操作的错误提示。

### 7.3 备份

SQLite 数据库文件应定期备份。备份策略建议：

- 每次演示前备份初始库；
- 每次重大规则变更前备份当前库；
- 每次验收完成后归档验收库。

### 7.4 回滚

如果部署后数据异常，推荐回滚方式：

1. 停止前端；
2. 停止后端；
3. 恢复备份数据库；
4. 重新启动后端；
5. 重新启动前端；
6. 执行健康检查和验收流程。

## 8. 常见问题

### 8.1 后端启动失败

请确认：

- Python 版本是否为 `3.12` 或更高；
- 虚拟环境是否已激活；
- 是否已执行 `pip install -e .`；
- `8000` 端口是否被占用。

### 8.2 前端启动失败

请确认：

- Node.js 版本是否为 `20` 或更高；
- 是否已执行 `npm install`；
- `3000` 端口是否被占用；
- `NEXT_PUBLIC_API_BASE_URL` 是否正确。

### 8.3 登录后无法访问业务页面

请确认：

- 后端登录 API 是否已实现；
- 前端 API Client 是否已接入登录流程；
- 浏览器控制台是否存在跨域或接口地址错误；
- 认证态是否被正确保存。

### 8.4 数据库状态异常

如果 SQLite 数据异常：

1. 停止后端；
2. 恢复备份数据库；
3. 重新执行初始化或 seed；
4. 重启后端；
5. 重新执行验收。

### 8.5 LLM 配置缺失

如果自然语言功能无法使用：

- 检查 `LLM_PROVIDER` 是否为 `nex-agi`；
- 检查 `LLM_MODEL` 是否为 `Nex-N2-Pro`；
- 检查 `NEX_AGI_API_KEY` 是否有效；
- 确认网络或 mock LLM 策略是否符合当前验收要求。

## 9. 部署检查清单

- [ ] 后端 Python 虚拟环境创建完成；
- [ ] 后端依赖安装完成；
- [ ] SQLite 初始化脚本已补齐并执行；
- [ ] 演示账号可用；
- [ ] 默认会议室已存在；
- [ ] 固定规则已存在；
- [ ] 后端服务可访问；
- [ ] `/health` 返回正常；
- [ ] Swagger/OpenAPI 可访问；
- [ ] 前端依赖安装完成；
- [ ] `NEXT_PUBLIC_API_BASE_URL` 已配置；
- [ ] 前端服务可访问；
- [ ] 登录流程可完成；
- [ ] 会议室列表可查询；
- [ ] 规则配置可完成；
- [ ] 预约创建/修改/取消可完成；
- [ ] 日历状态正确；
- [ ] 平面图状态正确；
- [ ] `acceptance/README.md` 中核心场景全部通过。

## 10. 当前实现状态提示

部署人员应在部署记录中记录以下当前状态：

- `backend/app/main.py` 当前仅实现 `/health`；
- `frontend/lib/api/index.ts` 当前仅定义 API 地址常量；
- `demo/seed/` 当前仅作为数据目录占位；
- 真实 Agent runtime、完整 API 路由、前端 API Client 仍需补齐后才能进入正式验收。
