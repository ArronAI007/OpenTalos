# M8 桌面侧栏与工作流

**状态**: Sidebar Workflows Complete

**日期**: 2026-11-16

## 上游对照

固定参考：

- Repository: `yetone/magpie`
- Commit: `9dcec6751323674bc1ad9f52b13ec8fc081b4de6`
- `internal/gui/assets/index.html`
- `internal/gui/assets/navpages.js`
- `internal/gui/plugins/sessions/client.js`
- `internal/gui/plugins/library/client.js`
- `internal/gui/plugins/routing/client.js`
- `internal/gui/plugins/redact/client.js`

OpenTalos 保留自己的 Python API、Next.js UI 和现有聊天能力，不复制 Wails/Go 实现。

## 左侧栏

侧栏按 Magpie 的信息架构分组：

### 使用

- Agent → `/agents`
- 会话 → `/conversations`
- 资源库 → `/resources`

### 模型

- 供应商 → `/providers`
- 路由 → `/routing`
- 路由组 → `/routing-groups`
- 网关 → `/gateway`

### 观测

- 用量 → `/usage`
- 脱敏 → `/privacy`

### 扩展

- 插件 → `/plugins`

### 底部

- 设置 → `/settings`
- Gateway 实时健康状态和当前地址

## 页面能力

### Agent

- 快速上手 3 步引导。
- 本机已安装 Agent 摘要。
- 自建 ReAct Agent 创建和使用。
- 外部 Agent 发现、模型绑定、配置事务、Profile 和 Library。

### 会话

- 活跃与归档会话。
- 标题/Agent 搜索。
- 新建、置顶、归档和恢复。
- 打开原会话。

### 资源库

- 技能发现、添加和移除。
- MCP Server 列表和启停。
- OpenTalos 与外部 Agent 汇总。
- Instructions、MCP、Skills、Hooks、Environment、Subagents、Commands、Plugins 托管条目。

### 路由

- Provider 账号和模型路由目录。
- 模型 ID 复制。
- 配额耗尽账号提示。
- Gateway 最近路由轨迹、尝试次数和配额过滤数量。

### 路由组

- 创建路由组。
- `order`、`rotate`、`usage`、`smart`、`pace`、`weight` 模式。
- 目标权重语法 `target | weight` 或 `target @ weight`。
- 嵌套组目标、会话粘性、模式修改和删除。

### 网关

- Gateway 健康、请求、Token 和账号状态。
- 最近请求表。
- 共享网络、TLS 配置、命名 Key、预算和访问范围。

### 用量

- Gateway 请求与 Token。
- Provider 账号汇总。
- Agent 运行 Token 和成本。
- 最近运行报告入口。

### 脱敏

- 隐私开关与 fail-closed。
- 内置和自定义规则。
- 脱敏测试、占位符有效期和审计。

### 插件

- 插件仓库发现。
- 本地插件安装。
- 启停、完整性校验和卸载。
- Provider、Middleware 和 UI slot 元数据。

### 设置

- API、Gateway、Provider 账号和 Agent 状态。
- 主题切换。
- Skills、MCP、Memory、Runs、Eval、AgentRL、DeepResearch 和安全中心高级入口。

## 保留功能

以下原 OpenTalos 页面没有删除，并从设置页保留入口：

- Skills
- MCP
- Memory
- Run history
- Agent evaluation
- AgentRL
- DeepResearch
- Security and sharing

## 验证

- 导航元数据测试覆盖四个分组和全部十项主导航。
- 会话过滤测试覆盖搜索、置顶排序和空标题。
- 路由权重解析测试覆盖 `|` 与 `@` 语法。
- Gateway URL 测试覆盖环境变量和尾部斜杠。
- 浏览器烟测逐页打开 `/conversations`、`/resources`、`/providers`、`/routing`、`/routing-groups`、`/gateway`、`/usage`、`/privacy`、`/plugins`、`/settings`，标题和页面均可见。

## 后续边界

- 外部 Agent 原生 session 文件的统一索引、恢复和删除仍可继续扩展。
- Magpie Settings 中的同步、OTLP、插件页面渲染等深层子页尚未完全复制。
- Routing 页面当前展示 OpenTalos 可路由模型和 Gateway trace，不复刻 Magpie 的 Wails 实时可视化组件。
