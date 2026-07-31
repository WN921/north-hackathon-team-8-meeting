# FastAPI API 与工具契约

本参考对齐 RFC-0002。Agent 工具只封装 HTTP API，不直接访问数据库。

## 认证上下文

- 工具优先使用平台注入的 `auth_token`；
- 缺失 token 时，仅在显式 demo 模式调用 `auth_meeting_api` 或读取 `MEETING_DEMO_TOKEN`；
- 只读 demo 凭据不得用于写操作；
- 认证失败必须返回 `UNAUTHORIZED` 或 `DEMO_REQUIRED`，并标注 `demo_actor`。

## 公共写操作字段

写操作请求体必须补齐：

- `workspace_id`，默认 `default`；
- `actor_id`，默认 `demo-user`；
- `idempotency_key`；
- `expected_state_revision`；
- `dry_run`，当后端端点支持时使用。

## 主要 API

| 工具 | API |
|---|---|
| `get_meeting_state` | `GET /api/health`、`GET /api/rooms`、`GET /api/rules` |
| `query_availability` | `POST /api/availability:query` |
| `check_availability` | `POST /api/availability:check` |
| `nl_booking_candidates` | `POST /api/nl/bookings:candidates` |
| `configure_meeting_state` | `POST /api/nl/configure` |
| `manage_rooms` | 房间和开放时段结构化 API |
| `manage_rules` | 规则列表、详情、创建、更新、删除 |
| `manage_bookings` | 预约列表、详情、创建、取消、修改 |
| `get_calendar` | `GET /api/calendar` |
| `get_floor_plan` | `GET /api/floor-plan` |

## 错误码

工具必须透传并解释以下错误码：

- `STATE_REVISION_CONFLICT`：状态版本冲突，需要重新读取当前状态并再次确认；
- `PROTECTED_RULE`：受保护规则不能被普通用户删除或覆盖；
- `LLM_PROVIDER_ERROR`：后端自然语言 provider/model/API key 配置错误；
- `BOOKING_CONFLICT`：预约冲突；
- `IDEMPOTENCY_KEY_REUSED`：同一幂等键被用于不同请求；
- `UNAUTHORIZED` / `DEMO_REQUIRED`：认证或演示凭据问题；
- `TRANSPORT_ERROR` / `TIMEOUT` / `INVALID_RESPONSE` / `TOOL_EXCEPTION`：工具层传输或异常问题。

## 统一返回结构

工具返回应保留：

```json
{
  "ok": true,
  "request_id": "req_xxx",
  "data": {},
  "warnings": [],
  "meta": {
    "state_revision": 13,
    "server_time": "2026-07-31T10:00:00+08:00",
    "timezone": "Asia/Shanghai"
  }
}
```

失败时保留 `error.code`、`error.message`、`error.details`、`error.suggestions`，并补充 `http_status`、`tool_name`、`recoverable`、`next_action`。
