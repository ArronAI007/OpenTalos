---

description: "Task list template for feature implementation"
---

# Tasks: 把 DeepResearch 抽取成独立服务

**Input**: Design documents from `/specs/006-extract-deepresearch-service/`

**Prerequisites**: plan.md、spec.md、research.md、data-model.md、contracts/deepresearch-api.md、quickstart.md（全部已存在）

**Tests**: 本项目宪法（constitution.md 原则 I，TDD 不可协商）要求业务逻辑代码必须配套测试，
所以下面每个 User Story 都包含先写失败测试、再实现的任务。

**Organization**: 任务按 User Story 分组，每个 Story 可独立实现、独立测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可并行（不同文件、无依赖）
- **[Story]**：对应 spec.md 的 User Story 编号
- 每个任务都给出确切文件路径

## Path Conventions

本功能是"仓库根目录下的独立子项目"结构（见 plan.md Structure Decision），新代码落在仓库根
目录新增的 `deepresearch/` 下，不是 `apps/`/`packages/` 任何一个既有目录；改动点也涉及现状
`apps/api/`、`tests/apps/api/`、`scripts/start.sh`、`apps/web/`。

---

## Phase 1: Setup

**Purpose**：记录基线、搭好新目录骨架

- [X] T001 运行 `.venv/bin/pytest -q` 记录当前根项目测试通过数（本次会在 Phase 3 删除
      `tests/apps/api/test_deepresearch.py` 及另外两个文件里的 DeepResearch 相关测试，用这
      个基线数字核实"删除数 + 新增数"的净变化符合预期，而不是意外多删/少删）
- [X] T002 创建 `deepresearch/tests/__init__.py`（空文件，镜像 `agentrl/tests/__init__.py`
      的组织方式）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**：新项目的依赖声明——没有这一步，`deepresearch/` 下任何代码都没法 `uv sync`/
独立安装/独立跑测试

**⚠️ CRITICAL**：这个阶段完成之前，Phase 3 及之后的任何任务都无法执行

- [X] T003 创建 `deepresearch/pyproject.toml`：镜像 `agentrl/pyproject.toml` 的结构
      （`requires-python = ">=3.12"`、`[tool.uv] package = false`、
      `[tool.pytest.ini_options] asyncio_mode = "auto"` + `testpaths = ["tests"]`），
      `[project.dependencies]` 声明 `fastapi>=0.115`、`uvicorn[standard]>=0.32`、
      `pydantic>=2.9`、`anthropic>=0.39`、`openai>=1.54`、`python-dotenv>=1.0`、
      `httpx>=0.27`（这些版本号和根 `pyproject.toml`/`packages/ai`/`packages/websearch` 实
      际用到的版本一致，见 research.md Decision 1 的依赖链核实），
      `[dependency-groups].dev` 声明 `pytest>=8.3`、`pytest-asyncio>=0.24`、`httpx>=0.27`
      （httpx 同时是运行依赖和测试依赖，和 `packages/websearch` 现状测试用
      `httpx.MockTransport` 的方式一致）

**Checkpoint**：`cd deepresearch && uv sync` 能成功跑完，`.venv` 生成——User Story 1 的实现
可以开始

---

## Phase 3: User Story 1 - DeepResearch 作为独立服务独立运行 (Priority: P1) 🎯 MVP

**Goal**：把 DeepResearch 的全部服务端逻辑（规划/并行搜索总结/报告合成/进度推送/任务存取）
整体搬进 `deepresearch/`，`apps/api` 不再承载这部分代码，新服务能在完全不启动
`apps/api`/`apps/web` 的情况下独立跑通一次完整研究流程。

**Independent Test**：见 spec.md User Story 1 的 Independent Test——全新 clone 的仓库里只进
`deepresearch/` 执行安装+启动两步，不碰 `apps/api`/`apps/web`，走完一次创建任务→拿到报告的
完整流程；静态检查 import 语句不触达 `apps/api`。

### Tests for User Story 1 ⚠️ 先写，确认失败，再实现

- [X] T004 [P] [US1] 失败测试：`DeepResearchStore.create_run`/`get_run`/`list_runs`/
      `update_run_todos`/`update_todo`/`update_run`/`delete_run` 的行为（新建默认
      `status="running"`/`todos=[]`/`report=None`/`error=None`；`list_runs` 按
      `created_at DESC, rowid DESC` 排序；`update_todo` 按 `id` 更新数组里的一条且不存在的
      `run_id` 静默跳过；`update_run` 只更新传了值的字段且不存在的 `run_id` 返回 `None`；
      `delete_run` 返回是否真的删到），镜像 `agentrl/tests/test_store.py` 的测试风格，写入
      `deepresearch/tests/test_store.py`（依赖 Phase 2 完成）
- [X] T005 [P] [US1] 把 `tests/apps/api/test_deepresearch.py` 的全部 8 个测试类
      （`TestParseQueries`/`TestPlan`/`TestRunTodo`/`TestSynthesizeReport`/
      `TestRunResearch`/`TestLiveRunBroadcaster`/`TestSnapshotWithPartialReport`/
      `TestStreamRunEvents`）复制到 `deepresearch/tests/test_research.py`：断言内容不改，
      只把 `store` fixture从构造 `db.ChatStore` 改成构造 `store.DeepResearchStore`，
      `store.get_deepresearch_run(...)` 这类调用改成 `store.get_run(...)`（方法名映射见
      data-model.md 的"命名变化说明"表），`from deepresearch import (...)` 改成
      `from research import (...)`（此刻 `deepresearch/research.py` 还不存在，这份测试此时
      必然失败/报 ImportError，这就是 RED）
- [X] T006 [P] [US1] 失败测试：对 `deepresearch/main.py` 的 5 个业务路由 + `/health` 的契约
      测试（见 contracts/deepresearch-api.md）——`POST /runs` 空白 `topic` 400、
      `TAVILY_API_KEY` 未配置时 503、成功创建返回 `status="running"`；`GET /runs` 列表排
      序；`GET /runs/{id}` 404；`DELETE /runs/{id}` 未知 404、`status="running"` 时 409、
      成功 204；`GET /runs/{id}/stream` 对不存在的 id 推一帧 `error` 后结束、对非
      `running` 状态推一帧 `snapshot` 后结束。镜像 `agentrl/tests/test_routes.py` 的写法
      （`httpx.ASGITransport(app=app)` + `monkeypatch.setattr(main_module, "store",
      DeepResearchStore(tmp_path/...))` 这个 autouse fixture 模式，这里还需要额外
      monkeypatch 掉 `main_module` 里懒加载的 `_model_client`/`_search_client` 全局变量,
      换成测试桩，避免真的调用模型/Tavily），写入 `deepresearch/tests/test_routes.py`（此
      刻 `deepresearch/main.py` 还不存在，这份测试必然 ImportError，这就是 RED）

### Implementation for User Story 1

- [X] T007 [US1] 创建 `deepresearch/store.py`：`DeepResearchStore` 类，`_SCHEMA` 定义
      `runs` 表（字段见 data-model.md：`id TEXT PRIMARY KEY`、`created_at TEXT NOT NULL`、
      `status TEXT NOT NULL`、`topic TEXT NOT NULL`、`todos TEXT NOT NULL`、
      `report TEXT`、`error TEXT`），`create_run`/`get_run`/`list_runs`/
      `update_run_todos`/`update_todo`/`update_run`/`delete_run` 七个方法，代码结构直接镜
      像 `agentrl/store.py`（`_now()`/`_connect()`/`_row_to_dict()` 同款写法），写入
      `deepresearch/store.py`（依赖 T004，验证 RED→GREEN）
- [X] T008 [US1] 用 `git mv apps/api/deepresearch.py deepresearch/research.py` 搬文件，再
      编辑：模块顶部按 research.md Decision 1 新增 sys.path 注入代码块（`_REPO_ROOT =
      Path(__file__).resolve().parent.parent`、`_PACKAGES_DIR = _REPO_ROOT / "packages"`、
      `sys.path.insert` 守卫），放在 `from ai.model import ModelClient`/`from
      websearch.client import TavilyClient` 之前；删除 `from db import ChatStore`，改成
      `from store import DeepResearchStore`；全部函数签名里的 `store: ChatStore` 类型标注
      改成 `store: DeepResearchStore`；函数体内 `store.get_deepresearch_run(...)` →
      `store.get_run(...)`、`store.update_deepresearch_run(...)` →
      `store.update_run(...)`、`store.update_deepresearch_run_todos(...)` →
      `store.update_run_todos(...)`、`store.update_deepresearch_todo(...)` →
      `store.update_todo(...)`；其余逻辑（`PlanningError`/`_LiveRun`/`_live_runs`/
      `start_live_run`/`_publish`/`_snapshot_with_partial_report`/`stream_run_events`/
      `_parse_queries`/`_plan`/`_run_todo`/`_synthesize_report`/`_finish`/`run_research`）
      逐字保留不改（依赖 T005、T007，验证 RED→GREEN）
- [X] T009 [US1] 创建 `deepresearch/main.py`：模块级 `store = DeepResearchStore(_REPO_ROOT
      / ".data" / "deepresearch.db")`（立即构造）；懒加载的 `_get_model_client()`/
      `_get_search_client()`（见 data-model.md 的精确实现，`_search_client` 在
      `TAVILY_API_KEY` 环境变量缺失时保持 `None`）；FastAPI app + CORS 中间件（读
      `CORS_ORIGINS` 环境变量，默认放行 `http://localhost:3000`，和
      `agentrl/main.py`/`apps/api/main.py` 同款约定）；`GET /health` 返回
      `{"status": "ok"}`；`POST /runs`（校验 `topic.strip()` 非空否则 400，
      `_get_search_client() is None` 则 503，否则 `store.create_run(topic)` + 同步调用
      `start_live_run(run["id"])` + `asyncio.create_task(run_research(store, run["id"],
      _get_model_client(), _get_search_client(), topic))`，返回新建的 run）；
      `GET /runs`（返回 `{"runs": store.list_runs()}`）；`GET /runs/{id}`（未知 404，否则
      返回完整 run）；`GET /runs/{id}/stream`（`StreamingResponse`，`media_type=
      "text/event-stream"`，内部复用 `research.py` 的 `stream_run_events` + 现状
      `apps/api/main.py` 的 `_sse()` 帧格式化函数，一并复制一份到 `main.py` 或
      `research.py`）；`DELETE /runs/{id}`（未知 404，`status=="running"` 409，否则
      `store.delete_run(run_id)` 204），写入 `deepresearch/main.py`（依赖 T006、T007、
      T008，验证 RED→GREEN）
- [X] T010 [US1] 清理 `apps/api`：删除 `apps/api/deepresearch.py`（内容已搬到 T008）；编辑
      `apps/api/main.py` 删除 `from deepresearch import run_research, start_live_run,
      stream_run_events` 这行、`CreateDeepResearchRunBody` 这个 Pydantic 模型、以及
      `/api/deepresearch/runs`（POST/GET）、`/api/deepresearch/runs/{run_id}`
      （GET/DELETE）、`/api/deepresearch/runs/{run_id}/stream` 这 5 个路由；编辑
      `apps/api/db.py` 删除 `_SCHEMA` 里的 `deepresearch_runs` 表定义、
      `create_deepresearch_run`/`_deepresearch_row_to_dict`/`get_deepresearch_run`/
      `list_deepresearch_runs`/`update_deepresearch_run_todos`/`update_deepresearch_todo`/
      `update_deepresearch_run` 7 个方法（依赖 T008，确认逻辑已安全搬迁后再删）
- [X] T011 [US1] 删除 `tests/apps/api/test_deepresearch.py`（内容已搬到
      `deepresearch/tests/test_research.py`，T005 已完成）；编辑
      `tests/apps/api/test_api_routes.py` 删除全部 DeepResearch 相关路由测试
      （`_mcp_demo_server_config` 附近以外的、断言 `/api/deepresearch/*` 的测试函数）；编
      辑 `tests/apps/api/test_db.py` 删除全部 DeepResearch 相关测试（依赖 T010）
- [X] T012 [US1] GREEN + 静态检查 checkpoint：运行 `grep -rn "^from db import\|^from
      runtime import\|from apps\." deepresearch/*.py` 确认无匹配（quickstart.md 场景 2）；
      运行 `cd deepresearch && uv run pytest -v` 确认全部通过；运行
      `.venv/bin/pytest -q` 确认根项目测试数相比 T001 记录的基线减少（删掉的 DeepResearch
      相关测试）且没有意外失败；运行 `.venv/bin/python scripts/check_core_boundary.py`
      确认仍然零违规（`apps/api`/`packages/core` 的改动不应该触碰这个边界）

**Checkpoint**：DeepResearch 已经是一个完全独立、可单独安装/单独启动/单独测试的服务——这是
MVP，即使 User Story 2/3 还没开始也有价值。

---

## Phase 4: User Story 2 - 现状的一键启动脚本原样纳管新服务 (Priority: P2)

**Goal**：`scripts/start.sh` 像管理 `agentrl` 一样管理新的 `deepresearch` 服务——一键启动
打印它的地址、一键停止连带停掉它、依赖装不上时只警告跳过不拖垮其余服务。

**Independent Test**：见 spec.md User Story 2 的 Independent Test。

- [X] T013 [US2] 编辑 `scripts/start.sh`：顶部"可调参数"区新增
      `DEEPRESEARCH_PORT="${DEEPRESEARCH_PORT:-8441}"`、
      `AUTO_SYNC_DEEPRESEARCH="${AUTO_SYNC_DEEPRESEARCH:-1}"`、
      `SKIP_DEEPRESEARCH="${SKIP_DEEPRESEARCH:-0}"`（紧邻现状 `AGENTRL_PORT`/
      `AUTO_SYNC_AGENTRL`/`SKIP_AGENTRL` 那几行之后）；新增
      `DEEPRESEARCH_URL="http://localhost:${DEEPRESEARCH_PORT}"`（紧邻
      `AGENTRL_URL` 那行之后）；新增 `DEEPRESEARCH_UP=1`（紧邻 `AGENTRL_UP=1` 那行之
      后）（依赖 Phase 3 完成，`deepresearch/pyproject.toml` 已存在）
- [X] T014 [US2] 继续编辑 `scripts/start.sh`：在现状 agentrl 的 sync-guard 代码块
      （`AGENTRL_ENABLED`/`AGENTRL_UNSUPPORTED` 那一段，第 249-270 行附近）之后，新增一段
      结构完全对等的 `DEEPRESEARCH_ENABLED`/`SKIP_DEEPRESEARCH`/
      `AUTO_SYNC_DEEPRESEARCH` 守卫块（`uv sync --directory deepresearch` 失败只打印警告
      并把 `DEEPRESEARCH_ENABLED` 置 0，不像 agentrl 那样需要额外的
      `AGENTRL_UNSUPPORTED`/平台限制提示，因为 `deepresearch` 没有 torch 那种平台受限依
      赖）；在 `ensure_service "agentrl" ...` 调用之后新增对等的
      `ensure_service "deepresearch" "$DEEPRESEARCH_PORT" "$DEEPRESEARCH_URL/health"
      healthy_status "$LOG_DIR/deepresearch.log" 0 uv run --no-sync --directory
      deepresearch uvicorn main:app --host "$HOST" --port "$DEEPRESEARCH_PORT" ||
      DEEPRESEARCH_UP=0`（包在 `if [ "$DEEPRESEARCH_ENABLED" = "1" ]` 判断里，否则直接
      `DEEPRESEARCH_UP=0`，结构对等现状 agentrl 那几行）
- [X] T015 [US2] 继续编辑 `scripts/start.sh`：web 进程启动那行的环境变量列表里追加
      `NEXT_PUBLIC_DEEPRESEARCH_URL="$DEEPRESEARCH_URL"`（紧邻现状
      `NEXT_PUBLIC_AGENTRL_URL="$AGENTRL_URL"` 之后）；汇总打印块里新增一段对等的
      `if [ "$DEEPRESEARCH_UP" = "1" ]; then echo "  deepresearch  $DEEPRESEARCH_URL"; else
      echo "  deepresearch  (skipped)"; fi`（紧邻现状 agentrl 那段汇总打印之后）；末尾日志
      提示行 `logs: tail -f $LOG_DIR/{api,agentrl,a2apeer,web}.log` 追加 `deepresearch`
      变成 `{api,agentrl,a2apeer,deepresearch,web}.log`
- [X] T016 [US2] 真机 checkpoint（quickstart.md 场景 3）：运行 `./scripts/start.sh
      restart`，确认汇总输出里出现 `deepresearch  http://localhost:8441` 一行，
      `curl http://localhost:8441/health` 返回 `{"status":"ok"}`；运行 `./scripts/
      start.sh stop` 确认 deepresearch 进程被连带停掉；临时把
      `deepresearch/pyproject.toml` 改名制造依赖装不上的场景，确认 `./scripts/start.sh
      restart` 只打印警告跳过 deepresearch、其余服务仍然正常启动、命令本身不报错退出，验
      证完后把文件名改回来

**Checkpoint**：一键启动/停止体验覆盖新服务，和现状开发体验保持一致。

---

## Phase 5: User Story 3 - Web 前端继续可用，指向新地址 (Priority: P3)

**Goal**：`apps/web` 的 DeepResearch 页面请求新服务而不是 `apps/api`，服务未启动时优雅降级。

**Independent Test**：见 spec.md User Story 3 的 Independent Test。

- [X] T017 [US3] 编辑 `apps/web/lib/deepresearch-api.ts`：新增 `export const
      DEEPRESEARCH_URL = process.env.NEXT_PUBLIC_DEEPRESEARCH_URL ||
      "http://localhost:8441"`；`createDeepResearchRun`/`listDeepResearchRuns`/
      `getDeepResearchRun`/`deleteDeepResearchRun`/`deepResearchStreamUrl` 五个函数的
      `API_URL` 全部换成 `DEEPRESEARCH_URL`，路径 `/api/deepresearch/runs...` 全部改成
      `/runs...`（`DeepResearchRun`/`DeepResearchTodo`/`DeepResearchSource` 三个
      TypeScript 接口字段不变）（依赖 Phase 3 完成，新路由契约已就位）
- [X] T018 [US3] 编辑 `apps/web/app/deepresearch/page.tsx`：仿照
      `apps/web/app/agentrl/page.tsx` 现状的 `loadError` 状态写法（第 96-108 行附近），给
      现状 `listDeepResearchRuns().then(setRuns).catch(() => setRuns([]))` 这个
      `useEffect` 补上 `setLoadError(true)` + 一段"DeepResearch 服务不可达"的用户可见提示
      文案渲染（新增 `const [loadError, setLoadError] = useState(false)` 状态）
- [X] T019 [US3] GREEN checkpoint：运行 `cd apps/web && npx tsc --noEmit --pretty false`
      确认类型检查通过；运行 `npx vitest run` 确认既有测试全部通过（这两个改动都是薄的请
      求包装/状态渲染，不新增独立单元测试，和现状 `mcp-api.ts`/`providers-api.ts`/
      `agentrl-api.ts` 零测试覆盖的既有惯例一致）
- [X] T020 [US3] 真机 checkpoint（quickstart.md 场景 4）：`deepresearch` 服务和 web 都启动
      后，打开 `http://localhost:3010/deepresearch`，新建一个研究任务，确认进度实时更新
      （`todo_update`/`report_chunk` 事件）、最终报告正常展示；浏览器 Network 面板确认请
      求落在 `:8441`；停掉 `deepresearch` 服务后刷新页面，确认出现"服务未启动"提示而不是
      白屏/未处理异常

**Checkpoint**：全部 3 个 User Story 独立可用，"统一管理 DeepResearch 为独立服务"的完整范围
交付。

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T021 [P] 运行全量回归：`.venv/bin/pytest`、`cd deepresearch && uv run pytest`、
      `.venv/bin/python scripts/check_core_boundary.py`、`cd apps/web && npx vitest run`，
      和 T001 记录的基线对比，确认 0 意外回归
- [X] T022 [P] 过一遍 quickstart.md 的全部 5 个验证场景（场景 1/2 在 Phase 3 已验证过，场景
      3 在 Phase 4 已验证过，场景 4 在 Phase 5 已验证过——这里是最终汇总确认，场景 5 的全量
      回归命令和 T021 相同）
- [X] T023 [P] 更新项目 memory（`project_opentalos_python_rebuild.md` 追加本次 shipped 记
      录 + `MEMORY.md` 索引行同步，记录"uv path dependency 的澄清标签 vs sys.path 注入的
      实际落地机制"这个值得记住的决策，供未来类似"独立服务复用现有包代码"的场景参考）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup（Phase 1）**：无依赖，立即开始
- **Foundational（Phase 2）**：依赖 Setup 完成——阻塞全部 User Story
- **User Story 1（Phase 3）**：依赖 Foundational 完成；**MVP**，独立可交付
- **User Story 2（Phase 4）**：依赖 User Story 1 完成（`scripts/start.sh` 需要
  `deepresearch/pyproject.toml`/`main.py` 已经存在才能 sync/启动）
- **User Story 3（Phase 5）**：依赖 User Story 1 完成（前端需要新路由契约已就位）；和 User
  Story 2 相互独立——T020 的真机验证可以手动 `uv run uvicorn main:app` 启动 deepresearch 而
  不依赖 `scripts/start.sh` 已经接好
- **Polish（Phase 6）**：依赖全部 User Story 完成

### Within Each User Story

- 测试任务必须先写、先确认失败（RED），再写实现任务（GREEN）
- User Story 1 内部：store.py 先于 research.py 先于 main.py 先于删除 apps/api 旧代码

### Parallel Opportunities

- Phase 3 的 T004/T005/T006 三个测试任务可以并行编写（互不冲突的三个新文件）
- Phase 4（User Story 2）和 Phase 5（User Story 3）在 Phase 3 完成后可以并行进行（不同文
  件、无交叉依赖）
- Phase 6 的三个任务可以并行

---

## Parallel Example: User Story 1 的测试

```bash
# 三个测试任务可以并行编写：
Task: "DeepResearchStore 的 CRUD 失败测试，写入 deepresearch/tests/test_store.py"
Task: "现状 test_deepresearch.py 迁移到 deepresearch/tests/test_research.py"
Task: "5 个路由 + /health 的契约失败测试，写入 deepresearch/tests/test_routes.py"
```

---

## Implementation Strategy

### MVP First（仅 User Story 1）

1. 完成 Phase 1：Setup
2. 完成 Phase 2：Foundational
3. 完成 Phase 3：User Story 1
4. **STOP and VALIDATE**：`deepresearch/` 独立跑通一次完整研究流程、`check_core_boundary.py`
   零违规——这是一个完整、可独立合并的架构改进，即使 User Story 2/3 还没开始也有价值

### Incremental Delivery

1. Setup + Foundational → 基础就绪
2. User Story 1（服务抽取）→ 独立验证 → 可以单独合并（MVP）
3. User Story 2（一键启动脚本接入）→ 独立验证 → 开发体验不退化
4. User Story 3（前端指向新地址）→ 独立验证 → 用户可见功能完整收尾
5. Polish → 全量回归 + memory 更新

### Parallel Team Strategy

1. 团队一起完成 Setup + Foundational + User Story 1（这是后续一切的地基，建议不拆给多人，
   顺序完成）
2. User Story 1 完成后：
   - 开发者 A：User Story 2（`scripts/start.sh`）
   - 开发者 B：User Story 3（`apps/web` 前端）
3. 两者互不冲突，完成后一起进 Polish

---

## Notes

- `[P]` 任务 = 不同文件、无依赖
- `[Story]` 标签把任务对应回 spec.md 的 User Story 编号，便于追溯
- User Story 2/3 都强依赖 User Story 1（地基），彼此之间无隐藏耦合
- 实现前先验证测试确实失败（RED）
- 建议每个 User Story 完成后提交一次
- 可以在任意 Checkpoint 处停下独立验证对应 Story
- 避免：模糊任务描述、同文件冲突的并行标记、破坏 Story 独立性的跨 Story 依赖（已显式说明的
  除外）
