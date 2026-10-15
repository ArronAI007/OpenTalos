# Contract: DeepResearch 独立服务 HTTP API

对应 spec.md FR-003/FR-007/FR-008、User Story 1/3。镜像现状 `apps/api/main.py` 的
`/api/deepresearch/*` 路由行为，路径改为扁平约定（见 research.md Decision 2）。

## 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查，`scripts/start.sh` 的 `ensure_service` 探测用 |
| `POST` | `/runs` | 创建一个研究任务，后台异步执行 |
| `GET` | `/runs` | 列出全部研究任务 |
| `GET` | `/runs/{id}` | 查询一个研究任务的当前状态 |
| `GET` | `/runs/{id}/stream` | SSE 订阅一个研究任务的实时进度 |
| `DELETE` | `/runs/{id}` | 删除一个研究任务 |

## 请求/响应契约

### `GET /health`

响应：`{"status": "ok"}`，状态码 200（和 `apps/api`/`agentrl`/`a2apeer` 完全一致的约定）。

### `POST /runs`

请求体：

```python
class CreateRunBody(BaseModel):
    topic: str
```

校验：`topic` 去空白后非空，否则 400。`TAVILY_API_KEY` 未配置（懒加载的 search client 为
`None`）时返回 503（和现状 `apps/api` 的 `runtime.search_client is None → 503` 逐字一致）。

响应：新建的 `ResearchRun`（`status="running"`，`todos=[]`，`report=null`，`error=null`），
状态码 200。成功响应后，服务器在后台 `asyncio.create_task` 里异步跑完规划→并行搜索总结→合
成报告的全过程（不阻塞这次请求）。

### `GET /runs`

响应：`{"runs": ResearchRun[]}`，按 `created_at DESC, rowid DESC` 排序。

### `GET /runs/{id}`

响应：完整的 `ResearchRun`。未知 `id` → 404。

### `GET /runs/{id}/stream`

`Content-Type: text/event-stream`。未知 `id` → 推一帧 `{"type": "error", "message": "run not
found"}` 后立即结束流（不是 HTTP 404——现状行为如此，SSE 连接本身总是能建立）。`status !=
"running"` 的 run → 推一帧 `{"type": "snapshot", "run": ResearchRun}` 后立即结束。
`status == "running"` 的 run → 先推一帧 `snapshot`（可能带 `report` 字段的部分流式内容），
随后持续推送 `todo_update`/`report_chunk` 事件，直到收到 `run_done` 事件为止。

### `DELETE /runs/{id}`

未知 `id` → 404。`status == "running"` 的 run → 409（不允许删除进行中的任务，和现状行为逐
字一致）。成功 → 204。

## 行为契约

1. **路径形状**：全部路径不带 `/api` 或 `deepresearch` 前缀（research.md Decision 2）。
2. **字段形状**：`ResearchRun`/`ResearchTodo` 的字段名、类型、取值枚举与抽取前的
   `apps/api` 实现逐字一致（见 data-model.md），前端 TypeScript 接口不需要改字段，只改请求
   路径和 base URL。
3. **懒加载降级**：模型/搜索客户端未配置时，服务本身仍然正常启动、`/health` 仍然返回
   `{"status": "ok"}`；只有真正发起 `POST /runs` 才会暴露配置缺失（research.md Decision
   3）。
4. **并发研究任务**：多个 `run_id` 可以同时处于 `running` 状态，互不影响（现状行为，
   `_live_runs` 按 `run_id` 隔离）。

## 独立测试方式

- 不启动 `apps/api`/`apps/web`，只用 `deepresearch/` 自己的测试套件（`uv run --directory
  deepresearch pytest`）验证全部路由 + `research.py` 内部逻辑（见 research.md Decision 7 的
  测试文件清单）。
- 真机验证：`scripts/start.sh` 启动后，`curl http://localhost:8441/health`、
  `curl -X POST http://localhost:8441/runs -d '{"topic": "..."}'`、在浏览器打开
  DeepResearch 页面走一遍完整交互（见 quickstart.md）。
