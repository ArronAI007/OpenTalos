# OpenTalos

A from-scratch TypeScript monorepo implementing a fully-decoupled agent harness: a graph-based
agent runtime, durable task scheduling with human-in-the-loop (HITL) pause/resume, a
Postgres-backed conversational web UI with live tracing, and a multi-tenant platform services
layer (real API-key auth, tenant/quota management).

Built as four independent, sequentially-developed subsystems, each with its own design spec,
implementation plan, and test suite:

1. **Core Agent Runtime Engine** — the graph execution engine agents run on.
2. **Task Scheduling & Execution Infrastructure** — durable, resumable task execution.
3. **Conversational Web UI** — a chat frontend with live trace visualization.
4. **Platform Services Layer** — tenant auth, API keys, and per-tenant quotas.

## Architecture

### 1. Core Agent Runtime Engine

The foundation every agent graph runs on. An agent is a directed graph of async-generator
**nodes**; a node can `yield` to pause execution (e.g. awaiting a tool call or human approval)
and resume later from exactly where it left off, via a serializable `NodeCursor`.

| Package | Responsibility |
|---|---|
| `packages/core-types` | Shared interfaces: `TenantContext`, `Message`, `ToolDefinition`, `CheckpointStore`, `EventBus`, `MemoryStore`. |
| `packages/core-graph` | `GraphEngine` — runs a `GraphDefinition` node-by-node, handling yields, resumption, and state reduction. |
| `packages/checkpoint` | `InMemoryCheckpointStore` — reference implementation of run-state persistence. |
| `packages/tracing` | `InMemoryEventBus` — reference implementation of trace-event pub/sub. |
| `packages/memory` | `InMemoryMemoryStore` — tenant/session-scoped agent memory. |
| `packages/model-providers` | LLM provider adapters: Anthropic, OpenAI-compatible, Ollama. |
| `packages/tool-registry` | Tool registration, including an MCP (Model Context Protocol) adapter. |
| `packages/multi-agent` | Composable multi-agent patterns: supervisor/router and swarm graphs. |
| `packages/config-loader` | Declarative graph definitions (YAML/JSON) compiled into `GraphDefinition`s. |
| `packages/sdk` | `defineGraph` — the ergonomic entry point tying the above together for a single-process agent. |

### 2. Task Scheduling & Execution Infrastructure

Promotes the runtime engine from in-process/in-memory to a durable, horizontally-scalable system:
runs are persisted as rows in Postgres and executed by one or more polling `Worker` processes,
so a paused (HITL) run can be resumed hours later, by a different process, without losing state.

| Package | Responsibility |
|---|---|
| `packages/scheduler` | `GraphRegistry`, `Scheduler` (enqueues/resumes runs as tasks), `Worker` (polls and executes tasks with global + per-tenant concurrency caps). |
| `packages/postgres-checkpoint` | Drizzle/Postgres-backed `CheckpointStore`. |
| `packages/postgres-tracing` | Drizzle/Postgres-backed `EventBus`, plus `listEventsSince` for SSE catch-up. |
| `apps/worker` | The long-running process that polls the `tasks` table and executes claimed runs. |

### 3. Conversational Web UI

A minimal chat app demonstrating the full stack end to end: send a message, watch the agent's
trace stream in over Server-Sent Events, approve a paused tool call, see the final reply.

| App | Responsibility |
|---|---|
| `apps/api` | Fastify REST API: `POST /runs`, `POST /runs/:id/resume`, `GET /runs/:id`, `GET /runs/:id/events` (SSE). |
| `apps/web` | React + Vite chat UI, with a live trace drawer and human-approval controls. |
| `packages/chat-agent` | The chat graph served by `apps/api` — calls a real model (with tools), pauses for human approval, replies. |
| `examples/research-agent` | A second example graph showing the `multi-agent` supervisor pattern (researcher → writer). |

### 4. Platform Services Layer

Replaces a hardcoded single-tenant setup with real multi-tenant operation: API-key
authentication, tenant management, and per-tenant differentiated concurrency quotas.

| Package/App | Responsibility |
|---|---|
| `packages/postgres-tenancy` | `TenantStore` — tenants and hashed API keys (`tk_<hex>`, SHA-256 at rest), with 401 (invalid key) vs. 403 (valid key, disabled tenant) discrimination. |
| `apps/api` (auth additions) | `createTenantAuthHook` protects every `/runs*` route (`Authorization: Bearer` header or `?apiKey=` query param, for SSE); `/admin/*` routes are separately protected by a bootstrap `ADMIN_API_KEY` secret. |
| `apps/admin` | React app for tenant and API-key management (create/list/disable tenants, issue/revoke keys, set per-tenant quotas). |
| `apps/web` (auth additions) | Gated behind a real API key entered once and stored client-side; a revoked/invalid key routes back to re-entry. |
| `packages/scheduler` (quota additions) | `Worker`'s optional `resolveTenantConcurrency` hook resolves each tenant's cap once per poll cycle, falling back to a static default — omitting it is fully backward-compatible. |

## Repository Layout

```
opentalos/
├── packages/        # Core runtime, scheduling, and platform libraries
├── apps/            # Deployable processes: api, worker, web, admin
├── examples/        # Example agent graphs served by apps/api
└── docs/            # Design specs & implementation plans (gitignored, kept local)
```

Managed as a pnpm workspace + Turborepo monorepo (`pnpm-workspace.yaml`: `packages/*`,
`apps/*`, `examples/*`). Every package is TypeScript, ESM/NodeNext, tested with Vitest;
Postgres-backed packages use [Testcontainers](https://node.testcontainers.org/) to test against
a real, ephemeral Postgres instance rather than mocks.

## Quick Start

**Prerequisites:** Node ≥20, pnpm, Docker (for Postgres and for running tests against real
Postgres instances via Testcontainers).

```bash
pnpm install

# Build, typecheck, and test everything
pnpm run build
pnpm run typecheck
pnpm run test
```

### Running the full stack locally

```bash
# 1. Start Postgres
docker compose -f apps/web/e2e/docker-compose.yml up -d

# 2. Build the processes that need a compiled dist/ to run
pnpm --filter @opentalos/worker build
pnpm --filter @opentalos/api build

# 3. Start each process (separate terminals)
DATABASE_URL=postgres://postgres:postgres@localhost:5433/postgres \
  pnpm --filter @opentalos/worker start

DATABASE_URL=postgres://postgres:postgres@localhost:5433/postgres \
  ADMIN_API_KEY=<pick-a-secret> \
  PORT=3001 \
  pnpm --filter @opentalos/api start

pnpm --filter @opentalos/web dev      # http://localhost:5173
pnpm --filter @opentalos/admin dev    # http://localhost:5174
```

On first run, use the admin UI (`:5174`) with your chosen `ADMIN_API_KEY` to create a tenant and
issue it an API key, then enter that key in the chat UI (`:5173`) to start using it.

### End-to-end tests

```bash
pnpm --filter @opentalos/web test:e2e
```

Playwright's `webServer` config starts `worker`/`api`/`web`/`admin` automatically and seeds a
default tenant + API key via `globalSetup` — no manual process startup needed for this path.

## Key Environment Variables

| Variable | Used by | Default | Notes |
|---|---|---|---|
| `DATABASE_URL` | `apps/worker`, `apps/api` | `postgres://postgres:postgres@localhost:5432/opentalos` | |
| `ADMIN_API_KEY` | `apps/api` | *(required, no default)* | Bootstrap secret for `/admin/*` routes; process fails fast at startup if unset. |
| `PORT` | `apps/api` | `3001` | |
| `HEALTH_PORT` | `apps/worker` | `3002` | Plain-text health check endpoint. |
| `WORKER_GLOBAL_CONCURRENCY` | `apps/worker` | `10` | Cap across all tenants combined. |
| `WORKER_TENANT_CONCURRENCY` | `apps/worker` | `5` | Static fallback cap per tenant, when a tenant has no configured quota. |

## Design Principles

- **Decoupling**: each subsystem depends only on `core-types`' interfaces, never on a concrete
  in-memory or Postgres implementation — swapping `InMemoryCheckpointStore` for
  `PostgresCheckpointStore` requires no changes to `core-graph` or the agent graphs themselves.
- **Resumability**: an agent node that `yield`s (for a tool call or human approval) can be
  resumed by any worker process, at any later time, from a durable `NodeCursor` — this is what
  makes human-in-the-loop approval workflows practical at scale.
- **Backward compatibility**: new capabilities (e.g. per-tenant quotas) are added as optional
  hooks with byte-identical default behavior when omitted, so existing callers never break.
- **Real dependencies in tests**: Postgres-backed packages are tested against a real, ephemeral
  Postgres via Testcontainers — never mocked — so tests catch actual SQL/schema issues.
