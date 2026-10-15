# Feature Specification: 独立的 Provider 包 + Web 端配置界面

**Feature Branch**: `005-provider-package-ui`

**Created**: 2026-10-15

**Status**: Draft

**Input**: User description: "Provider配置应该像pi一样是独立于agent模块的，应该在packages目录下创建一个ai或者provider目录来统一管理所有Provider，并且可以在 http://localhost:3010/ 左侧栏添加一个Provider的配置界面"

## 参考实现核实记录（写 spec 前直接核实过的事实，不是猜测）

直接核实了本仓库现状的真实耦合关系，不是转述 004 feature 的文档：

- **004 feature 刚把 provider 注册表/模型能力目录放进了 `packages/core`**（`packages/core/
  {model.py,providers.py,model_catalog.py,pricing.py}`），这次用户明确指出这个位置不对——pi 的
  `packages/ai` 是一个完全独立于 `packages/agent`（agent 循环编排）的包，本仓库现状把
  provider/模型配置和 agent 循环的核心机制（`agent.py`/`agent_loop.py`）放在同一个
  `packages/core` 包里，不符合这个架构分离。
- **`packages/core` 现状对 `ModelClient` 是直接的同包相对导入**：`packages/core/agent.py`
  （`from .model import ModelClient`，构造函数参数 `model_client: ModelClient`）、
  `packages/core/agent_loop.py`（同样 `from .model import ModelClient`，`execute_model_step`/
  `run_tool_turn` 等函数的 `model_client` 参数都标注成具体类）。这两个文件实际只用到
  `ModelClient` 的 6 个成员：`acomplete`/`astream`/`acomplete_with_tools`/
  `astream_with_tools`/`last_stream_summary`/`model_name`，不需要类的其余任何细节。
- **`scripts/check_core_boundary.py` 是本仓库从 `001-core-isolation-selftest` 起就已经验证、持
  续强制执行的硬约束**：`packages/core` 下任何文件的顶层 import 都不能指向其他 `packages/*` 目
  录（相对导入豁免，因为那是包内引用）。如果把 `model.py` 等 4 个文件原样搬到一个新的顶层包
  （比如 `packages/ai`），`agent.py`/`agent_loop.py` 现状的 `from .model import ModelClient`
  就必须改成跨包的 `from ai.model import ModelClient`，会被这个检查器判定为违规——这不是本次可
  以绕过或放宽的东西，`001`/`002`/`003`/`004` 四个 feature 的 plan.md 都把它列为必须保持零违规
  的硬性 Constitution Check 项。
- **本仓库已经有解决同一类问题的现成模式**：`packages/core/protocols.py` 是"core 对外要求的协
  作方契约：core 只认这些 Protocol 的形状，不 import 任何其他 `packages/*`"，已经登记了
  `HistoryStore`/`ToolExecutor`/`TraceRecorder`/`MetricsSink`/`TokenEstimator`/
  `OutputTrimmerLike`/`SteerQueue` 七个 `typing.Protocol`；002 feature 就是靠新增 `SteerQueue`
  这个 Protocol 解决了同样性质的"core 需要某个外部能力的形状、但不能 import 提供这个能力的具体
  类"问题。这次清楚地适用同一个模式：`protocols.py` 新增一个 `ModelClientProtocol`（或等价命
  名），只声明上面那 6 个成员的形状；真正的 `ModelClient` 类搬到新包后，结构性地满足这个
  Protocol（Python 的 `Protocol` 不需要显式继承），`packages/core` 永远不 import 新包。
- **真正构造 `ModelClient` 并传给 `Agent`/`ReActAgent` 的调用方**（`packages/agents/
  builder.py`、`packages/agents/react_agent.py`、`apps/api/runtime.py`）本来就已经合法地依赖
  `packages/core` 之外的其他包——它们只需要把 `from core.model import ModelClient` 这一行改成
  指向新包，不受边界检查器约束。
- **`packages/core/errors.py` 的 `SettingsError`/`ModelError`/`EmptyModelResponse`**（provider/
  model 相关异常）和同文件里的 `AgentRuntimeError`/`OutputLimitError`/`OperationCancelled`
  （纯 agent 循环相关异常）混在一起——这次不把这几个异常类也搬到新包（避免不必要地拆分一个本
  来就很小的文件），新包改成从 `core.errors` import 它们（这是允许的方向：非 core 的包依赖
  core 一直都是合法的，`packages/agents`/`packages/tool` 现状已经都这样做）。
- **Web 前端现状已经有一个结构上非常接近的先例**：`/mcp` 页面（`apps/web/app/mcp/page.tsx`）+
  两处都要同步更新的侧边栏导航链接（`apps/web/components/sidebar/{Sidebar.tsx,
  SidebarClient.tsx}`，这是本仓库 memory 里记录过的一个容易漏改的点）+ 后端对应的
  `mcp_servers` SQLite 表和一组 CRUD 路由。"添加一个 Provider 的配置界面"在页面结构/侧边栏接
  入方式上可以直接参照这个现成的模式。

## Clarifications

### Session 2026-10-15

- Q: Provider 配置界面要做成什么能力级别——只读展示当前生效的 provider/模型状态，还是允许用户
  通过界面本身新增/编辑/启用禁用 provider 配置（意味着需要一张新的数据库表持久化这些配置，类
  似现状 `mcp_servers` 的模式）？ → A: 可编辑的 CRUD 界面——用户能通过界面新增/编辑/删除/激活
  provider 配置实例，持久化到数据库，参照现状 `mcp_servers` 的既有模式（列表+启用禁用+quick-add
  卡片）。
- Q: 如果界面允许编辑 provider 配置，运行中的后端进程要不要立刻感知到这次改动（让下一个新任务
  用上新配置，不需要重启进程），还是改动在下次进程重启后才生效？ → A: 立刻生效——下一个新建的
  任务必须用上最新的激活配置，不需要重启进程，和 `/mcp` 页面"启用/禁用某个 server 立刻在下个新
  任务里生效"的现成模式保持一致的用户体验。已经在跑的任务不受影响（它们已经持有自己的
  `ModelClient` 实例）。
- Q: "统一管理所有 Provider" 是否也要把现状独立于 `ModelClient` 之外的 embedding 模型配置
  （`EMBED_MODEL_NAME`/`EMBED_API_KEY`，供 `packages/memory` 的长期记忆功能使用）一并纳入这个
  新包和界面，还是继续保持它完全独立、这次只处理聊天模型的 provider？ → A: 一并收编——embedding
  用途的 provider 配置复用和聊天用途完全相同的 CRUD/持久化/激活/免重启生效机制，只是用途
  （purpose）标记不同、字段集合更窄（不需要选择后端类型，因为 embedding 现状只有一种实现形
  状）。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Provider/模型配置独立成包，和 agent 循环解耦 (Priority: P1)

维护者需要 provider 注册表、模型能力目录、`ModelClient` 这些"怎么连接到大模型服务商"的代码，
放在一个完全独立于 agent 循环编排（`packages/core` 的 `agent.py`/`agent_loop.py`）的包里——像
pi 的 `packages/ai` 相对 `packages/agent` 那样，这样以后这个包可以独立演进（新增 provider、调
整目录数据）而不需要碰 agent 循环的代码，也让"agent 循环需要什么样的模型调用能力"这件事通过一
个清晰、狭窄的接口表达出来，而不是耦合到一个具体实现类上。

**本次确认**：这次拆分必须保持 `packages/core` 现状"零 `packages/*` 依赖"这条已经验证、持续强
制执行的边界不被打破（`scripts/check_core_boundary.py` 必须在拆分后依然零违规）——这不是本次
可以商量的范围，是继承自 `001`/`002`/`003`/`004` 四个 feature 一直在维护的既有约束。

**Why this priority**：这是用户请求里最明确、最没有歧义的那部分——"独立于 agent 模块"这句话本
身就是这条 User Story 的验收标准；界面能不能做出来（User Story 2）依赖这次拆分先把数据/逻辑放
到位。

**Independent Test**：搬移完成后运行 `scripts/check_core_boundary.py`，确认 `packages/core`
依然零违规；运行全量测试套件，确认 004 feature 交付的全部能力（具名 provider 自动解析、模型能
力目录、压缩阈值默认值、声明式请求参数怪癖）行为不变，只是代码物理位置换了。

**Acceptance Scenarios**:

1. **Given** 拆分完成后的代码库，**When** 运行 `scripts/check_core_boundary.py`，**Then** 报告
   `packages/core` 零违规（和拆分前一致）。
2. **Given** `packages/core/agent_loop.py` 的 `execute_model_step`/`run_tool_turn` 等函数，
   **When** 查看它们的 `model_client` 参数类型标注，**Then** 标注的是 `packages/core` 自己定义
   的一个 Protocol 类型，不是从新包直接 import 的具体类。
3. **Given** 新包里的 `ModelClient` 实例，**When** 把它传给 `packages/core` 的 `Agent`/
   `execute_model_step` 等既有接口，**Then** 两者之间不需要任何适配器/包装类——`ModelClient`
   天然满足 `packages/core` 声明的 Protocol 形状。
4. **Given** 004 feature 交付的全部测试（具名 provider 解析、模型能力目录、压缩阈值默认值、声
   明式请求参数怪癖），**When** 搬移到新包位置后重新运行，**Then** 全部继续通过，断言内容不需
   要改变语义，只需要调整 import 路径。

---

### User Story 2 - Web 端可编辑的聊天 Provider 配置界面 (Priority: P2)

用户打开 http://localhost:3010/ 时，左侧导航栏有一个入口可以进入 Provider 配置页面：查看当前系
统认识哪些具名 provider（004 feature 交付的注册表：`anthropic`/`openai`/`deepseek`/
`moonshot`/`openai-compatible`/`mock`）、新增一条具体的 provider 配置实例（选一个具名 provider
作为快捷起点，或完全自定义）、填入模型名和密钥、把它设为当前激活的聊天 provider——不需要碰
`.env` 文件或重启后端进程，下一次新建对话就会用上这个配置。

**Why this priority**：这是用户请求里"能在浏览器里看到/管起来 Provider"这个可见价值的核心落
地，依赖 User Story 1 先把数据模型（注册表内容）在新包里稳定下来。

**Independent Test**：打开应用，点击侧边栏的 Provider 入口，新增一条配置（选一个具名
provider、填入密钥和模型名）、点击激活，新建一个对话任务，验证这个新任务确实用了刚激活的配
置（不需要重启后端进程）；删除/取消激活这条配置后再新建一个任务，验证行为回退到现状的
`.env` 环境变量配置（不报错、不中断）。

**Acceptance Scenarios**:

1. **Given** 用户打开应用首页，**When** 查看左侧导航栏，**Then** 能看到一个新的 Provider 相关
   入口（参照现状 `/mcp` 入口的视觉风格）。
2. **Given** 用户点击这个入口，**When** 页面加载完成，**Then** 能看到当前已配置的全部聊天
   provider 实例列表（每条显示名字、使用哪个具名 provider/后端类型、是否当前激活），以及一组
   针对已知具名 provider 的快捷新增入口（参照现状 `/mcp` 的 quick-add 卡片）。
3. **Given** 用户点击某个具名 provider 的快捷新增入口，**When** 表单预填了该 provider 的后端
   类型/默认服务地址，**Then** 用户只需要补填密钥和模型名就能提交；用户也可以不走快捷入口，
   完全自定义填写一条新配置（含自己选择后端类型/服务地址）。
4. **Given** 已经存在至少一条配置，**When** 用户点击"激活"某一条，**Then** 同一用途
   （purpose=chat）下原本激活的那条自动变为未激活（同一用途永远最多一条激活）。
5. **Given** 某条配置被激活，**When** 用户新建一个对话任务，**Then** 这个新任务使用这条激活配
   置的密钥/服务地址/模型名，不需要重启后端进程；此前已经在运行的任务不受影响。
6. **Given** 没有任何配置被标记为激活（或全部被删除），**When** 用户新建一个对话任务，**Then**
   行为回退到现状的 `.env` 环境变量配置（004 feature 交付的行为），不报错、不中断。
7. **Given** 用户查看配置列表或某条配置的详情，**When** 页面渲染密钥字段，**Then** 看到的是
   掩码后的值（比如只显示末尾几位），任何时候都不会把完整密钥明文回显到界面或网络响应里。

---

### User Story 3 - Web 端的 Embedding Provider 配置界面 (Priority: P3)

用户在同一个 Provider 配置页面里，还能单独管理"embedding 用途"的 provider 配置——`packages/
memory` 长期记忆功能现状依赖的 `EMBED_MODEL_NAME`/`EMBED_API_KEY`/`EMBED_BASE_URL` 这组独立配
置，改成走和聊天 provider 完全相同的新增/激活/删除/免重启生效机制，只是字段集合更窄（不需要
选择后端类型，embedding 现状只有一种实现形状）。

**Why this priority**：这是"统一管理所有 Provider"里范围更大但使用频率更低的一块——长期记忆
功能本身默认关闭（`MEMORY_ENABLED` 默认为否），复用 User Story 2 已经建好的整套机制（同一张
表、同一组 API、同一个页面），增量工作量和风险都比 User Story 2 小。

**Independent Test**：在 Provider 配置页面切到"Embedding"分组，新增一条 embedding 用途的配
置、激活它；开启长期记忆功能后触发一次真实的语义检索，验证确实用了这条激活配置，不需要重启进
程；取消激活后验证回退到现状的 `EMBED_*` 环境变量配置。

**Acceptance Scenarios**:

1. **Given** 用户在 Provider 配置页面，**When** 切换到 embedding 分组，**Then** 看到的是一组
   独立的 embedding 用途配置列表，和聊天用途的列表分开展示、互不影响对方的激活状态。
2. **Given** 用户新增一条 embedding 配置（模型名、密钥、可选服务地址，不需要选择后端类型）并
   激活，**When** `packages/memory` 的 `EmbeddingClient` 下一次被构造，**Then** 使用这条激活
   配置，不需要重启进程。
3. **Given** 没有任何 embedding 配置被激活，**When** `EmbeddingClient` 被构造，**Then** 行为
   回退到现状的 `EMBED_MODEL_NAME`/`EMBED_API_KEY`/`EMBED_BASE_URL` 环境变量配置，不报错、不
   中断。

### Edge Cases

- 新包和 `packages/core` 的异常类型边界：provider/模型相关的异常（`SettingsError`/
  `ModelError`）留在 `packages/core/errors.py`，新包从 `core.errors` import 它们——这是允许的
  依赖方向（非 core 的包依赖 core 一直合法），不需要把这几个异常类也搬走。
- 现状所有直接 `from core.model import ...`/`from core.providers import ...`/`from
  core.model_catalog import ...`/`from core.pricing import ...` 的调用方（`packages/agents/
  {builder.py,react_agent.py}`、`apps/api/runtime.py`、相关测试文件）import 路径必须全部同步
  更新，不能遗漏任何一处（本仓库 memory 里记录过"grep 全仓库再改"这条教训，适用于这次）。
- 删除或取消激活某个用途（chat/embedding）下唯一一条激活的配置——不需要阻止这个操作，直接回退
  到现状的环境变量配置即可（见 User Story 2 Acceptance Scenario 6、User Story 3 Acceptance
  Scenario 3），不需要"不能删除最后一条"这类额外限制。
- 密钥的存储方式：和现状 `mcp_servers` 表里 `config` JSON 字段的存储方式一致（SQLite 本地文
  件，明文，靠文件系统权限保护，本仓库目前没有任何应用层加密存储机制）——这是和现状保持一致
  的既有约定，不是这次新引入的降级；但 API 密钥比 MCP 服务器的 `command`/`args` 更敏感，实现
  阶段需要按宪法"安全敏感代码需要额外谨慎"的要求做一次专门的安全检查（对应 FR-011 的掩码要
  求、以及确保日志/trace 不会意外记录明文密钥）。
- 已经在运行中的任务（已经持有自己 `ModelClient`/`EmbeddingClient` 实例）不会因为界面上改了激
  活配置而被打断或切换——"立刻生效"只对"下一个新建的任务"成立，这和现状 `_agents`/`_task_mcp_
  tools` 按 task_id 缓存、只在任务第一次构造时读取配置的既有模式完全一致，不是这次新发明的语
  义。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须把 provider 注册表、模型能力目录、`ModelClient`（及其依赖的 provider/
  model 具体后端实现）从 `packages/core` 搬到一个新的独立顶层包（`packages/ai` 或
  `packages/provider`，具体命名见 Assumptions）。
- **FR-002**: `packages/core` 在这次改动后必须继续保持对其他任何 `packages/*` 目录零 import
  依赖（`scripts/check_core_boundary.py` 零违规），`agent.py`/`agent_loop.py` 对模型客户端的依
  赖必须通过 `packages/core` 自己声明的 `typing.Protocol` 表达，不直接 import 新包的具体类。
- **FR-003**: 新包的 `ModelClient` 类必须结构性地满足 `packages/core` 声明的这个 Protocol，不
  需要任何适配器/包装类。
- **FR-004**: 004 feature 交付的全部 provider/模型能力目录行为（具名 provider 自动密钥/base_url
  解析、未注册名字报错、模型能力目录查询、压缩阈值自动默认值、声明式请求参数怪癖）在搬移后必
  须保持逐字不变，不允许出现"之前能用、这次之后报错或行为不同"的情况。
- **FR-005**: 全部现状直接依赖 `packages/core` 的 provider/模型相关模块的调用方（`packages/
  agents/builder.py`、`packages/agents/react_agent.py`、`apps/api/runtime.py`，以及对应的测
  试文件）的 import 路径必须同步更新，指向新包。
- **FR-006**: Web 前端左侧导航栏必须新增一个可以进入 Provider 相关页面的入口，覆盖现状两处都
  需要同步更新的侧边栏组件（`apps/web/components/sidebar/{Sidebar.tsx,SidebarClient.tsx}`）。
- **FR-007**: Provider 配置页面必须展示当前系统全部已注册的具名 provider（可作为新增配置的快
  捷起点），以及用户已经创建的全部配置实例列表。
- **FR-008**: 系统必须提供持久化存储，保存用户创建的 provider 配置实例，每条至少包含：名字、
  用途（chat 或 embedding）、使用哪个后端类型（仅 chat 用途需要；embedding 用途固定一种实现形
  状）、服务地址、API 密钥、默认模型名、是否激活。
- **FR-009**: 用户必须能够通过界面新增、编辑、删除一条 provider 配置实例。
- **FR-010**: 同一用途（chat 或 embedding）下任意时刻最多只有一条配置实例处于激活状态；激活
  某一条必须自动取消同用途下其余配置的激活状态。
- **FR-011**: 任何展示 provider 配置的界面或 API 响应都不得返回完整明文密钥——必须掩码处理
  （例如只显示末尾若干位）。
- **FR-012**: 当某个用途（chat 或 embedding）下没有任何配置处于激活状态时，系统行为必须回退到
  该用途现状的环境变量配置（chat：004 feature 交付的 `MODEL_PROVIDER`/`MODEL_API_KEY`/
  `MODEL_NAME`/`MODEL_BASE_URL` 等；embedding：`EMBED_MODEL_NAME`/`EMBED_API_KEY`/
  `EMBED_BASE_URL`），不得报错或中断。
- **FR-013**: 新增、编辑、激活、取消激活、删除一条 provider 配置之后，下一个新创建的任务/
  `EmbeddingClient` 构造必须立刻反映这次改动，不需要重启后端进程；已经在运行中的任务不受影
  响。
- **FR-014**: 界面必须为已知的具名 provider（`anthropic`/`openai`/`deepseek`/`moonshot`）提供
  快捷新增入口，点击后预填对应的后端类型和默认服务地址；同时必须支持完全自定义的新增（自选后
  端类型、服务地址），参照现状 `/mcp` 页面 quick-add 卡片 + 通用表单并存的模式。
- **FR-015**: embedding 用途的 provider 配置必须复用和 chat 用途完全相同的持久化/CRUD/激活/
  免重启生效机制（FR-008~FR-013），只是用途标记不同、字段集合更窄（不需要选择后端类型）。

### Key Entities

- **Provider 包**（新顶层 `packages/*` 目录）：承载 provider 注册表、模型能力目录、
  `ModelClient` 及其后端实现——004 feature 已经定义好的全部数据形状原样搬入，不改变字段。
- **ModelClientProtocol**（`packages/core/protocols.py` 新增的 `typing.Protocol`）：
  `packages/core` 对"一个可用的模型客户端"提出的最小形状要求——`acomplete`/`astream`/
  `acomplete_with_tools`/`astream_with_tools`/`last_stream_summary`/`model_name` 六个成员。
- **Provider 配置实例**：用户通过界面创建的一条具体配置——名字、用途（chat/embedding）、后端
  类型（仅 chat 需要）、服务地址、API 密钥（界面/API 响应里始终掩码）、默认模型名、是否激活。
  同一用途下任意时刻最多一条处于激活状态。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `packages/core` 在这次改动后，`scripts/check_core_boundary.py` 报告零违规。
- **SC-002**: 004 feature 交付的全部能力在搬移后行为 100% 保持一致，现有测试套件全部继续通过，
  没有任何测试因为这次纯粹的代码位置迁移而需要改变断言语义（只允许改 import 路径）。
- **SC-003**: 用户在浏览器里打开应用，能在 3 次点击以内（首页 → 侧边栏入口 → Provider 页面）看
  到当前系统支持哪些 provider。
- **SC-004**: 用户新增并激活一条聊天 provider 配置后，不重启后端进程，新建的下一个对话任务就
  能用上这条配置——从"点击激活"到"新任务生效"之间不需要任何手动干预（刷新页面之外的额外操
  作）。
- **SC-005**: 任何查看 provider 配置的界面或网络请求/响应里，都看不到任何一条已保存密钥的完整
  明文。
- **SC-006**: 删除或取消激活某个用途下唯一激活的配置后，系统继续正常工作（回退到环境变量配
  置），不出现错误提示或功能中断。

## Assumptions

- 新包命名选 `packages/ai`（直接对齐 pi 的包名，用户的描述也是"像 pi 一样"），不是
  `packages/provider`——两者用户都接受，`ai` 更贴近参照对象本身的命名,且在本仓库现状不会造成
  任何 import 遮蔽问题（不像 003 feature 处理过的 `mcp` 那样和某个官方 PyPI 包同名）。
- `packages/core/errors.py` 里的 `SettingsError`/`ModelError`/`EmptyModelResponse` 不搬到新
  包——新包改成依赖 `core.errors`（这是允许的方向），避免为了这次拆分而拆散一个本来就很小、且
  还装着其他 agent 循环专属异常类的现状文件。
- Provider 配置页面的视觉风格、交互模式参照现状 `/mcp` 页面的既有实现（同一个设计语言、同一套
  quick-add 卡片 + 通用表单 + 列表 + 启用禁用的交互范式），不是本次重新发明一套前端模式。
- API 密钥的持久化方式和现状 `mcp_servers` 表一致（本地 SQLite，明文，无应用层加密），这是和
  现状保持一致的既有约定（本仓库目前没有任何应用层加密存储机制），不是这次专门为了省事而降
  低的安全标准；界面/API 层面的掩码（FR-011）是防止"意外展示"这一类常见疏漏的最低限度要求，
  不等同于"静态加密存储"。
- "统一管理所有 Provider"的"所有"理解为"这次已知的、系统里实际存在的配置路径"（chat + 
  embedding 两个用途），不包含本次之外可能出现的、尚不存在的第三方配置路径。
