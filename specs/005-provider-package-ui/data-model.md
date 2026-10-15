# Phase 1 Data Model: 独立的 Provider 包 + Web 端配置界面

## `packages/core/protocols.py`

### ModelClientProtocol（`typing.Protocol`，新增）

| 成员 | 类型 | 说明 |
|------|------|------|
| `model_name` | `str` | 当前生效的模型名 |
| `last_stream_summary` | `StreamSummary \| None` | 上一次流式调用的汇总（`core.protocol.StreamSummary`，`packages/core` 内部类型，import 不受边界限制） |
| `acomplete` | `async (messages, **kwargs) -> Completion` | 非流式单次补全 |
| `astream` | `async (messages, **kwargs) -> AsyncIterator[str]` | 流式文本补全 |
| `acomplete_with_tools` | `async (messages, tools, **kwargs) -> ToolCompletion` | 非流式工具调用补全 |
| `astream_with_tools` | `async (messages, tools, *, on_text_delta=None, on_reasoning_delta=None, **kwargs) -> ToolCompletion` | 流式工具调用补全 |

**校验规则**：`packages/ai` 的 `ModelClient` 必须结构性满足（Python `Protocol`，不需要显式继
承）；`packages/core/agent.py`/`agent_loop.py` 只认这个 Protocol 的形状。

## `apps/api/db.py`（`provider_configs` 表）

### ProviderConfig（SQLite 行，序列化成 dict）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `TEXT` | 主键，`uuid.uuid4().hex` | |
| `created_at` | `TEXT` | 非空 | 和现状其余表一致的时间戳格式 |
| `name` | `TEXT` | 非空 | 用户起的名字，不要求唯一 |
| `purpose` | `TEXT` | 非空，枚举 `"chat" \| "embedding"` | 决定这条配置用在哪个场景 |
| `backend` | `TEXT` | `purpose="chat"` 时非空，枚举 `"anthropic" \| "openai-compatible" \| "mock"`；`purpose="embedding"` 时为 `NULL` | 决定 `ModelClient` 用哪个后端类；embedding 场景固定走 `AsyncOpenAI`，不需要这个字段 |
| `base_url` | `TEXT` | 可空 | 留空时用 `backend` 对应具名 provider 的默认值（chat）或 SDK 默认值（embedding） |
| `api_key` | `TEXT` | 非空，数据库存明文 | **任何序列化成 API 响应/界面展示的路径都必须掩码**（见 contracts/provider-configs-api.md） |
| `model_name` | `TEXT` | 非空 | 实际发请求时用的模型名 |
| `active` | `INTEGER` | 非空，默认 `0`，取值 `0`/`1` | 同一 `purpose` 下任意时刻最多一行为 `1`，由应用层在激活操作时保证 |

**校验规则**：
- `purpose` 不是 `"chat"`/`"embedding"` 之一 → 创建/更新时拒绝，返回清晰错误（FR-009 对应的
  输入校验，宪法原则 III）。
- `purpose="chat"` 但 `backend` 缺失或不在三个枚举值之内 → 拒绝。
- 激活某一行（`set_provider_config_active`-式方法）必须在同一个数据库事务里，先把同
  `purpose` 的其余行 `active` 置 `0`，再把目标行置 `1`（决策 3）。
- 删除/取消激活不受任何"不能删除最后一条"的限制（Edge Cases）。

## `packages/memory/semantic.py`

### SemanticMemory（构造签名变更）

| 变更前 | 变更后 |
|--------|--------|
| `__init__(self, path: Path, embedder: EmbeddingClient) -> None` | `__init__(self, path: Path, embedder: Callable[[], EmbeddingClient]) -> None` |

**校验规则**：`embedder` 工厂函数每次被调用都必须返回一个可用的 `EmbeddingClient`
实例（不要求同一个实例被复用——`EmbeddingClient` 构造本身不做 I/O，重复构造没有代价）；
`apps/api/db.py` 提供的默认工厂实现：查询 `provider_configs` 表 `purpose='embedding'` 且
`active=1` 的行，有则用其字段构造，没有则 `EmbeddingClient()` 无参构造（读环境变量，现状行
为）。

## `apps/web/lib/providers-api.ts`（前端类型，镜像 `mcp-api.ts`）

### ProviderConfig（TypeScript interface）

```typescript
export interface ProviderConfig {
  id: string;
  created_at: string;
  name: string;
  purpose: "chat" | "embedding";
  backend: "anthropic" | "openai-compatible" | "mock" | null;
  base_url: string | null;
  api_key_masked: string;  // 后端已经掩码过，前端永远拿不到完整密钥
  model_name: string;
  active: boolean;
}

export interface CreateProviderConfigInput {
  name: string;
  purpose: "chat" | "embedding";
  backend?: "anthropic" | "openai-compatible" | "mock";  // purpose="chat" 时必填
  base_url?: string;
  api_key: string;
  model_name: string;
}
```

**校验规则**：`api_key_masked` 字段名刻意和数据库列名 `api_key` 不同，避免前端代码误以为自
己拿到的是完整密钥（接口命名本身传达一次"这是掩码过的"信息，不只是依赖文档）。
