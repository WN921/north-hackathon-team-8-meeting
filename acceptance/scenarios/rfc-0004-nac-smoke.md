# RFC-0004 NAC 会务 Agent smoke 场景

## 目标

验证 NAC Agent artifact 与 FastAPI 边界是否符合 RFC-0004，同时不绕过后端直接操作 SQLite。

## 前置条件

- `nac` CLI 版本 >= `0.4.1`。
- NAC Gateway AK:SK 可用于数据面请求；项目管理 API 需要 PAT，不能用 AK:SK 代替。
- FastAPI 后端已在 `MEETING_API_BASE_URL` 可达，并能用 demo 账号登录。

## 脚本

- `acceptance/scripts/nac_gateway_smoke.sh`：验证 NAC Gateway AK:SK 连通性。
- `acceptance/scripts/rfc_contract_smoke.py`：验证 FastAPI/RFC 契约、规则、预约、取消、日历、平面图与 Agent artifact 结构。

## 验收点

1. NAC CLI 版本满足要求。
2. `nac chat hack-8` 可用 AK:SK 通过 Gateway 返回 OK。
3. Agent artifact 包含 RFC-0004 要求的工具绑定。
4. FastAPI 返回 `ok/meta.state_revision`，写操作支持 `idempotency_key` 与 `expected_state_revision`。
5. 固定规则、组合空间约束、午餐规则和取消释放均符合 RFC 预期。
