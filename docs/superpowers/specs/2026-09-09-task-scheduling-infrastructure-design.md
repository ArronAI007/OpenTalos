# 任务调度与执行基础设施 — 设计文档

- 日期：2026-09-09
- 状态：已批准，待写实施计划
- 范围：OpenTalos 平台的第二个子系统。第一个子系统（核心 Agent 运行时引擎）已完成并合并至 `main`。整体平台还包括对话 Web UI、平台服务层，均为独立子项目，不在本文档范围内。

## 1. 背景与目标

第一个子系统交付了 `@opentalos/core-graph` 的 `GraphEngine`：一个无状态、每步可产生 JSON 可序列化 `Checkpoint` 的图执行引擎。但它有一个明确记录的限制——`resume()` 只能在同一进程内恢复一个暂停的节点，因为暂停的 JS `generator` 实例只存在于内存里的 `Map<runId, {tenant, generator}>` 中。真实的持久化后端、任务队列、跨进程/跨重启的执行，在第一个子系统的设计文档中被显式列为"不在本阶段范围内"。

本子系统的目标就是补上这块留白：

- 让暂停的图执行能够真正跨进程、跨重启恢复，而不只是在同一个 Node 进程存活期间。
- 提供一个真实的、基于 PostgreSQL 的 `CheckpointStore` 实现。
- 提供一个任务队列 + worker 调度层，能够并发执行多个租户的多个图运行，并遵守并发配额、超时与重试策略。

## 2. 核心设计：让 GraphEngine 支持跨进程恢复

### 2.1 问题

`GraphEngine.resume(checkpoint, resumeValue)` 依赖 `this.paused.get(checkpoint.runId)` 取回一个还活着的 generator 实例。这个 Map 是进程内存，进程重启或换一个进程调用就会拿到 `undefined`，触发"Cross-process resume is not supported"错误——这是第一阶段刻意设计的边界，不是 bug。

### 2.2 方案：Replay-safe 重新执行

暂停发生在某个节点执行到一半（yield 了 `awaiting_approval`）的时刻。关键观察：`Checkpoint.state` 在节点暂停时**没有被修改**——它仍然是这个节点开始执行前的输入状态（`engine.ts` 的 `step()` 在暂停分支里只是 `{...checkpoint, nodeCursor, status:"paused", pendingYields}`，`state` 原样保留）。

这意味着：只要节点函数在第一次 `yield` 之前不做不可重复的副作用（"replay-safe"，与 Temporal.io 工作流的确定性重放假设一致），我们就可以：

1. 用 checkpoint 里保存的 `state` **重新调用**该节点函数，得到一个全新的 generator。
2. 正常驱动它（自动解析 `awaiting_tool`，就像 `runNodeToCompletion` 已经做的那样）。
3. 遇到 `awaiting_approval` yield 时，按顺序喂给它一个"重放队列"里的值，而不是遇到第一个就直接暂停。
4. 队列耗尽后遇到的下一个 `awaiting_approval` yield，才是真正需要暂停、等待外部新决策的那个。

**关键细节（脑暴阶段遗漏、自查时补上的）**：一个节点在同一次执行里可能暂停不止一次（例如 guardrail 的 before 和 after 阶段都要求审批——这是第一阶段就支持、且已有测试覆盖的场景）。如果重放时只喂给"遇到的第一个" `awaiting_approval` yield 外部传入的新 `resumeValue`，而 checkpoint 实际暂停在这次执行的第二次（甚至更晚）的 yield 点，就会用新答案错误地回答一个早就回答过的旧问题，而真正待回答的问题反而没有被处理——静默产生错误语义，而不是报错。

正确做法：`Checkpoint.pendingYields` 记录的不只是"当前待回答的问题"，而是"这次执行里已经被回答过的历史答案（按顺序）+ 当前待回答的问题"（数组的最后一个元素）。首次由 `step()` 产生的暂停 checkpoint，`pendingYields` 长度恒为 1（没有历史，是 Phase 1 就已经批准、且已有测试锁定的形状，不能改变）；如果 `resumeFromCheckpoint` 自己在重放中再次暂停，才会把 `pendingYields` 变成长度 >1 的数组（历史答案 + 新的待回答问题）。下一次 `resumeFromCheckpoint` 调用会先取出"除最后一个元素外的所有元素"作为重放队列的前缀（依次喂给重放过程中遇到的每一个 yield，逐一让节点重新确认），再把这次外部传入的新 `resumeValue` 追加在队列末尾——只有队列耗尽后遇到的下一个 yield，才是真正待处理的新暂停点。

### 2.3 对 `core-graph` 的增量扩展

在 `packages/core-graph/src/engine.ts` 新增一个公开方法 `resumeFromCheckpoint`，并给私有方法 `runNodeToCompletion` 增加一个可选参数 `replayQueue`（一个待消费的答案队列，而非单个值）：

- `runNodeToCompletion` 遇到 `awaiting_approval` yield 时，如果 `replayQueue` 还有剩余元素，就 `shift()` 出队首值推进一步；队列耗尽后遇到的 yield，才维持原有行为（调用 `onApprovalPause` 并返回 paused）。
- `resumeFromCheckpoint(checkpoint, resumeValue)`：校验 `status==="paused"`，取出 `nodeCursor`（节点 id）与 `graph.nodes[nodeCursor]`，用 `checkpoint.state` 重新构造该节点的（可能被 guardrail 包裹的）generator；从 `checkpoint.pendingYields`（去掉最后一个元素）恢复出历史答案，拼上这次的 `resumeValue` 作为 `replayQueue` 传给 `runNodeToCompletion`；得到的结果和 `resume()` 一样走 `completeNode` → 如果状态变为 running 就继续 `this.run()`；如果再次暂停，把完整的 `replayQueue` 加上新的待回答问题一起写回 `pendingYields`，供下一次 `resumeFromCheckpoint` 调用使用。

这是对已批准的 `engine.ts` 的**纯增量**修改：所有既有方法（`step`、`resume`、`run`）的行为和签名完全不变，已有测试不受影响。`resume()`（同进程、内存 generator）和 `resumeFromCheckpoint()`（跨进程、重放）是两条并行的恢复路径，各自服务不同场景——前者留给单进程内的即时人机交互，后者是本子系统的调度层实际使用的路径。

一次节点完整跑完之后，后续的 `step()` 调用本来就是对全新节点的调用，天然跨进程安全。所以"节点执行到一半暂停"是唯一需要这个新机制解决的缺口，解决之后整条执行链路就是完整可持久化的了。

## 3. 包结构

```
packages/
├── postgres-checkpoint/     # 真实 CheckpointStore 实现（Drizzle + PostgreSQL）
│   ├── src/schema.ts         # Drizzle schema：checkpoints 表
│   ├── src/store.ts          # PostgresCheckpointStore implements CheckpointStore
│   └── drizzle/               # drizzle-kit 生成的迁移文件
└── scheduler/                # 任务队列 + 单进程异步并发 worker
    ├── src/graph-registry.ts  # graphId(字符串) → 完整 GraphDefinition + EngineDeps 构建函数 的映射
    ├── src/schema.ts          # Drizzle schema：tasks 表
    ├── src/enqueue.ts         # enqueueStart / enqueueResume
    └── src/worker.ts          # 轮询循环、并发配额、超时、重试退避
```

`scheduler` 依赖 `core-graph`（用其 `GraphEngine`/`resumeFromCheckpoint`）、`postgres-checkpoint`（真实持久化）、`core-types`（接口）。它不依赖任何具体的模型/工具实现——那些由调用方通过 `graph-registry` 注入，延续第一阶段"引擎与具体实现解耦"的原则。

### 3.1 为什么需要 `graph-registry`

数据库里只能存 `graphId` 字符串、初始 state、tenant 信息——真正的 `GraphDefinition`（节点函数是闭包）无法序列化进数据库。调用方在进程启动时注册一张"`graphId` → 构建函数"的表；worker 执行任务时按 `graphId` 查表，重新构建出可执行的 `GraphDefinition` + `EngineDeps`（工具注册表、事件总线等）。这与第一阶段 `config-loader` "按名字解析节点工厂"的思路一致，只是这次解析的是整张图。

```ts
export interface GraphRegistration<TState> {
  buildGraph: () => GraphDefinition<TState>;
  buildDeps: () => Omit<EngineDeps, "checkpointStore">; // checkpointStore 总是注入 PostgresCheckpointStore
}
export interface GraphRegistry {
  register<TState>(graphId: string, registration: GraphRegistration<TState>): void;
  get(graphId: string): GraphRegistration<unknown> | undefined;
}
```

## 4. `postgres-checkpoint` 包

`checkpoints` 表（Drizzle schema）：`run_id`（主键）、`graph_id`、`tenant_id`、`session_id`、`node_cursor`（jsonb）、`state`（jsonb）、`pending_yields`（jsonb）、`status`、`created_at`、`updated_at`。`PostgresCheckpointStore implements CheckpointStore`：`save` 用 `INSERT ... ON CONFLICT (run_id) DO UPDATE`（upsert，语义等价于 Phase 1 `InMemoryCheckpointStore` 的 `Map.set` 覆盖行为），`load`/`list` 直接查询并按 `@opentalos/core-types` 的 `Checkpoint` 形状反序列化。

## 5. `scheduler` 包：任务队列与 Worker

### 5.1 `tasks` 表

字段：`id`（自增主键）、`run_id`、`graph_id`、`tenant_id`、`session_id`、`kind`（`'start' | 'resume'`）、`resume_value`（jsonb，仅 `resume` 任务需要）、`status`（`'queued' | 'running' | 'done' | 'failed'`）、`attempts`、`max_attempts`、`timeout_ms`、`priority`、`available_at`（重试退避用）、`locked_at`、`error`（失败原因）、`created_at`、`updated_at`。

`enqueueStart(graphId, initialState, tenant, options)`：调用 `graph-registry` 校验 `graphId` 已注册，用 `GraphEngine.start()` 生成初始 checkpoint（`status:"running"`），显式调用 `checkpointStore.save()` 落库（`start()` 本身无副作用，只构造对象，这是第一阶段就确立的约定），再插入一条 `kind:'start'` 的 `tasks` 行。

`enqueueResume(runId, resumeValue, options)`：从 `postgres-checkpoint` 加载 checkpoint，校验 `status === 'paused'`（否则明确报错，而不是静默排队一个永远不会推进的任务），插入一条 `kind:'resume'` 的 `tasks` 行。

### 5.2 Worker 循环

单进程内的异步并发模型：一个循环持续执行

```sql
SELECT * FROM tasks
WHERE status = 'queued' AND available_at <= now()
ORDER BY priority DESC, created_at ASC
FOR UPDATE SKIP LOCKED
LIMIT :batchSize
```

在应用内存里维护 `Map<tenantId, number>` 记录当前"正在执行中"的任务数（单进程模型下这是权威计数，不需要额外的 SQL 层面约束）。对每个候选任务：如果全局并发计数或该租户并发计数已达上限，跳过（该行保持 `queued`，留到下一轮轮询，事务内不做任何修改即可安全释放行锁）；否则在同一事务里把该行标记为 `running` 并提交，随即在内存中异步执行（不阻塞轮询循环去处理下一批）。

执行逻辑：按 `graphId` 从 registry 取回 `GraphDefinition`/`EngineDeps`（`checkpointStore` 固定注入 `PostgresCheckpointStore`），构造 `GraphEngine`；`kind==='start'` 时调用 `engine.run(checkpoint)`，`kind==='resume'` 时先 `checkpointStore.load(runId)` 拿到当前 checkpoint 再调用 `engine.resumeFromCheckpoint(checkpoint, resumeValue)`。用 `Promise.race` 包一层 `timeout_ms` 的定时器。

结果处理：正常完成或再次暂停 → 任务标记 `done`（checkpoint 本身已经反映了真实状态，任务表只需记录"这次调度动作处理完了"）；抛出异常或超时 → `attempts += 1`，若 `attempts < max_attempts` 则按指数退避写回 `available_at = now() + backoff(attempts)` 并保持 `queued`，否则标记 `failed` 并记录 `error`。

## 6. 数据流（一次完整的人工审批场景）

```
调用方 enqueueStart(graphId, initialState, tenant)
  → 写入 checkpoint(status:running) + tasks 行(kind:start, status:queued)
  → worker 轮询取到任务，通过并发配额检查 → 标记 running
  → 按 graphId 从 registry 建出 GraphEngine（注入 PostgresCheckpointStore）
  → engine.run() 跑到暂停 → checkpoint 落库(status:paused)，任务标记 done
  ...（可能是另一次部署 / 另一个 worker 实例 / 数小时之后）...
人工做出决定 → 调用方 enqueueResume(runId, resumeValue)
  → 校验 checkpoint 确实是 paused → 写入 tasks 行(kind:resume, status:queued)
  → worker 取到任务 → 从 postgres-checkpoint 加载 checkpoint
  → engine.resumeFromCheckpoint(checkpoint, resumeValue)
  → 跑到完成或再次暂停 → checkpoint 落库，任务标记 done
```

## 7. 测试策略

- **`core-graph` 的 `resumeFromCheckpoint`**：用现有的内存依赖（`InMemoryCheckpointStore`/`InMemoryEventBus`/`InMemoryToolRegistry`）做单元测试，验证"用全新 generator + replay 恢复"与"同进程 `resume()`"在最终状态、事件序列上等价；覆盖单次暂停、guardrail 导致的连续两次暂停、以及"重放到暂停点之前有工具调用需要被重新自动解析"的场景。
- **`postgres-checkpoint`**：针对真实 PostgreSQL（本地或 CI 里的 Postgres 服务）的集成测试，覆盖 save/load/list、以及 upsert 覆盖语义与 Phase 1 `InMemoryCheckpointStore` 的行为对齐。
- **`scheduler`**：针对真实 PostgreSQL 的集成测试，覆盖：`FOR UPDATE SKIP LOCKED` 下多个"并发 worker"不会重复领取同一任务；租户并发上限生效（超额任务保持排队）；全局并发上限生效；任务超时后重试与指数退避；重试次数耗尽后标记 `failed`；以及一个端到端场景——用两个**独立创建的** `Worker`/`GraphEngine` 实例（模拟两次不同的进程调用）先后处理同一个 `run_id` 的 start 任务和 resume 任务，证明真正跨"进程"（跨实例）的持久化恢复是成立的，而不只是同一个内存态的巧合。

## 8. 明确不在本阶段范围内

- 分布式/多机 worker 部署（本阶段是单进程内异步并发，多进程/多机的协调留给未来）。
- 对话 Web UI 对执行轨迹/暂停状态的可视化——那是第三个子系统的工作，本子系统只保证 `EventBus`/`CheckpointStore` 里有它需要的数据。
- 认证、租户资源配额的管理界面/API——本子系统只在 worker 内部强制执行配额数字，配额本身如何被设置、由谁设置，留给第四个子系统（平台服务层）。
- Redis/BullMQ 或任何其他队列技术——已决定完全用 PostgreSQL 承载队列语义（`FOR UPDATE SKIP LOCKED`），本阶段不引入额外的基础设施依赖。
