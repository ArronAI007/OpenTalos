# Quickstart: 验证"DeepResearch 作为独立服务"

> 本文档在 `/speckit-plan` 阶段写出，描述实现完成后应该怎么验证；命令里引用的文件名以
> `/speckit-tasks` 最终产出的 `tasks.md` 为准。

## 前置条件

```bash
cd /Users/arron/Desktop/ArronAI/OpenTalos
test -f deepresearch/pyproject.toml && echo "deepresearch project exists"
```

## 场景 1：完全独立运行，不启动 `apps/api`/`apps/web`（User Story 1）

```bash
cd deepresearch
uv sync
uv run uvicorn main:app --port 8440 &
sleep 2
curl -s http://localhost:8440/health
curl -s -X POST http://localhost:8440/runs -H "Content-Type: application/json" \
  -d '{"topic": "quickstart smoke test"}'
# 记下返回的 id，轮询直到 status 不是 running
curl -s http://localhost:8440/runs/<id>
kill %1
```

预期：`/health` 返回 `{"status": "ok"}`；创建请求返回一个 `status="running"` 的 run；轮询最
终能看到 `status` 变成 `"completed"` 或 `"failed"`（取决于 `.env` 是否配置了真实的模型/
`TAVILY_API_KEY`）。全程不需要 `apps/api`/`apps/web` 进程存在。

## 场景 2：静态检查新目录不依赖 `apps/api`（User Story 1 Acceptance Scenario 3）

```bash
grep -rn "^from db import\|^from runtime import\|from apps\." deepresearch/*.py
```

预期：无匹配（允许 `from ai...`/`from websearch...`/`from core...`，这是 path-dependency
复用方式的预期形态，见 research.md Decision 1）。

## 场景 3：`scripts/start.sh` 原样纳管（User Story 2）

```bash
./scripts/start.sh restart
# 预期输出里出现一行 "deepresearch  http://localhost:8440" 风格的地址
./scripts/start.sh stop
# 预期 deepresearch 进程被连带停掉
```

人为验证降级路径：

```bash
mv deepresearch/pyproject.toml deepresearch/pyproject.toml.bak
./scripts/start.sh restart
# 预期：打印警告并跳过 deepresearch，其余服务（web/api/agentrl/a2apeer）仍然正常启动
mv deepresearch/pyproject.toml.bak deepresearch/pyproject.toml
```

## 场景 4：Web 前端指向新服务（User Story 3）

```bash
# 需要 deepresearch :8440 + apps/web :3010 都在跑（./scripts/start.sh 即可）
# 1. 打开 http://localhost:3010/deepresearch
# 2. 新建一个研究任务，确认进度实时更新（todo_update/report_chunk 事件）、最终报告正常展示
# 3. 确认浏览器 Network 面板里这些请求打在 :8440 而不是 :8400
# 4. 停掉 deepresearch 服务（kill 或 ./scripts/start.sh stop 对应进程），刷新页面，
#    确认出现"服务未启动"类提示，不是白屏或未处理异常
```

## 场景 5：全量回归

```bash
.venv/bin/pytest  # 根项目测试套件：确认 apps/api 相关测试不再引用 deepresearch_runs
cd deepresearch && uv run pytest  # 新服务自己的测试套件，独立运行
cd ../apps/web && npx vitest run  # 前端 deepresearch-api.ts 的改动不破坏既有测试
```

预期：根项目测试数相比抽取前减少（删掉的 deepresearch 相关测试）；`deepresearch/` 自己的测
试套件独立通过，覆盖面不低于抽取前 `tests/apps/api/test_deepresearch.py`；前端测试全部通过。
