# North Hackathon Team 8 Meeting

这是北坡内部黑客马拉松第八组的作品。

本项目用于沉淀第八组在黑客马拉松期间产出的会议、技能与协作资产。

## 当前内容

- `docs/deployment.md`：会务系统正式部署手册，覆盖本地开发、演示验收、后端/前端启动、SQLite 初始化、运维和检查清单。
- `.skills/ui-ux-pro-max/`：UI/UX Pro Max Skill
- `.skills/taste/`：Taste Skill

## 源码目录结构

```text
/
├── AGENTS.md
├── README.md
├── docs/
│   ├── deployment.md
│   └── rfcs/
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

- `docs/deployment.md`：会务系统正式部署手册，覆盖本地开发、演示验收、后端/前端启动、SQLite 初始化、运维和检查清单。
- `backend/`：FastAPI 后端源码、领域模型、规则引擎、SQLite 仓储、API 路由、后端测试。
- `frontend/`：Next.js 前端源码、页面、组件、API Client、状态管理、静态 SVG 平面图资源。
- `docs/rfcs/`：RFC 设计源文档；实现和后续设计以 RFC 为单一事实来源。
- `acceptance/`：端到端验收场景、手动验证脚本、检查清单。
- `demo/`：演示账号、演示数据、seed 脚本和演示流程。
- `diagrams/`：架构图、流程图、时序图、平面图源文件。
