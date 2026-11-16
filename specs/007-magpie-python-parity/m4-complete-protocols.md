# M4 完整协议

**状态**: Protocol Complete

**日期**: 2026-11-16

## 协议矩阵

入站：

| Protocol | Endpoint | Streaming |
|---|---|---|
| OpenAI Chat | `POST /v1/chat/completions` | SSE |
| OpenAI Responses | `POST /v1/responses` | Responses SSE |
| Anthropic Messages | `POST /v1/messages` | Anthropic SSE |
| Gemini | `POST /v1beta/models/{model}:generateContent` | JSON |
| Gemini Stream | `POST /v1beta/models/{model}:streamGenerateContent` | SSE |

上游：

- OpenAI Chat Completions
- OpenAI Responses
- Anthropic Messages
- Gemini generateContent
- Mock

## 转换核心

Gateway 内部使用 OpenAI Chat 作为规范格式：

1. 入站 Responses、Anthropic、Gemini 转成 Chat。
2. Gateway Router 选择控制面账号。
3. 上游调用后统一成 Chat 响应或 Chat SSE。
4. 再转换回调用方使用的协议。

代码：

- `packages/gateway/inbound_responses.py`
- `packages/gateway/inbound_anthropic.py`
- `packages/gateway/inbound_gemini.py`
- `packages/gateway/streaming.py`
- `packages/gateway/upstream.py`

## 已支持内容

- 文本消息
- system / instructions
- OpenAI tools 与 Anthropic input_schema
- Gemini functionDeclarations
- tool call 和 tool result
- OpenAI `reasoning_content`
- Anthropic thinking blocks
- Responses reasoning summary
- 非流式 usage
- SSE 流式文本与工具参数增量
- Gemini functionCall / functionResponse
- Gemini、OpenAI Responses 原生上游
- Gemini 原生模型发现

## 控制面扩展

新增 backend：

- `openai-responses`
- `gemini`

新增 Provider 预设：

- Google Gemini Native
- OpenAI Responses

## 已知限制

- Responses `previous_response_id`、background mode 和完整的 response item 生命周期尚未实现。
- 流式 usage 在部分上游仍可能为 0。
- Gemini safety settings、citation metadata 和 grounding 字段尚未做完整双向映射。
- 图片、音频、embeddings 和 rerank 不属于 M4。
- 客户端取消传播和自动故障转移属于 M5。
- 全部 4×4 协议组合尚未建立外部真机矩阵；当前通过规范化层和协议单元测试覆盖。

## 验证

```bash
.venv/bin/python -m pytest -p no:capture tests/gateway -q
.venv/bin/python -m pytest -p no:capture tests/model_platform -q
```

当前结果：

- Gateway 协议测试：`27 passed`
- M4 协议与 control-plane 定向测试：`42 passed`
- 覆盖所有四种入站路由的非流式转换
- 覆盖 Anthropic、Responses、Gemini 与 Chat SSE 转换
- 覆盖 OpenAI Responses 和 Gemini 原生上游
- 真实临时 Gateway 验证：Chat、Responses、Anthropic Messages、Gemini
  `generateContent` 均返回成功
- Responses SSE 真实流式烟测通过，包含 `response.created`、文本 delta 和
  `response.completed`
- 完整后端回归：`886 passed, 7 skipped`
- 完整回归中 4 个已有 A2A 测试因 demo peer 启动超时失败；单独重跑 A2A 套件
  `11 passed`
- 前端 Vitest：`22` 个文件、`176 passed`
- ESLint、TypeScript、Next.js production build：通过
