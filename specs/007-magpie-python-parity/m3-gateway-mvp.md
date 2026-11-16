# M3 Gateway MVP

**状态**: OpenAI Chat MVP Complete

**日期**: 2026-11-16

## 已实现

- 独立 FastAPI Gateway，默认端口 `3425`。
- `GET /health`
- `GET /v1/models`
- `POST /v1/chat/completions`
- OpenAI-compatible 上游转发。
- Anthropic Messages 上游请求与响应转换。
- OpenAI-compatible 和 Anthropic SSE 流式输出。
- Anthropic `thinking` 到 OpenAI `reasoning_content` 转换。
- OpenAI/Anthropic 工具定义、tool call、tool result 转换。
- Mock 上游，便于无外部依赖验证。
- SQLite 请求日志：`:3425/v1/magpie/requests`。
- 桌面服务监督器同时启动 API、Gateway 和 Web。
- `scripts/start.sh` 纳入 Gateway 生命周期。
- Provider 控制面页面显示 Gateway Base URL。

## 模型选择

支持三种请求模型 ID：

1. `provider/model`，例如 `openai/gpt-4o`。
2. `provider/account/model`，用于多个同 Provider 账号时精确选择。
3. 裸模型 ID，例如 `gpt-4o`；多个账号同时提供同名模型时返回歧义错误。

只有 `enabled=1` 的控制面账号参与选择。控制面没有模型时必须先执行 Discover。

## 使用方式

```bash
export OPENAI_BASE_URL=http://127.0.0.1:3425/v1
export OPENAI_API_KEY=local
```

```bash
curl http://127.0.0.1:3425/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "openai/gpt-4o",
    "messages": [{"role": "user", "content": "hello"}]
  }'
```

流式：

```bash
curl -N http://127.0.0.1:3425/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "openai/gpt-4o",
    "messages": [{"role": "user", "content": "hello"}],
    "stream": true
  }'
```

## 日志

每次非流式请求记录：

- Request ID
- 请求模型与实际模型
- Provider、账号
- 状态、HTTP 状态、耗时
- 输入/输出/总 Token
- 错误

流式请求记录状态、耗时和路由信息；流式 Token 解析留待后续增强。

## 尚未完成

- OpenAI Responses、Anthropic Messages、Gemini 入站（M4）。
- Gateway 入站鉴权、命名 Key、模型访问控制。
- 流式 OpenAI usage chunk 的完整 Token 统计。
- 客户端断开取消、重试、429 故障转移和候选账号轮换（M5）。
- 图片、音频、embeddings 和 rerank 路由。
- 请求正文审计、脱敏和 OTLP。

## 验证

```bash
.venv/bin/python -m pytest -p no:capture tests/gateway -q
uv run python -m apps.desktop --no-tray --smoke-test
```

真实临时 Gateway 烟测已验证：

- `/health`
- `/v1/models`
- 非流式补全
- SSE 流式补全
- `/v1/magpie/requests`

最终回归：

- Gateway 单元与路由测试：`16 passed`
- 完整后端确定性回归：`877 passed, 7 skipped`
- 完整回归中 1 个已有 MCP stdio 测试偶发失败，单独重跑通过
- 前端 Vitest：`22` 个文件、`176 passed`
- ESLint、TypeScript、Next.js production build：通过
- API + Gateway + Next.js + Desktop WebView 烟测：通过
- 临时 Gateway `:13425` 与 API/Web 端口在退出后均释放
