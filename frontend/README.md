# 前端源码结构

`frontend/` 是 Next.js 前端源码根目录。实现必须优先遵循 `docs/rfcs/` 中的 RFC，尤其是 RFC-0003。

## 目录职责

- `app/`：Next.js App Router 页面与全局样式。
  - `(auth)/login/`：本地登录页面。
  - `(main)/`：登录后主功能区。
  - `(main)/rooms/`：会议室列表与查询。
  - `(main)/calendar/`：日历视图。
  - `(main)/nl/query/`：自然语言查询与会话入口。
  - `(main)/rules/`：不可预约规则配置。
  - `(main)/bookings/[id]/`：预约详情、取消与修改。
  - `(main)/floor-plan/`：静态 SVG 平面图状态展示。
- `components/`：可复用 UI 组件，例如房间卡片、日历网格、规则表单、预约详情卡片。
- `lib/api/`：FastAPI API Client，负责请求封装、错误处理和状态版本字段传递。
- `lib/state/`：前端状态管理，只展示 FastAPI 返回的结构化状态。
- `assets/floor-plan/`：静态 SVG 平面图资源。
- `styles/`：全局样式和主题变量。
- `tests/`：前端测试。

## 实现原则

1. 前端只展示 FastAPI 返回的结构化状态；冲突、午餐、临时禁用、组合空间约束均由后端判断。
2. 自然语言预约先返回候选，用户确认后再调用创建预约 API。
3. 平面图状态必须与日历、规则和预约状态保持一致，由后端结构化状态驱动。
4. 不把业务规则硬编码在前端或 Agent prompt 中。
