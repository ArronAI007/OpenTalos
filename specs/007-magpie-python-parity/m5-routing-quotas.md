# M5 路由与配额

**状态**: Routing Core Complete

**日期**: 2026-11-16

## 已实现

### 路由组

- 路由组创建、更新、列表和删除。
- 成员顺序和权重。
- 嵌套路由组。
- 环路检测。
- 同一候选去重。

### 路由模式

- `order`
- `rotate`
- `usage`
- `smart`
- `pace`
- `weight`

`smart` 在配额未耗尽的候选里优先选择最早重置的账号。
`pace` 按剩余配额比例和距离重置时间计算消耗速度。
`usage` 使用 Gateway 已记录 Token 总量最少者优先。

### 配额

- Provider 账号配额快照。
- `window_name`、`remaining`、`limit_value`、`unit`、`reset_at`。
- 最新快照按账号和窗口去重。
- 剩余配额为 0 且尚未重置的账号会从候选中过滤。

### 会话与失败转移

- `X-Magpie-Session` 或 `X-Session-ID` 启用会话粘性。
- 会话绑定记录在 SQLite，Gateway 重启后仍然有效。
- 429、401、403、408、409、425、5xx、连接错误会尝试下一候选。
- 400 等请求错误不会错误地切换账号。
- 流式请求只在开始发送字节前执行失败转移。

### 追踪与用量

- `gateway_requests.routing_trace` 保存候选、过滤数量、选中账号和每次尝试。
- `/v1/magpie/requests` 返回路由轨迹。
- `/v1/magpie/usage` 和 `/api/model-control/usage` 返回请求数与 Token 汇总。
- Provider 页面可管理路由组、配额快照并查看用量。

## API

```text
GET/POST   /api/model-control/routing-groups
PATCH/DEL   /api/model-control/routing-groups/{id}
GET/POST   /api/model-control/quotas
GET        /api/model-control/usage
GET        /v1/magpie/usage
GET        /v1/magpie/requests
```

Gateway 模型 ID：

```text
group/daily-coding
```

## 失败转移语义

- 非流式：完整请求失败后可切换下一候选，最终响应来自成功账号。
- 流式：建连和读取响应头阶段失败可切换；开始输出后不再切换，避免重复文本。
- 所有尝试写入请求日志的 `routing_trace`。

## 已知限制

- `weight` 当前是加权轮询，不是随机加权抽样。
- `smart` / `pace` 依赖本地配额快照，尚未自动轮询所有厂商配额 API。
- Intent routing 尚未实现。
- Busy load、context window 和 free/cheap/fast 偏好尚未全部进入候选过滤。
- 成本计算仍复用现有 pricing 基础，Gateway 暂未持久化价格快照。
- Quota history 已有底层表，但尚无独立趋势页面。
- 实时 Routing 可视化目前以数据 API 和路由组 UI 为主。

## 验证

```bash
.venv/bin/python -m pytest -p no:capture tests/gateway/test_routing.py -q
.venv/bin/python -m pytest -p no:capture tests/gateway/test_failover.py -q
.venv/bin/python -m pytest -p no:capture tests/apps/api/test_model_control_routes.py -q
```

真实临时 Gateway 烟测：

- 路由组配置 Primary → Backup。
- Primary 的 weekly 配额快照设为 `remaining=0`。
- 请求 `group/failover` 时 Primary 被过滤。
- 响应实际来自 Backup。
- `routing_trace.filtered_quota=1`，`selected_account=Backup`。
- `/v1/magpie/usage` 正确汇总 1 次请求和 2 个 Token。

最终回归：

- 路由模式、嵌套、粘性和配额过滤测试：`5 passed`
- 失败转移测试：`3 passed`
- 控制面路由组、配额和用量 API 测试：`7 passed`
- 完整后端回归：`898 passed, 7 skipped`
- 完整回归中 2 个已有 A2A demo peer 启动超时；两项单独重跑均通过
- 前端 Vitest：`22` 个文件、`177 passed`
- ESLint、TypeScript、Next.js production build：通过
- API + Gateway + Next.js + Desktop WebView 烟测：通过
- 烟测后 API、Gateway 和 Web 端口均释放
