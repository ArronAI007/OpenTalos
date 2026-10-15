# Contract: Provider 配置 CRUD API

对应 User Story 2/3、FR-007~FR-015、SC-003~SC-006。镜像现状 `/api/mcp/servers` 的路由结构
（`apps/api/main.py`）。

## 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/providers` | 新增一条配置 |
| `GET` | `/api/providers` | 列出全部配置（可选 `?purpose=chat\|embedding` 过滤） |
| `PATCH` | `/api/providers/{id}` | 编辑字段，或传 `{"active": true}` 激活这一条 |
| `DELETE` | `/api/providers/{id}` | 删除（状态码 204），不受"不能删除最后一条"限制 |

## 请求/响应契约

### `POST /api/providers`

请求体（Pydantic `CreateProviderConfigBody`）：

```python
class CreateProviderConfigBody(BaseModel):
    name: str
    purpose: Literal["chat", "embedding"]
    backend: Literal["anthropic", "openai-compatible", "mock"] | None = None  # purpose="chat" 时必填
    base_url: str | None = None
    api_key: str
    model_name: str
```

校验：`name`/`api_key`/`model_name` 去空白后非空；`purpose="chat"` 时 `backend` 必须提供且
是三个枚举值之一，否则 400；`purpose="embedding"` 时 `backend` 必须为空（如果提供了非空值，
同样 400——避免用户误以为 embedding 也要选后端类型）。

响应：序列化后的配置（密钥已掩码），状态码 200。新建的配置默认 `active=false`（不自动激活，
避免"新增就意外切换了生产配置"这种意外，需要用户再点一次激活——比 MCP 服务器"新增默认启用"
更保守，因为切错聊天 provider 的影响比装错一个 MCP 工具大）。

### `GET /api/providers`

响应：`{"providers": ProviderConfig[]}`，按 `created_at DESC, rowid DESC` 排序（和现状
`mcp_servers`/`agent_roles` 一致）；每条的 `api_key` 字段替换成 `api_key_masked`。

### `PATCH /api/providers/{id}`

请求体（Pydantic `UpdateProviderConfigBody`，字段均可选但至少一个）：

```python
class UpdateProviderConfigBody(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_name: str | None = None
    active: bool | None = None
```

行为：`active=true` 时，在同一个数据库事务里把同 `purpose` 的其余行 `active` 置 0，再把这一
行置 1；`active=false` 时只取消这一行自己的激活状态，不影响其余行。未知 `id` → 404。

### `DELETE /api/providers/{id}`

未知 `id` → 404；成功 → 204。删除当前激活的配置不需要任何额外确认或限制——下一次解析配置时
自然查不到激活行，回退到环境变量（FR-012）。

## 行为契约

1. **掩码**：任何从这组路由返回的 JSON 里，`api_key`/`api_key_masked` 字段的值都不是完整明
   文密钥（FR-011）。
2. **立刻生效**：`PATCH .../active=true` 成功返回后，下一个新建的聊天任务/下一次 embedding
   调用必须使用这条配置（FR-013）——不依赖重启 `apps/api` 进程。
3. **回退**：某个 `purpose` 下没有任何 `active=1` 的行时，对应的消费方（`ChatRuntime`/
   `EmbeddingClient` 工厂）必须完整回退到现状的环境变量配置路径，不抛错误、不中断用户请求
   （FR-012）。
4. **输入校验**：`purpose`/`backend` 的枚举校验必须在写入数据库之前完成，失败给出清晰的
   400 错误（不是数据库约束报错后再包装）。

## 独立测试方式

- 新增一条配置，断言响应体里密钥已掩码；直接查数据库断言存的是完整明文（确认"掩码只在序列
  化层，不影响真实使用"）。
- 激活 A，再激活同 purpose 下的 B，断言 A 自动变为未激活。
- 删除当前激活的配置后，构造一次新任务/一次 embedding 调用，断言用的是环境变量配置（不是报
  错，也不是用了已删除的配置）。
- `purpose="chat"` 但不传 `backend`，断言 400；`purpose="embedding"` 但传了 `backend`，断言
  400。
