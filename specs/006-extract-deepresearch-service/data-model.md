# Phase 1 Data Model: 把 DeepResearch 抽取成独立服务

## `deepresearch/store.py`（`DeepResearchStore`，新建）

### ResearchRun（SQLite 表 `runs`，序列化成 dict）

和现状 `apps/api/db.py` 的 `deepresearch_runs` 表字段逐字一致，只是表名从
`deepresearch_runs` 简化为 `runs`（同一服务里不需要再用模块名前缀自己）：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `TEXT` | 主键，`uuid.uuid4().hex` | |
| `created_at` | `TEXT` | 非空 | 和现状格式一致（`_now()` helper） |
| `status` | `TEXT` | 非空，枚举 `"running" \| "completed" \| "failed"` | |
| `topic` | `TEXT` | 非空 | 用户给出的研究主题原文 |
| `todos` | `TEXT` | 非空，JSON 序列化的 `ResearchTodo[]` | 创建时为 `'[]'`，规划完成后整体替换 |
| `report` | `TEXT` | 可空 | 最终 markdown 报告；未完成/失败为 `NULL` |
| `error` | `TEXT` | 可空 | 失败信息；成功/进行中为 `NULL` |

**校验规则**：`status` 的三个取值、`todos` 的 JSON 结构由应用层（`research.py`）保证，不在数
据库层加 CHECK 约束（和现状 `deepresearch_runs` 表一致，不是本次抽取引入的新行为）。

### ResearchTodo（内嵌在 `ResearchRun.todos` 字段里的 JSON 对象，非独立表）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `int` | 规划阶段按顺序分配的序号，从 0 开始 |
| `query` | `str` | 规划阶段生成的搜索查询问题 |
| `status` | `"pending" \| "running" \| "completed" \| "failed"` | |
| `summary` | `str \| None` | 完成后的总结文本；失败时是错误信息；未开始时为 `None` |
| `sources` | `list[{"title": str, "url": str}]` | 完成时填充；失败/未开始为空数组 |

### `DeepResearchStore` 方法（镜像现状 `ChatStore` 里对应的 7 个方法，逐字保留行为）

| 方法 | 签名 | 行为 |
|------|------|------|
| `create_run` | `(self, topic: str) -> dict` | 插入一行 `status='running'`/`todos='[]'`/`report=NULL`/`error=NULL`，返回完整行 |
| `get_run` | `(self, run_id: str) -> dict \| None` | 按 id 查，不存在返回 `None` |
| `list_runs` | `(self) -> list[dict]` | 按 `created_at DESC, rowid DESC` 排序 |
| `update_run_todos` | `(self, run_id: str, todos: list[dict]) -> None` | 整体替换 `todos` 字段 |
| `update_todo` | `(self, run_id: str, todo_id: int, **fields) -> None` | 按 `id` 找到 `todos` 数组里的一条，用 `fields` 更新；run 不存在则静默跳过 |
| `update_run` | `(self, run_id: str, *, status=None, report=None, error=None) -> dict \| None` | 只更新传了值的字段；行不存在返回 `None` |
| `delete_run` | `(self, run_id: str) -> bool` | 删除一行，返回是否真的删到 |

**命名变化说明**：方法名从 `create_deepresearch_run`/`get_deepresearch_run`/... 简化为
`create_run`/`get_run`/...（去掉冗余的 `deepresearch` 前缀——类名 `DeepResearchStore` 已经
表达了这个上下文，和 `agentrl/store.py` 的 `RunStore.create_run`/`get_run` 命名风格一致）。
调用方（`research.py`/`main.py`）相应使用新方法名，字段名和返回值形状不变。

## `deepresearch/research.py`（迁移自 `apps/api/deepresearch.py`，内部逻辑不变）

- `PlanningError`、`_LiveRun`、`_live_runs`、`start_live_run`、`_publish`、
  `_snapshot_with_partial_report`、`stream_run_events`、`_parse_queries`、`_plan`、
  `_run_todo`、`_synthesize_report`、`_finish`、`run_research`：函数签名与内部逻辑逐字保留，
  唯一改动是参数类型从 `ChatStore` 换成 `DeepResearchStore`，调用的 store 方法名按上表更
  新（如 `store.get_deepresearch_run(run_id)` → `store.get_run(run_id)`）。
- 模块顶部新增 sys.path 注入（见 research.md Decision 1），`from ai.model import
  ModelClient`/`from websearch.client import TavilyClient` 的 import 语句保持不变（只是现
  在能 resolve 到是因为 sys.path 注入，而不是因为运行在 `apps/api` 进程里）。

## `deepresearch/main.py`（新建，镜像 `agentrl/main.py` 的组织方式）

- 模块级 `store = DeepResearchStore(_REPO_ROOT / ".data" / "deepresearch.db")`（立即构造，
  纯 SQLite 文件操作，没有外部服务依赖，不需要懒加载）。
- 模块级懒加载的 `ModelClient`/`TavilyClient`（见 research.md Decision 3）：
  ```python
  _model_client: ModelClient | None = None
  _search_client: TavilyClient | None = None

  def _get_model_client() -> ModelClient:
      global _model_client
      if _model_client is None:
          _model_client = ModelClient()
      return _model_client

  def _get_search_client() -> TavilyClient | None:
      global _search_client
      if _search_client is None and os.environ.get("TAVILY_API_KEY"):
          _search_client = TavilyClient(os.environ["TAVILY_API_KEY"])
      return _search_client
  ```
- CORS 中间件：和 `agentrl/main.py`/`apps/api/main.py` 同款约定，读 `CORS_ORIGINS` 环境变
  量，默认放行 `http://localhost:3000`。
- 5 个路由（见 `contracts/deepresearch-api.md`）+ `GET /health`。

## `apps/web/lib/deepresearch-api.ts`（改动，不新建）

- 新增 `export const DEEPRESEARCH_URL = process.env.NEXT_PUBLIC_DEEPRESEARCH_URL ||
  "http://localhost:8440"`。
- 5 个函数的 `API_URL` 换成 `DEEPRESEARCH_URL`，路径去掉 `/api/deepresearch` 前缀
  （`/api/deepresearch/runs` → `/runs`，其余同理）。
- `DeepResearchRun`/`DeepResearchTodo`/`DeepResearchSource` 三个 TypeScript 接口字段不变
  （后端字段逐字一致，见上表）。
