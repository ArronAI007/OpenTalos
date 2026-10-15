# Phase 0 Research: 把 DeepResearch 抽取成独立服务

## Decision 1：依赖复用机制——sys.path 注入，而不是字面意义的 uv path dependency

**Decision**：新 `deepresearch/` 目录保持"自己的 `pyproject.toml`、自己的虚拟环境、可独立
`uv sync` + 独立启动"（镜像 `agentrl/`），但复用 `packages/ai`/`packages/websearch`/
`packages/core` 的具体机制是**在 `deepresearch/` 自己的 Python 源码里做 `sys.path.insert`**
（和 `apps/api/main.py` 第 16-18 行完全相同的写法），不是给 `packages/ai`/`packages/
websearch`/`packages/core` 各自新增一份 `pyproject.toml` 再走字面意义的 uv path dependency。

**Rationale**：Clarifications 阶段选的选项标签是"uv 的 path dependency"，但这个标签表达的真实
意图是"引用复用已有代码，不要重新实现一遍协议/重试/多厂商适配逻辑"，不是字面指定一种具体
机制。核实后发现：`packages/ai`、`packages/websearch`、`packages/core` 目前都**没有**各自的
`pyproject.toml`（仓库唯一的包元数据只在根 `pyproject.toml` 和 `agentrl/pyproject.toml` 两
处）——它们是通过 `apps/api/main.py` 启动时 `sys.path.insert(0, str(_PACKAGES_DIR))` 变成可
import 的普通目录，不是独立可分发的 Python 包。要让 `uv` 的 path dependency 机制字面意义上
工作，需要先给这三个目录各自补一份 `pyproject.toml`（声明包名/构建后端）——这是在为了满足
*这一个新功能*的接线方式，去改动三个已经上线、与本功能无关的既有目录的包结构，既不必要地
放大了改动范围，也违反宪法原则 IV（拒绝过度工程）。sys.path 注入是本仓库已经在用、被验证过
的现状做法（`apps/api/main.py` 正是这么做的），用同样的手法达到"不重新实现、保持独立启动"
这个真实目标，改动面只落在新目录自己的代码里。

**Alternatives considered**：
- 给 `packages/ai`/`packages/websearch`/`packages/core` 各自补 `pyproject.toml`，走字面意义
  的 `[tool.uv.sources]` path dependency——技术上可行，但改动范围溢出到三个无关目录，且这三
  个目录目前都没有被设计成"可独立安装的包"（比如 `packages/core/__init__.py` 的相对导入结构
  默认假设自己是通过 sys.path 注入、而不是 `pip install` 的方式被消费），需要额外验证才能确
  认改造后不会破坏 `apps/api`/`packages/agents` 现有的消费方式。否决：收益（纯粹的"字面符合
  uv path dependency"）不足以覆盖这个改动面和回归风险。
- 彻底零依赖，各自重新实现一份最小客户端——这是 Clarifications 阶段已经否决的选项（用户选
  了"复用现有代码"而非"各自重新实现"），不再重新评估。

**依赖链核实**（决定了 sys.path 需要注入到哪一级、新 `pyproject.toml` 需要声明哪些三方依
赖）：
- `packages/ai/model.py` 需要 `core.errors`（`ModelError`/`SettingsError`）和 `core.protocol`
  （`Completion`/`StreamSummary`/...），这两个都是 `packages/core` 自己的模块；`packages/
  core` 本身（含它自己的 `__init__.py` 连带导入的 `agent.py`/`agent_loop.py`/`compaction.py`
  /`pricing.py`/`cancellation.py`/`protocols.py`）已经由 `scripts/check_core_boundary.py` 验
  证过零跨包依赖（只需要标准库 + `pydantic`），所以把整个 `packages/core` 一起纳入 sys.path
  是安全的，不会级联拉进其他 `packages/*`。
- `packages/websearch/client.py`/`models.py` 只依赖 `httpx`/`pydantic`，零跨包依赖；
  `websearch/__init__.py` 是空文件，`from websearch.client import TavilyClient` 不会触发
  `websearch/tools.py`（它依赖 `packages/tool`，deepresearch 用不到，也不应该被拉进来）。
- 新 `pyproject.toml` 需要的三方依赖：`fastapi`/`uvicorn`（自己的 HTTP 服务）、`pydantic`（
  `core.protocol` + `websearch.models` 都要）、`anthropic`/`openai`/`python-dotenv`（`ai.
  model` 要）、`httpx`（`websearch.client` 要）。

**sys.path 注入的具体位置**：放在 `deepresearch/research.py`（承载 `_plan`/`_run_todo`/
`_synthesize_report`/`run_research` 这组现状 `apps/api/deepresearch.py` 的逻辑）模块顶部，
和 `ai.model`/`websearch.client` 的 import 语句之前，写法与 `apps/api/main.py` 完全一致：

```python
_REPO_ROOT = Path(__file__).resolve().parent.parent  # deepresearch/research.py -> deepresearch -> repo root
_PACKAGES_DIR = _REPO_ROOT / "packages"
if str(_PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_DIR))
```

这样写的好处：不依赖进程启动时的 `PYTHONPATH` 环境变量或 `uv run --directory` 之类外部调用
方式——`Path(__file__)` 是这份源码在磁盘上的真实物理位置，不受"用哪个 venv 跑""cwd 是什么"
影响，`scripts/start.sh` 不需要为这个新服务特殊设置 `PYTHONPATH`（和 `agentrl` 一样，直接
`uv run --no-sync --directory deepresearch uvicorn main:app ...` 即可）。`ai/model.py` 自己
的 `load_dotenv(Path(__file__).resolve().parents[2] / ".env")` 同理不受影响——它算的是
`packages/ai/model.py` 自身的物理路径，和是谁 import 它无关，继续正确指向仓库根 `.env`。

## Decision 2：路由路径约定——扁平路径，镜像 AgentRL

**Decision**：新服务的路由是 `POST /runs`、`GET /runs`、`GET /runs/{id}`、`GET /runs/{id}/
stream`、`DELETE /runs/{id}`，不带 `/api` 或 `deepresearch` 前缀。

**Rationale**：Clarifications 阶段已经问过并确认（见 spec.md）；这里额外核实了 `scripts/
start.sh` 里 `agentrl` 的既有接入方式（`ensure_service "agentrl" "$AGENTRL_PORT" "$AGENTRL_
URL/health" ...`）完全不关心具体业务路由路径，只探测 `/health`——新服务同样只需要提供
`/health`，不需要为了兼容某个更大的路由树做任何特殊处理。

## Decision 3：ModelClient/TavilyClient 的构造时机——懒加载，不在服务启动时构造

**Decision**：新服务的 `ModelClient`/`TavilyClient` 不在模块导入时/应用启动时立即构造，而是
在收到第一个 `POST /runs` 请求时才尝试构造（构造失败则这一次请求返回错误，不影响服务本身已
经启动并通过健康检查）。

**Rationale**：核实了 `ai.model.ModelClient.__init__` 在 `MODEL_PROVIDER` 环境变量未设置时
会立即抛 `SettingsError`（没有 mock 兜底，除非显式传 `provider="mock"`）。现状 `apps/api`
的 `ChatRuntime` 对此的处理方式是整个运行时惰性持有 `self._model_client = None`，只有
`_client()` 真正被调用时才构造——这保证了即使 `.env` 里没配置模型相关变量，`apps/api` 进程本
身依然能正常启动、健康检查依然能过（只有真正发起聊天/DeepResearch 请求时才会报错）。新服务
延续同样的现状行为：构造延后到请求处理时，用一个模块级的"懒加载单例"函数（类似
`ChatRuntime._client()`），不在 `main.py` 顶层或 FastAPI 启动事件里就地构造，避免"没配置模
型密钥时整个服务直接起不来"这种比现状更差的新回归。`TavilyClient` 同理：现状 `apps/api` 在
`runtime.search_client is None` 时让 `POST /api/deepresearch/runs` 返回 503，而不是让整个
服务拒绝启动——新服务对等地在 `TAVILY_API_KEY` 缺失时允许服务正常启动、只在 `POST /runs` 时
返回 503。

**Alternatives considered**：在 FastAPI 的 lifespan/启动事件里立即构造两个客户端并挂到
`app.state`——否决，因为这会让"没配置密钥时服务直接起不来"，比抽取前的现状（服务能起，只是
这个功能用不了）更差，属于不必要的行为回归。

## Decision 4：持久化存储——独立 SQLite 文件 + 直接镜像 `agentrl/store.py` 的类结构

**Decision**：新增 `deepresearch/store.py`，内容结构直接镜像 `agentrl/store.py` 的
`RunStore`（同一种 `_now()`/`_connect()`/`_row_to_dict()` 写法），类名定为
`DeepResearchStore`，表名保持 `runs`（不需要叫 `deepresearch_runs`——这张表现在就是这个服务
唯一的表，不需要用模块名再前缀一遍，这一点也和 `agentrl/store.py` 把表叫 `runs` 而不是
`agentrl_runs` 一致）。数据库文件落在 `deepresearch/.data/deepresearch.db`（镜像
`agentrl/.data/agentrl.db` 的"自己目录下自己的 `.data/`"约定，不是仓库顶层共享的
`.data/`）。

**Rationale**：现状 `apps/api/db.py` 里 `deepresearch_runs` 表 + 5 个 CRUD 方法
（`create_deepresearch_run`/`get_deepresearch_run`/`list_deepresearch_runs`/
`update_deepresearch_run_todos`/`update_deepresearch_todo`/`update_deepresearch_run`/
`delete_deepresearch_run`，共 7 个）已经是一个独立、自包含的切片，和 `ChatStore` 其余表
（tasks/agents/projects/mcp_servers/...）没有任何外键或业务耦合——核实过 `apps/api/
deepresearch.py` 本身只用到这 7 个方法中的 4 个（`get_deepresearch_run`/
`update_deepresearch_run`/`update_deepresearch_run_todos`/`update_deepresearch_todo`），
`create_deepresearch_run`/`list_deepresearch_runs`/`delete_deepresearch_run` 由
`apps/api/main.py` 的路由直接调用——新服务里这两类调用方都在同一个 `main.py`/`research.py`
里，原样保留全部 7 个方法。

## Decision 5：`scripts/start.sh` 接入方式——逐字镜像 `agentrl` 的接入块

**Decision**：在 `scripts/start.sh` 里复制一份和 `agentrl` 一模一样的接入结构（变量声明 +
`AUTO_SYNC_DEEPRESEARCH`/`SKIP_DEEPRESEARCH` 开关 + `uv sync --directory deepresearch` +
`ensure_service "deepresearch" ...` + 启动失败降级为跳过 + 汇总打印行 + `NEXT_PUBLIC_
DEEPRESEARCH_URL` 传给 web）。

**Rationale**：核实了 `do_stop()` 函数（`scripts/start.sh` 第 184 行起）已经是通用的——它遍
历 `$PID_DIR/*.pid` 逐个停止，只要新服务用 `ensure_service "deepresearch" ...` 注册过
（这个调用本身会写 `$PID_DIR/deepresearch.pid`），`./scripts/start.sh stop` 不需要任何额外
改动就能连带停掉它。需要新增代码的地方只有：顶部端口/URL 变量声明、`AUTO_SYNC_DEEPRESEARCH`
相关的 sync 守卫块（可以比 agentrl 简单——deepresearch 没有 torch 那种平台限制性依赖，但仍
然保留"sync 失败只警告跳过，不拖垮其余服务"的现状健壮性约定）、`ensure_service` 调用本身、
`NEXT_PUBLIC_*` 环境变量传递给 web 进程、启动完成后的汇总打印行、以及末尾的日志提示行。

## Decision 6：前端接入——新增 `NEXT_PUBLIC_DEEPRESEARCH_URL`，页面本身留在 `apps/web`

**Decision**：`apps/web/lib/deepresearch-api.ts` 新增 `export const DEEPRESEARCH_URL =
process.env.NEXT_PUBLIC_DEEPRESEARCH_URL || "http://localhost:8441"`（镜像 `agentrl-api.ts`
的 `AGENTRL_URL` 写法），5 个请求函数的 base URL 从 `API_URL` 换成 `DEEPRESEARCH_URL`，路径
从 `/api/deepresearch/runs...` 换成 `/runs...`（对应 Decision 2）。`apps/web/app/
deepresearch/page.tsx` 本身不搬家，只是现状 `.catch(() => setRuns([]))` 这行需要补一个和
`AgentRLPage` 一样的 `loadError` 状态 + 对应的"服务未启动"提示文案，满足 User Story 3 的
Acceptance Scenario 2。

**Rationale**：核实了 `apps/web/app/agentrl/page.tsx` 现状已经有这个"独立服务连不上就降级
提示"的实现模式（第 100-108 行：`.catch(() => { setRuns([]); setLoadError(true); })`），
`apps/web/app/deepresearch/page.tsx` 现状只有 `.catch(() => setRuns([]))`（第 80 行），缺一
个显式的"服务未启动"用户可见提示，这正是 spec.md User Story 3 Acceptance Scenario 2 明确要
求补的那一处差异。

## Decision 7：测试组织——新目录下自己的 `tests/`，镜像 `agentrl/tests/` 的扁平结构

**Decision**：`deepresearch/tests/test_research.py` 内容迁移自现状
`tests/apps/api/test_deepresearch.py`（8 个测试类：`TestParseQueries`/`TestPlan`/
`TestRunTodo`/`TestSynthesizeReport`/`TestRunResearch`/`TestLiveRunBroadcaster`/
`TestSnapshotWithPartialReport`/`TestStreamRunEvents`），测试夹具从"构造一个完整的
`apps/api` ChatStore"换成"构造一个 `DeepResearchStore`"；`deepresearch/tests/test_routes.py`
新增，覆盖现状 `tests/apps/api/test_api_routes.py` 里属于 `/api/deepresearch/*` 的路由测
试，路径相应改成新的扁平路径。两份现状测试文件里属于 DeepResearch 的部分需要删除（连同
`tests/apps/api/test_db.py` 里的 deepresearch 相关测试一并删除，因为 `apps/api/db.py` 不再
有这张表）。

**Rationale**：`agentrl/tests/` 没有 `conftest.py`，直接 `from main import app`/`from store
import RunStore`——因为 pytest 以 `agentrl/pyproject.toml` 声明的 `testpaths = ["tests"]`
为准、以 `agentrl/` 自身为有效根目录运行，不需要额外的 sys.path 配置。`deepresearch/` 镜像
同样的结构，测试文件直接 `from research import ...`/`from store import DeepResearchStore`
即可，`packages/` 的可见性由 `research.py` 自己的 sys.path 注入（Decision 1）负责，测试不需
要重复处理。

## Decision 8：历史数据——不写迁移脚本

**Decision**：不新增任何迁移脚本或迁移任务。`apps/api/db.py` 删除 `deepresearch_runs` 表定
义和相关 CRUD 方法之后，`chat.db` 里原有的这张表（如果存在）既不会被自动清空也不会被自动迁
移——它只是不再被任何代码读写，物理上继续留在文件里，不额外处理。

**Rationale**：Clarifications 阶段已确认（spec.md）"不迁移，视为可接受的损耗"。这里额外确
认了技术上的后果：`apps/api/db.py` 的 `_SCHEMA` 用的是 `CREATE TABLE IF NOT EXISTS`——删除
这段 DDL 不会主动 `DROP TABLE`，旧表在旧的 `chat.db` 文件里保持原样（只是没有任何代码再引用
它），这正是"旧历史记录留在 `chat.db` 里不再可见，但不主动删除那些行"这句 Clarifications 原
文想表达的技术状态，不需要额外写代码去实现"不删除"——什么都不做就是这个效果。
