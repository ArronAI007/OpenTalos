# Phase 0 Research: 独立的 Provider 包 + Web 端配置界面

本次调研基于对真实代码的阅读（`packages/core/{agent.py,agent_loop.py,protocols.py,errors.py,
model.py,providers.py,model_catalog.py,pricing.py}`、`packages/agents/{builder.py,
react_agent.py}`、`packages/memory/{embedding.py,semantic.py}`、`apps/api/{db.py,main.py,
runtime.py}`、`apps/web/{app/mcp/page.tsx,lib/mcp-api.ts,components/sidebar/{Sidebar.tsx,
SidebarClient.tsx},components/ui/icons.tsx}`、`scripts/check_core_boundary.py`），不是对
spec.md 的转述。

## 决策 1：`ModelClientProtocol` 的具体形状和迁移步骤

**决策**：核实 `packages/core/agent_loop.py` 实际用到的 `ModelClient` 成员，精确到 6 个：
`acomplete`/`astream`/`acomplete_with_tools`/`astream_with_tools`/`last_stream_summary`/
`model_name`（`packages/core/agent.py` 本身不直接调用任何成员，只是把 `model_client` 原样存
下来传给 `agent_loop.py` 的函数）。在 `packages/core/protocols.py` 新增：

```python
@runtime_checkable
class ModelClientProtocol(Protocol):
    """agent 循环需要的最小模型客户端形状；由 packages/ai 的 ModelClient 结构性满足。"""

    model_name: str
    last_stream_summary: Any | None  # core.protocol.StreamSummary，但 protocols.py 不 import core.protocol 以外的类型

    async def acomplete(self, messages: list[dict], **kwargs: Any) -> Any: ...
    async def astream(self, messages: list[dict], **kwargs: Any) -> AsyncIterator[str]: ...
    async def acomplete_with_tools(self, messages: list[dict], tools: list[dict], **kwargs: Any) -> Any: ...
    async def astream_with_tools(
        self, messages: list[dict], tools: list[dict], *,
        on_text_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> Any: ...
```

返回值类型（`Completion`/`ToolCompletion`）已经是 `packages/core/protocol.py` 自己定义的类
型，不属于要搬走的 4 个文件，`protocols.py` 可以直接 import 它们而不违反边界（`protocol.py`
和 `protocols.py` 都在 `packages/core` 包内）。`packages/core/agent.py`/`agent_loop.py` 的
`model_client: ModelClient` 参数标注改成 `model_client: ModelClientProtocol`，删除
`from .model import ModelClient` 这一行——这是整个 User Story 1 里 `packages/core` 唯一需要
改的两个文件。

对应 FR-002/FR-003。

**备选方案**：给新包的 `ModelClient` 显式继承一个 ABC 基类。被否决——`typing.Protocol` 本身
就是本仓库从 002 feature 起确立的既定模式（`SteerQueue` 等 6 个现有 Protocol 都是这样做
的），`ModelClient` 不需要知道 `packages/core` 的存在，继承会反向引入耦合。

## 决策 2：`packages/ai` 的文件布局和 import 路径改动范围

**决策**：`packages/core/{model.py,providers.py,model_catalog.py,pricing.py}` 四个文件原样
搬到 `packages/ai/` 下（文件名不变：`model.py`/`providers.py`/`model_catalog.py`/
`pricing.py`），新增 `packages/ai/__init__.py`（空文件，和现状 `packages/core/__init__.py`
一致的约定）。四个文件内部原本的相对导入（`model.py` 的 `from .providers import
get_provider_preset`、`from .errors import ModelError, SettingsError`）里，只有
`from .errors import ...` 这一行需要改成 `from core.errors import ...`（绝对导入，因为
`errors.py` 留在 `packages/core`，不随这次搬家）；`from .providers import ...`/
`from .model_catalog import ...` 这类四个文件之间的相对导入保持不变（它们现在在同一个新包
里，相对导入语义不变）。

需要同步更新 import 路径的调用方（逐一核实过，不是猜测）：

| 文件 | 现状 import | 改成 |
|------|-----------|------|
| `packages/agents/builder.py` | `from core.model import ModelClient` | `from ai.model import ModelClient` |
| `packages/agents/react_agent.py` | `from core.model import ModelClient` | `from ai.model import ModelClient` |
| `apps/api/runtime.py` | `from core.model import ModelClient`、`from core.model_catalog import default_compaction_token_limit` | 对应改成 `from ai.model import ...`、`from ai.model_catalog import ...` |
| `apps/api/main.py` | 004 feature 里 `apps/api/main.py` 没有直接 import 这几个模块（需要在 tasks 阶段再次确认，这次新增的 provider 配置路由会新增一处 `from ai.providers import ...` 式的 import 供"已知具名 provider 列表"的快捷新增卡片使用） | 新增 import |
| `tests/core/{test_model.py,test_providers.py,test_model_catalog.py}` | `from core.model import ...` 等 | 整个文件搬到新的测试目录（建议 `tests/ai/`），import 改成 `from ai.model import ...` 等 |

对应 FR-001/FR-005。

**备选方案**：保留 `packages/core/model.py` 作为一个转发层（`from ai.model import *`），不改
调用方 import。被否决——这会制造一个永久存在的、容易让人迷惑"真正的实现在哪"的重定向层，且
`packages/core` 如果保留这个转发文件本身就会 import 新包，直接违反 FR-002 的边界要求。

## 决策 3：`provider_configs` 表的字段设计

**决策**：新增一张表，和现状 `mcp_servers`/`agent_roles` 同样的设计语言（`id`/`created_at`/
`enabled`-风格字段）：

```sql
CREATE TABLE IF NOT EXISTS provider_configs (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  name TEXT NOT NULL,
  purpose TEXT NOT NULL,          -- 'chat' | 'embedding'
  backend TEXT,                    -- 'anthropic' | 'openai-compatible' | 'mock'；仅 purpose='chat' 非空
  base_url TEXT,
  api_key TEXT NOT NULL,
  model_name TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 0
);
```

`active` 用整数 0/1（和现状 `mcp_servers.enabled` 同样的约定）。"同一 purpose 下最多一条
active"（FR-010）不用数据库唯一约束强制（SQLite 的部分唯一索引写法在这个仓库其余表里没有先
例，增加不必要的复杂度），改成应用层逻辑：激活某一条时，同一个事务里先把同 purpose 的其余行
的 `active` 置 0，再把目标行置 1——参照现状 `set_mcp_server_enabled` 的单字段更新模式，只是
多了一步"先清空同类"。

对应 FR-008/FR-010、data-model.md 的完整字段说明。

**备选方案**：chat 和 embedding 各建一张独立的表。被否决——两者字段高度重合（只差
`backend` 这一列是否需要），拆成两张表会在 CRUD 路由/前端表单/未来可能的第三种 purpose 上重
复一遍几乎相同的代码；宪法原则 IV 倾向更简单的那个选项。

## 决策 4：API 密钥掩码的具体规则

**决策**：`_provider_config_row_to_dict`（镜像 `_mcp_server_row_to_dict`）序列化时，`api_key`
字段永远替换成掩码值：密钥长度 ≤ 4 时整体替换成 `"****"`；否则保留末 4 位，前面全部替换成
`"*"`（例如 `sk-ab...1234` 风格的后四位展示，和主流密钥管理 UI 的常见约定一致，足够用户辨认
"是不是填对了那个密钥"而不泄露完整值）。数据库里存的是完整明文（和现状 `mcp_servers.config`
里存 `command`/`args`/`env` 的做法一致，参见 Edge Cases 对这一点的明确说明），掩码只发生在
"读出来、序列化成 API 响应/界面展示"这一步。新增/编辑请求体本身仍然需要接收完整密钥（否则用
户没法设置），所以掩码规则**只适用于 GET 类路由的响应**，POST/PATCH 的请求体不受影响。

对应 FR-011/SC-005。

**备选方案**：数据库里也不存明文，改成某种哈希或加密存储。被否决——加密需要一个密钥管理方
案本身（密钥的密钥存哪），这个仓库现状没有任何应用层加密基础设施，引入一套只为这一张表服务
的加密机制超出这次范围（spec.md Assumptions 已经明确这一点）；真正需要用这个密钥发起真实请
求时，系统必须能拿到明文，纯哈希存储做不到这件事。

## 决策 5：聊天 provider 配置的免重启生效机制

**决策**：核实 `apps/api/runtime.py` 的 `_get_agent(task)` 现状逻辑——`self._agents.get
(task["id"])` 命中缓存直接返回（已经在跑的任务不会重新解析配置，这正是 Clarifications Q2
"已经在跑的任务不受影响"这句话字面对应的现状行为，不需要额外代码）；只有某个 `task_id`
第一次被请求、`self._model_client`（`ChatRuntime` 的旧版单例缓存）还未构造时才会真正用到
"解析 provider 配置"这一步。

把 `ChatRuntime._client()` 现状的"全局只构造一次、永久复用"逻辑改成：每次 `_get_agent()`
给一个还没有缓存 `Agent` 的新 `task_id` 构造 `Agent` 时，都重新查一次 `provider_configs` 表
有没有 `purpose='chat'` 且 `active=1` 的行——有则用它的 `backend`/`base_url`/`api_key`/
`model_name` 构造一个新的 `ModelClient`；没有则回退到现状"读环境变量"的构造方式
（`ModelClient()` 无参构造，004 feature 的行为）。这意味着 `ChatRuntime` 不再对
`ModelClient` 做跨任务的永久单例缓存——每个新任务都拿到一个独立构造的 `ModelClient` 实例
（但同一个任务生命周期内，`self._agents[task_id]` 缓存住的 `Agent` 继续复用同一个
`ModelClient` 实例，不会每次发消息都重新构造）。

`model_name` 属性（`ChatRuntime.model_name` 现状通过 `self._client().model_name` 暴露给
`/api/config` 路由）需要相应调整为"查询当前激活配置，没有则退回环境变量默认值"的语义，而不
是"问那个永久缓存的单例"。

对应 FR-013、Clarifications Q2、spec.md Edge Cases 关于"已运行任务不受影响"的说明。

**备选方案**：保留 `ModelClient` 单例缓存，新增一个显式的"配置变更时手动失效缓存"的 API 调
用（界面上点激活时额外触发一次缓存失效）。被否决——这样行为上等价，但多了一条"缓存失效"的
显式状态需要维护和测试，而"每个新任务重新解析一次"本来就是现状 MCP 工具（`_ensure_mcp_
tools()`）已经在用、已经验证过的模式，复用它比发明一套新的缓存失效机制更简单（宪法原则
IV）。

## 决策 6：Embedding provider 配置的免重启生效机制

**决策**：核实 `packages/memory/semantic.py` 的 `SemanticMemory.__init__(self, path,
embedder: EmbeddingClient)` ——构造时收一个**具体实例**，4 处方法体内部用
`self._embedder.embed(...)`；`apps/api/db.py` 的 `ChatStore.__init__` 构造
`SemanticMemory(self._path, embedder or EmbeddingClient())`，这个 `EmbeddingClient()` 实例
一旦建好就是 `ChatStore`（进而是整个进程）生命周期内唯一的一个，比聊天场景的单例缓存问题更
深——它不是"每个新任务重新查一次"能解决的，因为 `ChatStore`/`SemanticMemory` 本身就是进程
级单例，不存在"任务"这个颗粒度。

`SemanticMemory.__init__` 的 `embedder` 参数类型改成 `Callable[[], EmbeddingClient]`
（零参可调用对象，不是具体实例），4 处 `self._embedder.embed(...)` 改成
`self._embedder().embed(...)`——`EmbeddingClient.__init__` 本身极轻（只存几个字符串字段，
不做任何 I/O，构造便宜），每次调用这个工厂函数都重新构造一个当下最新的 `EmbeddingClient` 不
会有可感知的性能代价。`apps/api/db.py` 提供这个工厂闭包的默认实现：查一次
`provider_configs` 表有没有 `purpose='embedding'` 且 `active=1` 的行，有则用它的字段构造
`EmbeddingClient(model_name=..., api_key=..., base_url=...)`，没有则 `EmbeddingClient()`
无参构造（读环境变量，现状行为）。

对应 FR-013/FR-015、Clarifications Q3。

**备选方案**：`packages/memory` 自己持有数据库连接，直接查表。被否决——`packages/memory` 现
状对"配置从哪来"完全不知情（干净的职责边界），自己查数据库会让这个包额外依赖
`apps/api/db.py` 的 schema 细节，方向反了（`apps/api` 依赖 `packages/memory` 是合法方向，反
过来不是）。

## 决策 7：前端页面结构——镜像 `/mcp` 的既有模式

**决策**：新页面 `apps/web/app/providers/page.tsx` 整体结构镜像 `apps/web/app/mcp/page.tsx`
（364 行，已完整读过）：

- 一组"已知具名 provider"快捷卡片（`anthropic`/`openai`/`deepseek`/`moonshot`，数据来自新增
  的 `GET /api/providers/presets` 式只读端点，或直接在前端硬编码——004 feature 的注册表内容
  本身就是 6 条静态数据，和 `COMMON_MCP_SERVERS` 现状硬编码在前端的做法一致，不需要额外一个
  API）、点击预填表单的 `backend`/`base_url`。
- 一个通用新增表单（名字/用途/后端类型/服务地址/密钥/模型名），提交后追加到列表。
- 两个列表分组（chat / embedding，对应 `purpose` 字段），每条展示名字/后端类型/掩码后的密
  钥/是否激活，提供"激活"/"删除"按钮（激活用现状 `/mcp` 里"启用/禁用"按钮的同一视觉模式，只
  是语义从"开关"变成"单选"——点击未激活的那条变成激活，同组其余自动取消）。
- 复用现状 `ConfirmDeleteServerDialog` 的确认删除弹窗模式（新建一个同构的
  `ConfirmDeleteProviderDialog`）。
- 复用 `PageSkeleton`（加载态）。

对应 FR-006/FR-007/FR-009/FR-014、Assumptions 里"参照现状 `/mcp` 页面既有实现"的决定。

**备选方案**：provider 的具名预设数据通过一个新的只读 API 端点下发，而不是前端硬编码。被否
决——004 feature 的注册表内容（6 条数据）本来就是一份极少变化的静态数据，和现状
`COMMON_MCP_SERVERS` 硬编码在 `page.tsx` 里的做法完全同构，没有必要为了"理论上更优雅"而多引
入一次网络请求。

## 决策 8：侧边栏入口 + 新图标

**决策**：核实 `apps/web/components/sidebar/{Sidebar.tsx,SidebarClient.tsx}` 两个文件现状都
有一份完整的导航链接列表（`Sidebar.tsx` 的展开态 + `SidebarClient.tsx` 的 `SidebarRail` 折
叠态），`/mcp` 在两处都出现——这次新增的 `/providers` 入口必须同样在两处都添加（本仓库
memory 里记录过的"两处都要改"教训，这次直接作为一条 Functional Requirement 而不是依赖记
忆）。新增一个 `KeyIcon`（`apps/web/components/ui/icons.tsx`，复用文件里已有的 `Icon` 包装
函数，lucide 风格的钥匙图形），入口文案定为"Provider"。

对应 FR-006。

## 决策 9：OAuth/密钥类安全检查的复用

**决策**：这次新增的"界面可编辑、持久化存储的 API 密钥"和 003 feature 的 OAuth 凭据处理属于
同一类"安全敏感代码"（宪法"涉及安全敏感代码的改动必须额外做安全性检查"）。`/speckit-tasks`
阶段需要安排一个专门的安全检查任务（参照 003 feature 的先例：当时发现并修复了一个真实的
CSRF 漏洞），重点检查：掩码规则是否覆盖了全部返回密钥的路径（包括错误信息里会不会意外带出
密钥片段）、日志/trace 会不会记录完整请求体（如果会，新增的 provider 配置路由需要排除密钥字
段）、前端是否有任何地方把密钥明文打印到 console/网络面板之外的地方。

对应 Edge Cases 里"安全敏感代码需要额外谨慎"的要求。
