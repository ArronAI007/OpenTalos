# 核心 Agent 运行时引擎 — 设计文档

- 日期：2026-09-09
- 状态：已批准，待写实施计划
- 范围：OpenTalos 平台的第一个子系统。整体平台还包括任务调度与执行基础设施、对话 Web UI、平台服务层（认证/多租户管理），这些均为独立子项目，各自会有自己的 brainstorming → spec → plan 流程，不在本文档范围内。

## 1. 背景与目标

OpenTalos 是一个从零搭建的 agent harness，目标是支持当前主流 agent harness 的关键技术能力（工具调用/MCP、多智能体编排、Planning/ReAct、记忆与 RAG、HITL/护栏、流式与结构化输出、可观测执行轨迹、多模型厂商抽象），代码脚手架要求完全解耦，并最终支撑多租户、高并发、长任务运行等平台级能力。

本子项目负责这套系统的地基：**核心 Agent 运行时引擎**。它必须：

- 提供一个可被其他子系统安全复用的执行内核，自身不做任何假设自己是唯一实例、唯一租户、唯一进程。
- 通过接口（ports）与所有具体实现（模型厂商、工具协议、存储、追踪）解耦，使得替换或移除任一实现包都不影响引擎本身。
- 暴露足够的钩子（检查点、事件流、护栏拦截点），让后续的任务调度子系统和 Web UI 子系统能够分别实现"可中断/恢复的长任务"和"执行轨迹可视化"，而无需修改引擎内部。

## 2. 技术栈与 Monorepo 方案

- 语言：TypeScript / Node.js。
- 包管理与构建：pnpm workspace + Turborepo（增量构建/缓存，社区主流，便于后续接入 Web UI 子系统时共享工具链）。
- 模型 Provider 优先级：Anthropic Claude（首选/默认适配器）→ OpenAI 兼容接口（含 GPT 及大量开源模型的 OpenAI 兼容 API）→ 本地模型（Ollama 等）。三者都在本阶段实现适配器，行为通过同一 `ModelProvider` 接口收敛。

### 包结构

```
opentalos/
├── packages/
│   ├── core-graph/          # 图执行引擎（Generator 驱动，状态/检查点模型）
│   ├── core-types/          # 跨包共享类型与接口定义（ports），零运行时依赖
│   ├── model-providers/     # ModelProvider 适配器：anthropic / openai-compatible / ollama
│   ├── tool-registry/       # 工具注册与调用，原生 MCP client 支持
│   ├── memory/              # MemoryStore 接口 + 内置实现（内存版 + 可插拔向量库适配器）
│   ├── checkpoint/          # CheckpointStore 接口 + 内置内存实现
│   ├── tracing/             # EventBus/Tracer：结构化事件流
│   ├── multi-agent/         # 子图节点、supervisor/swarm 编排原语（构建于 core-graph 之上）
│   ├── sdk/                 # 代码驱动入口：组合各包，提供人体工学 API
│   └── config-loader/       # 声明式配置入口：将 YAML/JSON 编译为 core-graph 图
├── examples/                 # 最小可运行示例，兼作集成测试载体
└── turbo.json / pnpm-workspace.yaml
```

**解耦原则**：`core-graph` 只依赖 `core-types` 中定义的接口，不引用任何具体实现包。`model-providers`、`tool-registry`、`memory`、`checkpoint`、`tracing` 都是"实现细节"，可被替换或删除而不触及 `core-graph`。`sdk` 与 `config-loader` 是两个平行的组装层，职责仅是把实现按接口注入到 `core-graph`，二者互不依赖。

## 3. 核心执行模型

执行范式采用**混合模式**：底层统一为图/状态机引擎，对上同时提供代码驱动（`sdk`）与声明式配置（`config-loader`）两种构建方式。

图内部的推进模型采用 **Generator/Coroutine 驱动**（相对 Pregel 超步模型和 Actor 消息总线模型，实现复杂度最低，且与"引擎无状态、每步可检查点"的目标天然契合）：

- **图模型**：节点（Node）+ 边（Edge，含条件边）构成有向图；支持分支、循环、fan-out/fan-in（并行节点）、子图嵌套（用于多智能体委派/supervisor-worker 结构）。
- **节点即 Generator**：每个节点是 `function* (state, ctx)`，通过 `yield` 暴露可恢复点（如"等待工具结果""等待人工审批"）。引擎本体是纯函数 `step(graph, checkpoint) → nextCheckpoint`，不持有运行时单例状态，不缓存任何跨调用的可变数据。
- **状态（State）**：不可变数据结构；每一步产生新状态对象，通过 reducer 函数合并节点输出，绝不原地修改。
- **检查点（Checkpoint）**：`{ graphId, nodeCursor, state, pendingYields, tenantId, sessionId }`，可被 `JSON.stringify`。引擎只通过 `CheckpointStore` 接口的 `save/load/list` 三个方法与持久化交互，本阶段只提供内存实现；真正的持久化后端（数据库/对象存储）由后续的任务调度子系统实现并注入。
- **多租户隔离**：`tenantId`/`sessionId` 是执行上下文的必填字段，贯穿所有事件、日志、检查点。引擎零全局状态、零单例，天然支持同进程内并发运行多个租户的独立图实例，互不干扰。

## 4. 关键接口（`core-types`）

均为纯 TypeScript interface，无运行时依赖：

| 接口 | 职责 |
|---|---|
| `ModelProvider` | `complete(messages, tools, opts) → streamable response`，屏蔽厂商差异，支持流式与结构化（schema 校验）输出 |
| `Tool` / `ToolRegistry` | 工具描述（JSON Schema）+ 执行函数；`tool-registry` 包内置 MCP client，把远程 MCP server 暴露的工具适配为本接口 |
| `MemoryStore` | `read/write/search`，用于短期上下文压缩与长期记忆/RAG 检索 |
| `CheckpointStore` | 持久化端口：`save(checkpoint) / load(id) / list(query)`，本阶段只提供内存实现 |
| `EventBus` / `Tracer` | `emit(event)`：事件类型包括 `llm_call_start/end`、`tool_call_start/end`、`node_enter/exit`、`hitl_interrupt`、`error`；Web UI 子系统未来直接消费这个事件流渲染执行轨迹时间线 |
| `Guardrail` | 节点执行前/后的校验钩子，返回"放行 / 拦截 / 需人工确认" |

## 5. 数据流（一次执行）

```
调用方（sdk 或 config-loader）组装 Graph + 初始 Context（含 tenantId/sessionId）
  → core-graph.step() 循环推进
       ├─ 每个节点执行前后 emit 事件到 Tracer
       ├─ 遇到工具调用 → ToolRegistry.execute()（经过 Guardrail 校验）
       ├─ 遇到 HITL 节点 → yield，返回 pendingCheckpoint 给调用方，暂停执行
       └─ 每步结束调用 CheckpointStore.save()（内置内存实现，调用方可替换为持久化实现）
  → 到达终止节点 → 返回最终 state + 完整 trace 事件列表
```

## 6. 多智能体编排（`multi-agent`）

构建在 `core-graph` 之上，不修改引擎内核：

- **子图节点**：一个节点内部封装完整的子图，对外表现为普通节点，用于将"子智能体"建模为可复用单元。
- **Supervisor 模式**：一个决策节点根据当前状态选择下一个要调用的子图节点（子智能体），循环直到任务完成。
- **Swarm/并行委派**：fan-out 节点并行触发多个子图分支，fan-in 节点合并结果，用于并行调用多个子智能体后汇总。

## 7. 错误处理与护栏

- 节点级 try/catch，异常包装为标准 `NodeError{nodeId, cause, recoverable}` 并 emit `error` 事件，绝不静默吞掉。
- 重试逻辑通过图上显式建模的重试边实现，不是引擎内置的隐藏行为——保持引擎行为可预测、可追溯。
- Guardrail 拦截产生 `hitl_interrupt` 检查点，暂停执行并等待外部注入人工决策后恢复（人工决策的采集与 UI 呈现属于后续子系统范围）。

## 8. 测试策略

- 遵循 TDD：先写测试（RED）→ 最小实现（GREEN）→ 重构（IMPROVE），覆盖率目标 80%+；`core-graph`、`core-types` 作为地基模块要求更高覆盖率。
- 单元测试：节点执行、reducer 合并逻辑、条件边求值、Generator 暂停/恢复语义。
- 集成测试：`examples/` 目录下的最小可运行图，验证端到端场景——包括检查点保存/恢复、暂停后从检查点精确恢复、并行 fan-out/fan-in 正确性、MCP 工具调用往返、多租户上下文隔离（同进程并发跑两个不同 tenantId 的图互不干扰）。

## 9. 明确不在本阶段范围内

- 真实的持久化后端（数据库/对象存储）实现——只定义 `CheckpointStore` 接口和内存实现。
- 高并发任务队列、任务调度、跨进程/跨机器的执行——留给任务调度子系统。
- 任何 Web UI 或 HTTP/gRPC 对外服务层——留给对话 Web UI 子系统。
- 认证、租户管理、计费——留给平台服务层子系统。
- 向量数据库的具体接入（如 pgvector/Pinecone）——`memory` 包本阶段只定义接口和内存实现。
