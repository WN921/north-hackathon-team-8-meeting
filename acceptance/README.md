# Acceptance

本目录用于沉淀端到端验收场景、脚本和检查清单。

## 核心场景

- 登录后查询会议室列表，默认空间包含活动室、会议室一、会议室二、503、505、506。
- 下周二 10:00-11:00 查询小会议室，503、506 可用，505 因周二全天不可用被排除。
- 明天中午预约活动室时，因午餐规则被拒绝。
- 创建会议室一+会议室二组合预约后，成员房间不能再被分别预约。
- “504 全天临时维修”后改为“只停用下午”时，只更新同一条规则。
- 取消预约后对应时段释放，并可重新预约。
- 平面图状态必须与日历、规则和预约状态一致。
- Swagger/OpenAPI 必须能展示所有 API、请求和响应模型。
- NAC Agent 制品验收：见 `agent/README.md`、`docs/rfcs/0004-nac-meeting-agent-artifact.md` 与 `docs/rfcs/0005-nac-context-platform-agent-integration.md`，覆盖制品解析、工具绑定、FastAPI 调用、状态版本、幂等、trace 验收和云端部署上下文。
- 本地制品自检：`python3 acceptance/scripts/nac-agent-smoke.py`，用于在不访问真实 FastAPI 的情况下验证工具请求体、幂等字段、状态版本字段和统一 envelope。
- NAC Gateway 连通性：`NAC_AK=... NAC_SK=... bash acceptance/scripts/nac_gateway_smoke.sh`，仅验证 AK:SK 对数据面 Gateway 是否可用，不打印凭据。
- NAC Agent 流式对话：`NAC_AK=... NAC_SK=... bash acceptance/scripts/nac_stream_smoke.sh`，默认使用 `NAC_ENVIRONMENT=test`，通过 `nac chat --stdin --compact --json` 验证页面 BFF 依赖的流式 Agent 对话可通。
- RFC 契约自检：`python3 acceptance/scripts/rfc_contract_smoke.py`，默认 dry-run 验证 FastAPI/OpenAPI、固定规则、组合空间、预约取消、NL 候选、日历、平面图和 Agent artifact 工具绑定。
