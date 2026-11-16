# M7 安全、账号与工具平台

**状态**: Security and Tooling Core Complete

**日期**: 2026-11-16

## 已实现

### 隐私脱敏

- 内置邮箱、电话、OpenAI/GitHub/AWS Key、Bearer Token、私钥规则。
- 用户自定义正则规则，支持 `mask`、`warn`、`block`。
- 同一 scope 内稳定占位符，默认 24 小时有效。
- 请求进入上游前递归脱敏 messages、reasoning 和 tool arguments。
- 非流式响应、SSE 文本、reasoning 和工具参数在返回客户端前恢复。
- SQLite 审计只保存规则、占位符和匹配数量，不保存原始秘密。
- masking 异常时按配置 fail-closed，返回明确 503。

### Gateway 中间件

- 请求前、流事件、响应后三类 hook。
- 每个 hook 独立超时，默认 fail-open 并记录插件错误。
- 文件插件通过 JSON stdin/stdout 协议接入，不经过 shell。
- 隐私恢复位于中间件链之后，插件只能观察占位符。

### 共享与访问控制

- 命名 Gateway Key，仅保存 SHA-256，明文只在创建和轮换时返回一次。
- Key 支持创建、轮换、更新、撤销和使用审计。
- 日、周、月请求预算，Token、成本、缓存和并发限制。
- 模型、账号、路由组和只读/admin scope 访问控制。
- 本机回环请求继续使用 local administrator；非回环共享请求必须使用 Key。
- Dashboard 预置共享网络暴露警告，未确认时禁止绑定非回环地址。

### 订阅库存

- 发现 Claude、Codex/ChatGPT、GitHub Copilot、Gemini、Antigravity、Grok 和 OpenCode 的本地登录文件。
- 只持久化账号来源、模型清单、项目、配额未知状态和登录状态。
- API 响应和普通导出不包含 Token、API Key 或 credential 内容。
- 可选 credential export 必须显式确认风险。
- 支持导入元数据 bundle。
- daily/reset warm-up 调度持久化，API 进程内有后台调度器；休眠唤醒后只补跑一次到期任务。

### 搜索与 Web Fetch

- 多 Tavily Key 轮换、优先级和拒绝冷却。
- 401/403/429、网络错误和 5xx 自动尝试下一个 Key。
- 成功、失败、拒绝和冷却状态可查询。
- `web_fetch` 限制 HTTP(S)、拒绝 localhost/私网/保留地址和重定向。
- `web_fetch` 限制 content type、响应字节数和 HTML 脚本内容，并执行隐私脱敏。

### 插件平台

- 本地目录发现、manifest 校验、安装、更新、停用、启用和删除。
- 确定性目录哈希完整性校验。
- 声明式 capability allow-list。
- Provider 插件 JSON 命令协议可执行 complete/stream。
- Middleware 插件实现 request/event/response hooks。
- 插件 UI pages/slots 元数据进入桌面安全中心。

### 媒体生成

- Provider-neutral image/video job 存储。
- 图片生成结果持久化到本地媒体目录，并通过受控 API 读取。
- MCP stdio server 暴露 `generate_image` 与 `generate_video`。
- 视频支持 start、progress、cancel 状态机。
- 内置 OpenAI Image backend；未配置厂商时返回明确 503。

### 桌面控制面

`/security` 页面提供：

- 隐私开关、TTL、规则、测试和审计。
- 共享地址、TLS 模式、网络风险确认和 Gateway Key 生命周期。
- 订阅扫描、刷新和 warm-up。
- 搜索 Key 管理。
- 插件安装、启停和完整性校验。
- 图片生成与媒体任务。

## API

```text
GET/PATCH /api/m7/privacy/settings
GET/POST  /api/m7/privacy/rules
POST      /api/m7/privacy/test
GET       /api/m7/privacy/audit
GET/PUT   /api/m7/sharing/config
GET/POST  /api/m7/sharing/keys
PATCH     /api/m7/sharing/keys/{id}
POST      /api/m7/sharing/keys/{id}/rotate
DELETE    /api/m7/sharing/keys/{id}
GET       /api/m7/sharing/keys/{id}/usage
GET       /api/m7/sharing/audit
GET       /api/m7/subscriptions
POST      /api/m7/subscriptions/discover
POST      /api/m7/subscriptions/{id}/refresh
POST      /api/m7/subscriptions/export
POST      /api/m7/subscriptions/import
GET/POST  /api/m7/subscriptions/warmups
POST      /api/m7/subscriptions/warmups/run
GET/POST  /api/m7/tools/search-keys
PATCH     /api/m7/tools/search-keys/{id}
POST      /api/m7/tools/web-fetch
GET       /api/m7/plugins
POST      /api/m7/plugins/install
POST      /api/m7/plugins/discover
PATCH     /api/m7/plugins/{id}
POST      /api/m7/plugins/{id}/verify
GET       /api/m7/media/jobs
POST      /api/m7/media/images
POST      /api/m7/media/videos
GET       /api/m7/media/files/{job_id}
```

## 安全边界

- 明文 Gateway Key 不落库。
- 隐私审计不保存原始敏感值。
- 插件安装目录必须位于受管插件根目录，入口路径不能逃逸插件目录。
- 插件进程只继承 PATH、HOME 和最小 `OPENTALOS_PLUGIN_*` 环境。
- Web Fetch 不做自动重定向，防止重定向到内网。
- 媒体文件 API 只允许读取配置的媒体根目录。

## 已知限制

- Claude/Codex/Copilot/Gemini 等订阅目前完成本地 inventory、refresh 和账号元数据；直接使用厂商 OAuth 凭据转发模型请求仍需逐个厂商协议适配。
- Antigravity、Grok、OpenCode 的本地 CLI bridge 尚需厂商版本 fixture。
- 订阅 warm-up 当前刷新本地状态，不会对所有厂商主动发起计费请求。
- 浏览器扩展 MCP、Magpie 证书签发/吊销、完整 mTLS 启动开关尚未完成。
- Provider 插件已经能执行 completion，但插件账号签入和动态模型发现 UI 仍待补齐。
- Plugin UI 当前展示 manifest page/slot 元数据，不执行第三方前端代码。
- Grok/MiniMax 视频后端尚未绑定真实厂商 API。

## 验收命令

```bash
.venv/bin/python -m pytest -p no:capture tests/privacy tests/gateway_access -q
.venv/bin/python -m pytest -p no:capture tests/subscriptions tests/plugin_platform tests/media_platform -q
.venv/bin/python -m pytest -p no:capture tests/gateway/test_m7_middleware.py tests/gateway/test_m7_privacy_gateway.py tests/gateway/test_m7_access_routes.py -q
.venv/bin/python -m pytest -p no:capture tests/apps/api/test_m7_routes.py -q
pnpm -C apps/web test
pnpm -C apps/web lint
pnpm -C apps/web exec tsc --noEmit
```

## 验证结果

- M7 定向测试：`36 passed`
- MCP 完整回归：`50 passed`
- 完整后端回归：`953 passed, 7 skipped`
- 完整回归中单个既有 MCP stdio 清理用例受 `killpg` 环境权限影响失败；补充 `OSError` 清理保护后，该用例与整个 `tests/mcp` 均通过
- 桌面与 parity 基线：`18 passed`
- 前端 Vitest：`24` 个文件、`179 passed`
- ESLint、TypeScript、Webpack production build：通过
- 浏览器烟测：六个安全中心页签均加载；隐私脱敏开关和邮箱占位符恢复交互通过
- M7 当前 37 项：`16 implemented`、`18 partial`、`3 gap`
