# NAC 会务 Agent 制品

本目录包含 RFC-0004 定义的 NAC Agent artifact。

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

## 快速使用

在制品目录中执行：

```bash
cd agent/meeting-agent
nac deploy --dry-run
nac dev
nac smoke staging
nac test staging
nac chat staging -m '2026年8月4日 10:00-11:00 有哪些小会议室可用？'
```

如果尚未配置 NAC 项目，请先按 `nexau-artifact-builder` skill 的说明执行 `nac --project-id <project-id> init`。

## 环境变量

工具默认通过环境变量或工具参数读取运行上下文：

- `MEETING_API_BASE_URL`：会务 FastAPI 地址，默认 `http://127.0.0.1:8000`；
- `MEETING_API_TIMEOUT_SECONDS`：HTTP 超时时间，默认 `30` 秒；
- `MEETING_WORKSPACE_ID` 或 `WORKSPACE_ID`：默认 `default`；
- `MEETING_ACTOR_ID` 或 `ACTOR_ID_FALLBACK`：默认 `demo-user`；
- `MEETING_AUTH_TOKEN` 或 `AUTH_TOKEN`：平台用户认证 token；
- `MEETING_DEMO_CREDENTIALS`：显式 demo 登录凭据 JSON；
- `MEETING_DEMO_USERNAME` / `MEETING_DEMO_PASSWORD`：无 JSON 凭据时的 demo 登录兜底；
- `TIMEZONE`：默认 `Asia/Shanghai`。

`agent.yaml` 不写入 `base_url`、`api_key`、`sandbox_config`、`tracers` 或任何密钥；模型连接信息由 NAC 平台按模型卡注入。

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

工具会补齐 `workspace_id`、`actor_id`、`idempotency_key`、`expected_state_revision` 和 `dry_run`，并保留 FastAPI 返回的 `request_id`、`state_revision`、错误码和建议。

## 本地静态验证

```bash
cd agent/meeting-agent
python3 -m json.tool nexau.json
python3 -m py_compile custom_tools/meeting_tools.py
grep -R "base_url\|api_key\|sandbox_config\|tracers" agent.yaml || true
```

## 验收场景

核心验收见 `docs/rfcs/0004-nac-meeting-agent-artifact.md` 的测试方案。建议至少覆盖：

1. 查询会议室列表，确认不包含 502；
2. 下周二 10:00-11:00 查询小会议室，503/506 可用，505 因周二不可用排除；
3. 明天中午预约活动室，因午餐规则拒绝；
4. 自然语言配置 504 全天维修后改为下午停用，规则、日历、平面图一致；
5. 创建会议室一+会议室二组合预约后，成员房间不可分别预约；
6. 取消预约后释放时段并可重新预约；
7. 检查 NAC trace 中工具名、FastAPI path、请求体摘要、响应 `ok/error`、`request_id`、`state_revision` 和 `provider/model`。
