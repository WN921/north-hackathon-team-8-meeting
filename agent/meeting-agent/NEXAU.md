# Meeting Agent Artifact

本目录是 RFC-0004 定义的 NAC 会务 Agent 制品。

- 入口：`nexau.json`
- Agent 配置：`agent.yaml`
- 系统提示词：`systemprompt.md`
- 工具定义：`tools/*.tool.yaml`
- 工具实现：`custom_tools/meeting_tools.py`
- 会务知识库：`skills/meeting-system/`

运行和部署时应在 `agent/meeting-agent/` 下执行 `nac dev`、`nac deploy`、`nac smoke`、`nac test` 或 `nac chat`。不要把 `tools/`、`custom_tools/`、`skills/` 放到仓库根目录。
