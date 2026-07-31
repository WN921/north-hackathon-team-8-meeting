# NAC 会务 Agent 制品

本目录包含 RFC-0004 / RFC-0005 定义的 NAC Agent artifact。`meeting_assistant` 通过 `custom_tools/meeting_tools.py` 调用会务系统 FastAPI，不直接访问 SQLite、仓储或领域服务代码。

## 目录结构

```text
agent/
└── meeting-agent/
    ├── nexau.json
    ├── agent.yaml
    ├── systemprompt.md
    ├── NEXAU.md
    ├── tools/
    ├── custom_tools/
    └── skills/meeting-system/
```

## 云端对接模式

RFC-0005 的主路径是：

```text
NAC Cloud Runtime
  -> meeting_assistant
  -> custom_tools/meeting_tools.py
  -> 会务 FastAPI
  -> 领域服务 / SQLite
```

Agent 只做对话、意图识别、工具选择、候选解释和错误解释；FastAPI 仍是会务领域规则、冲突校验、幂等和状态版本的唯一执行来源。

## 快速使用

在制品目录中执行：

```bash
cd agent/meeting-agent
python3 -m json.tool nexau.json
python3 -m py_compile custom_tools/meeting_tools.py
python3 ../../acceptance/scripts/nac-agent-smoke.py
nac deploy hack-8 --yes --json
nac chat hack-8 -m '2026年8月5日 10:00-11:00 有哪些小会议室可用？'
nac smoke hack-8
nac test hack-8
```

本地开发时也可使用：

```bash
cd agent/meeting-agent
nac deploy --dry-run
nac dev
```

## NAC 项目配置

RFC-0005 使用的 NAC 项目配置项如下。真实 AK/SK、用户 token、demo 凭据必须写入 NAC secret 或本地安全环境，不得写入仓库、README、日志或 trace。

| 配置项 | 值/示例 | 是否可提交仓库 | 说明 |
|---|---|---:|---|
| `NAC_BASE_URL` | `https://nac-beta.xiaobei.top/` | 是 | NAC Agent API base URL |
| `NAC_ENVIRONMENT` | `hack-8` | 是 | NAC 部署环境 |
| `NAC_PROJECT_ID` | `e4ebe630-1c26-48d0-8d29-4563375ee959` | 是，但需确认项目公开性 | NAC 项目 ID |
| `NAC_AK` | `<secret>` | 否 | NAC 访问密钥 |
| `NAC_SK` | `<secret>` | 否 | NAC 访问密钥 |

## Agent 运行上下文

`custom_tools/meeting_tools.py` 通过环境变量读取 FastAPI 运行上下文：

| 变量名 | 默认值 | 说明 |
|---|---|---|
| `MEETING_API_BASE_URL` | `https://hackathon-8.qichangzheng.net` | NAC runtime 可达的会务 FastAPI 地址；不要使用调用者本地 `127.0.0.1` |
| `MEETING_API_TIMEOUT_SECONDS` | `30` | HTTP 超时时间 |
| `MEETING_WORKSPACE_ID` / `WORKSPACE_ID` | `default` | 会务工作空间 |
| `MEETING_ACTOR_ID` / `ACTOR_ID_FALLBACK` | `demo-user` | 写操作 actor |
| `MEETING_AUTH_TOKEN` / `AUTH_TOKEN` | 无 | 平台用户认证 token；缺失时只能走显式 demo 模式 |
| `MEETING_DEMO_CREDENTIALS` | 无 | 显式 demo 登录凭据 JSON |
| `MEETING_DEMO_USERNAME` / `MEETING_DEMO_PASSWORD` | `demo-user` / `demo-password` | 无 JSON 凭据时的 demo 登录兜底 |
| `TIMEZONE` | `Asia/Shanghai` | 时间解释时区 |

## 工具封装

业务工具都位于 `custom_tools/meeting_tools.py`，通过 HTTP 调用 RFC-0002 FastAPI API：

- `auth_meeting_api`
- `get_meeting_state`
- `query_availability`
- `check_availability`
- `nl_booking_candidates`
- `configure_meeting_state`
- `manage_rooms`
- `manage_rules`
- `manage_bookings`
- `get_calendar`
- `get_floor_plan`

查询类工具不发送写操作 envelope；`check_availability` 当前只发送 FastAPI `AvailabilityCheck` 支持字段，避免预检接口收到额外字段导致 422。写操作工具会补齐 `workspace_id`、`actor_id`、`idempotency_key`、`expected_state_revision` 和 `dry_run`；自然语言配置/预约候选的写前 dry-run 应先读取最新 `state_revision` 并显式传入。

## 本地静态验证

```bash
cd agent/meeting-agent
python3 -m json.tool nexau.json
python3 -m py_compile custom_tools/meeting_tools.py
grep -R "base_url\|api_key\|sandbox_config\|tracers" agent.yaml || true
grep -R "<NAC_AK_SECRET_VALUE>\|<NAC_SK_SECRET_VALUE>\|<MEETING_AUTH_TOKEN_VALUE>" . || true
```

## 验收场景

核心验收见 `docs/rfcs/0004-nac-meeting-agent-artifact.md` 与 `docs/rfcs/0005-nac-context-platform-agent-integration.md`。建议至少覆盖：

1. 查询会议室列表，确认不包含 502；
2. 下周二 10:00-11:00 查询小会议室，503/506 可用，505 因周二不可用排除；
3. 明天中午预约活动室，因午餐规则拒绝；
4. 自然语言配置 504 全天维修后改为下午停用，规则、日历、平面图一致；
5. 创建会议室一+会议室二组合预约后，成员房间不可分别预约；
6. 取消预约后释放时段并可重新预约；
7. 检查 NAC trace 中工具名、FastAPI path、请求体摘要、响应 `ok/error`、`request_id`、`state_revision` 和 `provider/model`。
