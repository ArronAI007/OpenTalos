# M6 Agent 平台

**状态**: Agent Platform Core Complete

**日期**: 2026-11-16

## 已实现

### 固定 Agent 目录

- 读取 M0 固定基线中的 87 个 Agent。
- 每个 Agent 都有稳定 ID、发现命令、安装提示和明确的兼容路径。
- Claude Code、Codex、Gemini CLI、OpenCode 提供原生配置适配器。
- 其余 Agent 使用明确的 manual Gateway 兼容路径；没有经过验证的原生格式时禁用自动写入。

### 安装发现

- 基于 PATH 命令和应用包发现已安装 Agent。
- 记录版本、安装路径、安装来源、配置位置和平台。
- macOS `.app` 从 `Info.plist` 读取版本。
- UI 默认只展示已安装 Agent，也可以查看完整 87 项目录。

### 模型绑定

- 从现有 Provider 控制面读取所有模型。
- 同时支持具体 `provider/account/model` 和 `group/name` 路由组。
- 不可用模型保留在列表中并显示禁用原因。
- 每个 Agent 保存主模型、模型短名单和 routing preference。
- Profile 在单个 SQLite 事务中恢复全部 Agent 绑定。

### 配置事务

- Claude Code JSON、Gemini CLI JSON、OpenCode JSON、Codex TOML 渲染器。
- 文件级互斥锁。
- 同目录临时文件、`fsync`、原子替换。
- 写入后字节校验、JSON/TOML 语法校验。
- 写入或验证失败自动回滚。
- 首次写入前保存原始字节，恢复操作可以精确恢复原始文件，或者删除首次托管时原本不存在的文件。

### 跨 Agent Library

支持四类资源：

- Instructions
- MCP Server
- Skill
- Subagent

Instructions 使用带唯一标记的托管块；MCP 使用唯一命名空间；Skill/Subagent 使用独立原生文件。移除时只删除 OpenTalos 托管内容，不删除用户已有配置。

### 版本更新

- 报告已安装版本。
- 根据安装路径识别 npm、Homebrew、uv 更新方式，也支持适配器声明的回退方式。
- 更新执行使用参数数组，不经过 shell。
- 缺失 Agent 显示安装命令或官方安装提示。

## API

```text
GET    /api/agent-platform/catalog
POST   /api/agent-platform/discover
GET    /api/agent-platform/agents
GET    /api/agent-platform/agents/{id}
GET    /api/agent-platform/agents/{id}/models
PATCH  /api/agent-platform/agents/{id}/binding
POST   /api/agent-platform/agents/{id}/configuration/preview
POST   /api/agent-platform/agents/{id}/configuration/apply
POST   /api/agent-platform/agents/{id}/restore
GET    /api/agent-platform/agents/{id}/update-plan
POST   /api/agent-platform/agents/{id}/update
GET    /api/agent-platform/profiles
POST   /api/agent-platform/profiles
POST   /api/agent-platform/profiles/{id}/apply
DELETE /api/agent-platform/profiles/{id}
GET    /api/agent-platform/library
POST   /api/agent-platform/library
DELETE /api/agent-platform/library/{id}
POST   /api/agent-platform/agents/{id}/library/{item_id}/apply
DELETE /api/agent-platform/agents/{id}/library/{item_id}
```

## 桌面界面

现有 `/agents` 页面继续管理 OpenTalos 自建 ReAct Agent，并新增外部 Agent 平台区：

- 已安装/完整目录切换和搜索。
- 安装版本、配置路径和兼容路径。
- 模型搜索、主模型绑定和短名单。
- Diff 预览、应用和恢复。
- Profile 保存与应用。
- 跨 Agent Library 创建、应用和移除。
- 更新命令预览和显式确认执行。

## 安全边界

- 自动配置只对已实现渲染器并验证格式的 Agent 开放。
- 不使用 shell 执行更新命令。
- API 不接触 Provider 明文密钥；Agent 配置只写入本地 Gateway URL 和固定本地占位 Token。
- 配置替换防止产生半写入文件。
- 恢复使用首次托管快照，而不是上一次已修改状态。

## 已知限制

- Windows WSL 多发行版安装矩阵尚未实现，当前保留为 M6 的 P2 后续项。
- 未验证的 83 个 Agent 不自动改写原生配置，需按其官方方式连接 Gateway。
- 厂商 CLI 的配置文件格式可能随版本变化；新格式必须先增加 fixture 测试再启用自动写入。
- Windows 可执行文件版本和安装来源识别仍以命令发现为主。

## 验收命令

```bash
.venv/bin/python -m pytest -p no:capture tests/agent_platform -q
.venv/bin/python -m pytest -p no:capture tests/apps/api/test_agent_platform_routes.py -q
pnpm -C apps/web test
pnpm -C apps/web lint
pnpm -C apps/web exec tsc --noEmit
```

## 验证结果

- M6 核心与 API 定向测试：`18 passed`
- M6 + parity 基线联合测试：`23 passed`
- 桌面监督器回归：`13 passed`
- 完整后端回归：`918 passed, 7 skipped`
- 前端 Vitest：`23` 个文件、`178 passed`
- ESLint：通过
- TypeScript：通过
- Next.js Webpack production build：通过
- Magpie parity 基线：`130` 项能力、`87` 个 Agent
- M6 完成后：`agents` 工作面 8 项 implemented，WSL 1 项保留 gap
