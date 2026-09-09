# Core Agent Runtime Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the core Agent runtime engine for OpenTalos — a generator-driven graph execution engine, fully decoupled from any specific model provider/tool protocol/storage backend via `core-types` interfaces, that supports tool calling + MCP, multi-agent orchestration, HITL pauses, and per-step checkpointing.

**Architecture:** A pnpm + Turborepo monorepo of small TypeScript packages. `core-types` defines zero-dependency interfaces (`ModelProvider`, `Tool`/`ToolRegistry`, `MemoryStore`, `CheckpointStore`, `EventBus`, `Guardrail`, `Checkpoint`). `core-graph` is a stateless `GraphEngine` class that drives async-generator node functions node-by-node, auto-resolves tool-call yields through an injected `ToolRegistry`, pauses on approval yields (HITL) and saves a serializable `Checkpoint`, and supports fan-out/fan-in and subgraph nesting. Implementation packages (`checkpoint`, `tracing`, `memory`, `tool-registry`, `model-providers`) provide in-memory / adapter implementations of those interfaces without `core-graph` ever importing them. `multi-agent`, `sdk`, and `config-loader` are composition layers on top of `core-graph`. A final `examples/research-agent` package proves the whole stack end-to-end.

**Tech Stack:** TypeScript (Node >= 20, ESM/`NodeNext`), pnpm workspaces, Turborepo, Vitest, `@modelcontextprotocol/sdk` (MCP), `js-yaml` + `zod` (config-loader).

Reference spec: `docs/superpowers/specs/2026-09-09-core-agent-runtime-engine-design.md`

---

## Task 1: Monorepo Scaffold

**Files:**
- Create: `package.json`
- Create: `pnpm-workspace.yaml`
- Create: `turbo.json`
- Create: `tsconfig.base.json`
- Create: `.gitignore`

This task only creates configuration — there is no runtime logic to test yet. Correctness is verified by `pnpm install` succeeding.

- [ ] **Step 1: Create root `package.json`**

```json
{
  "name": "opentalos",
  "private": true,
  "version": "0.0.0",
  "packageManager": "pnpm@12.3.4",
  "engines": {
    "node": ">=20"
  },
  "scripts": {
    "build": "turbo run build",
    "test": "turbo run test",
    "typecheck": "turbo run typecheck"
  },
  "devDependencies": {
    "turbo": "^2.10.12",
    "typescript": "^7.0.2",
    "vitest": "^5.0.0"
  }
}
```

- [ ] **Step 2: Create `pnpm-workspace.yaml`**

```yaml
packages:
  - "packages/*"
  - "examples/*"
```

- [ ] **Step 3: Create `turbo.json`**

```json
{
  "$schema": "https://turbo.build/schema.json",
  "tasks": {
    "build": {
      "dependsOn": ["^build"],
      "outputs": ["dist/**"]
    },
    "test": {
      "dependsOn": ["^build"]
    },
    "typecheck": {
      "dependsOn": ["^build"]
    }
  }
}
```

- [ ] **Step 4: Create `tsconfig.base.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022"],
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "declaration": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "forceConsistentCasingInFileNames": true
  }
}
```

- [ ] **Step 5: Create `.gitignore`**

```
node_modules
dist
.turbo
*.tsbuildinfo
```

- [ ] **Step 6: Verify install works**

Run: `pnpm install`
Expected: Completes without errors, creates `pnpm-lock.yaml` (there are no packages yet, so nothing is installed besides root devDependencies).

- [ ] **Step 7: Commit**

```bash
git add package.json pnpm-workspace.yaml turbo.json tsconfig.base.json .gitignore pnpm-lock.yaml
git commit -m "chore: scaffold pnpm + turborepo monorepo"
```

---

## Task 2: `core-types` Package

**Files:**
- Create: `packages/core-types/package.json`
- Create: `packages/core-types/tsconfig.json`
- Create: `packages/core-types/src/index.ts`

This package contains only interface/type declarations with no runtime code, so there is nothing to unit test. Correctness is verified by a clean `tsc` build. All later packages import from here.

- [ ] **Step 1: Create `packages/core-types/package.json`**

```json
{
  "name": "@opentalos/core-types",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  }
}
```

- [ ] **Step 2: Create `packages/core-types/tsconfig.json`**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src"],
  "exclude": ["src/**/*.test.ts"]
}
```

- [ ] **Step 3: Create `packages/core-types/src/index.ts`**

```ts
// Threaded through every operation for multi-tenant isolation and log/trace correlation.
export interface TenantContext {
  tenantId: string;
  sessionId: string;
}

export type MessageRole = "system" | "user" | "assistant" | "tool";

export interface Message {
  role: MessageRole;
  content: string;
}

export type JSONSchema = Record<string, unknown>;

export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: JSONSchema;
}

export interface ToolCall {
  id: string;
  name: string;
  input: unknown;
}

export interface ToolResult {
  id: string;
  output: unknown;
  isError?: boolean;
}

export interface Tool {
  definition: ToolDefinition;
  execute(input: unknown, ctx: TenantContext): Promise<ToolResult>;
}

export interface ToolRegistry {
  register(tool: Tool): void;
  get(name: string): Tool | undefined;
  list(): ToolDefinition[];
  execute(call: ToolCall, ctx: TenantContext): Promise<ToolResult>;
}

export interface ModelRequest {
  messages: Message[];
  tools?: ToolDefinition[];
  responseSchema?: JSONSchema;
}

export type ModelResponseChunk =
  | { type: "text_delta"; textDelta: string }
  | { type: "tool_call"; toolCall: ToolCall }
  | { type: "message_stop" };

export interface ModelProvider {
  complete(request: ModelRequest): AsyncIterable<ModelResponseChunk>;
}

export interface MemoryRecord {
  key: string;
  value: unknown;
  score?: number;
}

export interface MemoryStore {
  read(key: string, ctx: TenantContext): Promise<unknown | undefined>;
  write(key: string, value: unknown, ctx: TenantContext): Promise<void>;
  search(query: string, ctx: TenantContext): Promise<MemoryRecord[]>;
}

// `nodeCursor` and `pendingYields` are deliberately `unknown`: CheckpointStore must stay
// usable by any future execution engine, not just the generator-based graph engine built
// in this plan. The graph engine casts these fields to its own cursor type internally.
export interface Checkpoint<TState = unknown> {
  graphId: string;
  runId: string;
  tenantId: string;
  sessionId: string;
  nodeCursor: unknown;
  state: TState;
  pendingYields: unknown[];
  status: "running" | "paused" | "done";
  createdAt: string;
}

export interface CheckpointQuery {
  tenantId?: string;
  sessionId?: string;
}

export interface CheckpointStore {
  save(checkpoint: Checkpoint): Promise<void>;
  load(runId: string): Promise<Checkpoint | undefined>;
  list(query: CheckpointQuery): Promise<Checkpoint[]>;
}

export type TraceEventType =
  | "node_enter"
  | "node_exit"
  | "llm_call_start"
  | "llm_call_end"
  | "tool_call_start"
  | "tool_call_end"
  | "hitl_interrupt"
  | "error";

export interface TraceEvent {
  type: TraceEventType;
  runId: string;
  tenantId: string;
  sessionId: string;
  timestamp: string;
  payload?: Record<string, unknown>;
}

export type EventHandler = (event: TraceEvent) => void;

export interface EventBus {
  emit(event: TraceEvent): void;
  subscribe(handler: EventHandler): () => void;
}

export type GuardrailDecision = "allow" | "block" | "require_approval";

export interface GuardrailInput {
  nodeId: string;
  phase: "before" | "after";
  state: unknown;
  ctx: TenantContext;
}

export interface Guardrail {
  check(input: GuardrailInput): Promise<GuardrailDecision>;
}
```

- [ ] **Step 4: Build and verify**

Run: `pnpm install && pnpm --filter @opentalos/core-types build`
Expected: PASS — `packages/core-types/dist/index.js` and `dist/index.d.ts` are created, no TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add packages/core-types pnpm-lock.yaml
git commit -m "feat(core-types): add shared engine interfaces"
```

---

## Task 3: `checkpoint` Package

**Files:**
- Create: `packages/checkpoint/package.json`
- Create: `packages/checkpoint/tsconfig.json`
- Create: `packages/checkpoint/src/index.ts`
- Test: `packages/checkpoint/src/index.test.ts`

- [ ] **Step 1: Create `packages/checkpoint/package.json`**

```json
{
  "name": "@opentalos/checkpoint",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@opentalos/core-types": "workspace:*"
  }
}
```

- [ ] **Step 2: Create `packages/checkpoint/tsconfig.json`**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src"],
  "exclude": ["src/**/*.test.ts"]
}
```

- [ ] **Step 3: Write the failing tests — `packages/checkpoint/src/index.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { Checkpoint } from "@opentalos/core-types";
import { InMemoryCheckpointStore } from "./index.js";

function makeCheckpoint(overrides: Partial<Checkpoint> = {}): Checkpoint {
  return {
    graphId: "g1",
    runId: "run-1",
    tenantId: "tenant-a",
    sessionId: "session-1",
    nodeCursor: "start",
    state: {},
    pendingYields: [],
    status: "running",
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

describe("InMemoryCheckpointStore", () => {
  it("saves and loads a checkpoint by runId", async () => {
    const store = new InMemoryCheckpointStore();
    const checkpoint = makeCheckpoint();
    await store.save(checkpoint);
    await expect(store.load("run-1")).resolves.toEqual(checkpoint);
  });

  it("returns undefined for an unknown runId", async () => {
    const store = new InMemoryCheckpointStore();
    await expect(store.load("missing")).resolves.toBeUndefined();
  });

  it("overwrites a checkpoint saved again with the same runId", async () => {
    const store = new InMemoryCheckpointStore();
    await store.save(makeCheckpoint({ status: "running" }));
    await store.save(makeCheckpoint({ status: "done" }));
    const loaded = await store.load("run-1");
    expect(loaded?.status).toBe("done");
  });

  it("lists checkpoints filtered by tenantId and sessionId", async () => {
    const store = new InMemoryCheckpointStore();
    await store.save(makeCheckpoint({ runId: "run-1", tenantId: "tenant-a", sessionId: "s1" }));
    await store.save(makeCheckpoint({ runId: "run-2", tenantId: "tenant-b", sessionId: "s1" }));
    await store.save(makeCheckpoint({ runId: "run-3", tenantId: "tenant-a", sessionId: "s2" }));

    const tenantAOnly = await store.list({ tenantId: "tenant-a" });
    expect(tenantAOnly.map((c) => c.runId).sort()).toEqual(["run-1", "run-3"]);

    const tenantAAndSession1 = await store.list({ tenantId: "tenant-a", sessionId: "s1" });
    expect(tenantAAndSession1.map((c) => c.runId)).toEqual(["run-1"]);
  });
});
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pnpm install && pnpm --filter @opentalos/checkpoint test`
Expected: FAIL — `src/index.ts` does not exist yet / `InMemoryCheckpointStore` is not exported.

- [ ] **Step 5: Implement `packages/checkpoint/src/index.ts`**

```ts
import type { Checkpoint, CheckpointQuery, CheckpointStore } from "@opentalos/core-types";

export class InMemoryCheckpointStore implements CheckpointStore {
  private readonly checkpoints = new Map<string, Checkpoint>();

  async save(checkpoint: Checkpoint): Promise<void> {
    this.checkpoints.set(checkpoint.runId, checkpoint);
  }

  async load(runId: string): Promise<Checkpoint | undefined> {
    return this.checkpoints.get(runId);
  }

  async list(query: CheckpointQuery): Promise<Checkpoint[]> {
    return [...this.checkpoints.values()].filter((checkpoint) => {
      if (query.tenantId && checkpoint.tenantId !== query.tenantId) return false;
      if (query.sessionId && checkpoint.sessionId !== query.sessionId) return false;
      return true;
    });
  }
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pnpm --filter @opentalos/checkpoint test`
Expected: PASS — all 4 tests green.

- [ ] **Step 7: Commit**

```bash
git add packages/checkpoint pnpm-lock.yaml
git commit -m "feat(checkpoint): add in-memory CheckpointStore"
```

---

## Task 4: `tracing` Package

**Files:**
- Create: `packages/tracing/package.json`
- Create: `packages/tracing/tsconfig.json`
- Create: `packages/tracing/src/index.ts`
- Test: `packages/tracing/src/index.test.ts`

- [ ] **Step 1: Create `packages/tracing/package.json`**

```json
{
  "name": "@opentalos/tracing",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@opentalos/core-types": "workspace:*"
  }
}
```

- [ ] **Step 2: Create `packages/tracing/tsconfig.json`**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src"],
  "exclude": ["src/**/*.test.ts"]
}
```

- [ ] **Step 3: Write the failing tests — `packages/tracing/src/index.test.ts`**

```ts
import { describe, expect, it, vi } from "vitest";
import type { TraceEvent } from "@opentalos/core-types";
import { InMemoryEventBus } from "./index.js";

function makeEvent(overrides: Partial<TraceEvent> = {}): TraceEvent {
  return {
    type: "node_enter",
    runId: "run-1",
    tenantId: "tenant-a",
    sessionId: "session-1",
    timestamp: new Date().toISOString(),
    ...overrides,
  };
}

describe("InMemoryEventBus", () => {
  it("delivers emitted events to subscribed handlers", () => {
    const bus = new InMemoryEventBus();
    const handler = vi.fn();
    bus.subscribe(handler);
    const event = makeEvent();
    bus.emit(event);
    expect(handler).toHaveBeenCalledWith(event);
  });

  it("supports multiple subscribers", () => {
    const bus = new InMemoryEventBus();
    const first = vi.fn();
    const second = vi.fn();
    bus.subscribe(first);
    bus.subscribe(second);
    bus.emit(makeEvent());
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("stops delivering events after unsubscribe", () => {
    const bus = new InMemoryEventBus();
    const handler = vi.fn();
    const unsubscribe = bus.subscribe(handler);
    unsubscribe();
    bus.emit(makeEvent());
    expect(handler).not.toHaveBeenCalled();
  });

  it("records emitted events in order via getEvents()", () => {
    const bus = new InMemoryEventBus();
    bus.emit(makeEvent({ type: "node_enter" }));
    bus.emit(makeEvent({ type: "node_exit" }));
    expect(bus.getEvents().map((e) => e.type)).toEqual(["node_enter", "node_exit"]);
  });
});
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pnpm --filter @opentalos/tracing test`
Expected: FAIL — `InMemoryEventBus` is not defined.

- [ ] **Step 5: Implement `packages/tracing/src/index.ts`**

```ts
import type { EventBus, EventHandler, TraceEvent } from "@opentalos/core-types";

export class InMemoryEventBus implements EventBus {
  private readonly handlers = new Set<EventHandler>();
  private readonly log: TraceEvent[] = [];

  emit(event: TraceEvent): void {
    this.log.push(event);
    for (const handler of this.handlers) {
      handler(event);
    }
  }

  subscribe(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  getEvents(): TraceEvent[] {
    return [...this.log];
  }
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pnpm --filter @opentalos/tracing test`
Expected: PASS — all 4 tests green.

- [ ] **Step 7: Commit**

```bash
git add packages/tracing pnpm-lock.yaml
git commit -m "feat(tracing): add in-memory EventBus"
```

---

## Task 5: `memory` Package

**Files:**
- Create: `packages/memory/package.json`
- Create: `packages/memory/tsconfig.json`
- Create: `packages/memory/src/index.ts`
- Test: `packages/memory/src/index.test.ts`

- [ ] **Step 1: Create `packages/memory/package.json`**

```json
{
  "name": "@opentalos/memory",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@opentalos/core-types": "workspace:*"
  }
}
```

- [ ] **Step 2: Create `packages/memory/tsconfig.json`**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src"],
  "exclude": ["src/**/*.test.ts"]
}
```

- [ ] **Step 3: Write the failing tests — `packages/memory/src/index.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { TenantContext } from "@opentalos/core-types";
import { InMemoryMemoryStore } from "./index.js";

const tenantA: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };
const tenantB: TenantContext = { tenantId: "tenant-b", sessionId: "session-1" };

describe("InMemoryMemoryStore", () => {
  it("writes and reads a value scoped to a tenant", async () => {
    const store = new InMemoryMemoryStore();
    await store.write("greeting", "hello", tenantA);
    await expect(store.read("greeting", tenantA)).resolves.toBe("hello");
  });

  it("returns undefined for a key never written", async () => {
    const store = new InMemoryMemoryStore();
    await expect(store.read("missing", tenantA)).resolves.toBeUndefined();
  });

  it("isolates values between tenants sharing the same key and sessionId", async () => {
    const store = new InMemoryMemoryStore();
    await store.write("greeting", "hello from A", tenantA);
    await store.write("greeting", "hello from B", tenantB);
    await expect(store.read("greeting", tenantA)).resolves.toBe("hello from A");
    await expect(store.read("greeting", tenantB)).resolves.toBe("hello from B");
  });

  it("finds records whose value contains the search query, scoped to tenant", async () => {
    const store = new InMemoryMemoryStore();
    await store.write("fact-1", "Paris is the capital of France", tenantA);
    await store.write("fact-2", "Tokyo is the capital of Japan", tenantA);
    await store.write("fact-1", "Berlin is the capital of Germany", tenantB);

    const results = await store.search("capital of france", tenantA);
    expect(results).toEqual([{ key: "fact-1", value: "Paris is the capital of France" }]);
  });
});
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pnpm --filter @opentalos/memory test`
Expected: FAIL — `InMemoryMemoryStore` is not defined.

- [ ] **Step 5: Implement `packages/memory/src/index.ts`**

```ts
import type { MemoryRecord, MemoryStore, TenantContext } from "@opentalos/core-types";

export class InMemoryMemoryStore implements MemoryStore {
  private readonly data = new Map<string, unknown>();

  private scopedKey(key: string, ctx: TenantContext): string {
    return `${ctx.tenantId}:${ctx.sessionId}:${key}`;
  }

  async read(key: string, ctx: TenantContext): Promise<unknown | undefined> {
    return this.data.get(this.scopedKey(key, ctx));
  }

  async write(key: string, value: unknown, ctx: TenantContext): Promise<void> {
    this.data.set(this.scopedKey(key, ctx), value);
  }

  async search(query: string, ctx: TenantContext): Promise<MemoryRecord[]> {
    const prefix = `${ctx.tenantId}:${ctx.sessionId}:`;
    const lowerQuery = query.toLowerCase();
    const results: MemoryRecord[] = [];
    for (const [scopedKey, value] of this.data.entries()) {
      if (!scopedKey.startsWith(prefix)) continue;
      const haystack = JSON.stringify(value).toLowerCase();
      if (haystack.includes(lowerQuery)) {
        results.push({ key: scopedKey.slice(prefix.length), value });
      }
    }
    return results;
  }
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pnpm --filter @opentalos/memory test`
Expected: PASS — all 4 tests green.

- [ ] **Step 7: Commit**

```bash
git add packages/memory pnpm-lock.yaml
git commit -m "feat(memory): add tenant-scoped in-memory MemoryStore"
```

---

## Task 6: `tool-registry` Package (in-memory registry + MCP adapter)

**Files:**
- Create: `packages/tool-registry/package.json`
- Create: `packages/tool-registry/tsconfig.json`
- Create: `packages/tool-registry/src/in-memory-registry.ts`
- Create: `packages/tool-registry/src/mcp-adapter.ts`
- Create: `packages/tool-registry/src/index.ts`
- Test: `packages/tool-registry/src/in-memory-registry.test.ts`
- Test: `packages/tool-registry/src/mcp-adapter.test.ts`

- [ ] **Step 1: Create `packages/tool-registry/package.json`**

```json
{
  "name": "@opentalos/tool-registry",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@opentalos/core-types": "workspace:*",
    "@modelcontextprotocol/sdk": "^1.30.0"
  },
  "devDependencies": {
    "zod": "^4.5.4"
  }
}
```

- [ ] **Step 2: Create `packages/tool-registry/tsconfig.json`**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src"],
  "exclude": ["src/**/*.test.ts"]
}
```

### Part A — in-memory registry

- [ ] **Step 3: Write the failing tests — `packages/tool-registry/src/in-memory-registry.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { TenantContext, Tool } from "@opentalos/core-types";
import { InMemoryToolRegistry } from "./in-memory-registry.js";

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

const echoTool: Tool = {
  definition: { name: "echo", description: "Echoes the input text", inputSchema: { type: "object" } },
  async execute(input) {
    return { id: "call-1", output: input };
  },
};

const throwingTool: Tool = {
  definition: { name: "boom", description: "Always throws", inputSchema: { type: "object" } },
  async execute() {
    throw new Error("kaboom");
  },
};

describe("InMemoryToolRegistry", () => {
  it("registers and lists tool definitions", () => {
    const registry = new InMemoryToolRegistry();
    registry.register(echoTool);
    expect(registry.list()).toEqual([echoTool.definition]);
    expect(registry.get("echo")).toBe(echoTool);
  });

  it("executes a registered tool and returns its result", async () => {
    const registry = new InMemoryToolRegistry();
    registry.register(echoTool);
    const result = await registry.execute({ id: "call-1", name: "echo", input: { text: "hi" } }, tenant);
    expect(result).toEqual({ id: "call-1", output: { text: "hi" } });
  });

  it("returns an error result for an unknown tool name", async () => {
    const registry = new InMemoryToolRegistry();
    const result = await registry.execute({ id: "call-1", name: "missing", input: {} }, tenant);
    expect(result.isError).toBe(true);
  });

  it("catches a thrown error inside a tool and returns it as an error result", async () => {
    const registry = new InMemoryToolRegistry();
    registry.register(throwingTool);
    const result = await registry.execute({ id: "call-1", name: "boom", input: {} }, tenant);
    expect(result.isError).toBe(true);
    expect(result.output).toContain("kaboom");
  });
});
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pnpm install && pnpm --filter @opentalos/tool-registry test`
Expected: FAIL — `InMemoryToolRegistry` is not defined.

- [ ] **Step 5: Implement `packages/tool-registry/src/in-memory-registry.ts`**

```ts
import type { TenantContext, Tool, ToolCall, ToolDefinition, ToolRegistry, ToolResult } from "@opentalos/core-types";

export class InMemoryToolRegistry implements ToolRegistry {
  private readonly tools = new Map<string, Tool>();

  register(tool: Tool): void {
    this.tools.set(tool.definition.name, tool);
  }

  get(name: string): Tool | undefined {
    return this.tools.get(name);
  }

  list(): ToolDefinition[] {
    return [...this.tools.values()].map((tool) => tool.definition);
  }

  async execute(call: ToolCall, ctx: TenantContext): Promise<ToolResult> {
    const tool = this.tools.get(call.name);
    if (!tool) {
      return { id: call.id, output: `Unknown tool: ${call.name}`, isError: true };
    }
    try {
      // Always return the caller's call.id, not whatever id the Tool implementation
      // invented — result/call id correlation matters for threading tool results
      // back into an LLM conversation correctly.
      return { ...(await tool.execute(call.input, ctx)), id: call.id };
    } catch (error) {
      return { id: call.id, output: error instanceof Error ? error.message : String(error), isError: true };
    }
  }
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pnpm --filter @opentalos/tool-registry test -- in-memory-registry`
Expected: PASS — all 4 tests green.

### Part B — MCP adapter

- [ ] **Step 7: Write the failing test — `packages/tool-registry/src/mcp-adapter.test.ts`**

This spins up a real `McpServer` and `Client` connected via `InMemoryTransport`, so the test exercises the real MCP protocol without any external process.

```ts
import { describe, expect, it } from "vitest";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { z } from "zod";
import type { TenantContext } from "@opentalos/core-types";
import { createMcpTools } from "./mcp-adapter.js";

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

async function startLinkedServerAndClient(): Promise<Client> {
  const server = new McpServer({ name: "test-server", version: "1.0.0" });
  server.registerTool(
    "echo",
    { description: "Echoes the input text back", inputSchema: { text: z.string() } },
    async ({ text }) => ({ content: [{ type: "text", text }] }),
  );

  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "test-client", version: "1.0.0" });
  await Promise.all([client.connect(clientTransport), server.connect(serverTransport)]);
  return client;
}

describe("createMcpTools", () => {
  it("adapts a real MCP server's tools into OpenTalos Tool objects", async () => {
    const client = await startLinkedServerAndClient();
    const tools = await createMcpTools(client);

    expect(tools).toHaveLength(1);
    expect(tools[0].definition.name).toBe("echo");

    const result = await tools[0].execute({ text: "hello mcp" }, tenant);
    expect(result.isError).toBeFalsy();
    expect(result.output).toBe("hello mcp");
  });
});
```

- [ ] **Step 8: Run test to verify it fails**

Run: `pnpm --filter @opentalos/tool-registry test -- mcp-adapter`
Expected: FAIL — `createMcpTools` is not defined.

- [ ] **Step 9: Implement `packages/tool-registry/src/mcp-adapter.ts`**

```ts
import type { Client } from "@modelcontextprotocol/sdk/client/index.js";
import type { JSONSchema, Tool, ToolResult } from "@opentalos/core-types";

interface McpTextContent {
  type: "text";
  text: string;
}

function extractText(content: unknown): string {
  if (!Array.isArray(content)) return "";
  return content
    .filter((block): block is McpTextContent => (block as McpTextContent).type === "text")
    .map((block) => block.text)
    .join("");
}

export async function createMcpTools(client: Client): Promise<Tool[]> {
  const { tools } = await client.listTools();
  return tools.map((mcpTool) => ({
    definition: {
      name: mcpTool.name,
      description: mcpTool.description ?? "",
      inputSchema: (mcpTool.inputSchema ?? {}) as JSONSchema,
    },
    async execute(input: unknown): Promise<ToolResult> {
      const result = await client.callTool({
        name: mcpTool.name,
        arguments: input as Record<string, unknown>,
      });
      return {
        id: `${mcpTool.name}-${Date.now()}`,
        output: extractText(result.content),
        isError: Boolean(result.isError),
      };
    },
  }));
}
```

- [ ] **Step 10: Run test to verify it passes**

Run: `pnpm --filter @opentalos/tool-registry test`
Expected: PASS — all 5 tests (4 in-memory + 1 MCP) green.

- [ ] **Step 11: Create `packages/tool-registry/src/index.ts`**

```ts
export { InMemoryToolRegistry } from "./in-memory-registry.js";
export { createMcpTools } from "./mcp-adapter.js";
```

- [ ] **Step 12: Rebuild and re-run tests**

Run: `pnpm --filter @opentalos/tool-registry build && pnpm --filter @opentalos/tool-registry test`
Expected: PASS.

- [ ] **Step 13: Commit**

```bash
git add packages/tool-registry pnpm-lock.yaml
git commit -m "feat(tool-registry): add in-memory registry and MCP client adapter"
```

---

## Task 7: `model-providers` Package

**Files:**
- Create: `packages/model-providers/package.json`
- Create: `packages/model-providers/tsconfig.json`
- Create: `packages/model-providers/src/anthropic.ts`
- Create: `packages/model-providers/src/openai-compatible.ts`
- Create: `packages/model-providers/src/ollama.ts`
- Create: `packages/model-providers/src/index.ts`
- Test: `packages/model-providers/src/anthropic.test.ts`
- Test: `packages/model-providers/src/openai-compatible.test.ts`
- Test: `packages/model-providers/src/ollama.test.ts`

Each adapter takes a minimal, structurally-typed client interface (`AnthropicClientLike`, `OpenAIClientLike`, `OllamaFetchLike`) instead of importing the real vendor SDKs. This keeps `model-providers` free of vendor SDK version churn while staying real: an actual `Anthropic`/`OpenAI` client instance from the official SDKs satisfies these interfaces structurally, since TypeScript structural typing only requires the fields actually used to be present. Tests inject fakes so no network access or API key is required.

- [ ] **Step 1: Create `packages/model-providers/package.json`**

```json
{
  "name": "@opentalos/model-providers",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@opentalos/core-types": "workspace:*"
  }
}
```

- [ ] **Step 2: Create `packages/model-providers/tsconfig.json`** — includes a local `"lib": ["ES2022", "DOM"]` override: the Ollama adapter uses the Web Streams API (`ReadableStream`, `TextDecoder`), which are real Node 20+ globals at runtime but require the DOM lib for TypeScript to see their type declarations, since the shared `tsconfig.base.json` only sets `"lib": ["ES2022"]`.

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src",
    "lib": ["ES2022", "DOM"]
  },
  "include": ["src"],
  "exclude": ["src/**/*.test.ts"]
}
```

### Part A — Anthropic adapter

- [ ] **Step 3: Write the failing test — `packages/model-providers/src/anthropic.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { ModelRequest } from "@opentalos/core-types";
import { createAnthropicProvider, type AnthropicClientLike } from "./anthropic.js";

function fakeClient(events: unknown[]): AnthropicClientLike {
  return {
    messages: {
      stream() {
        return (async function* () {
          for (const event of events) yield event as never;
        })();
      },
    },
  };
}

const request: ModelRequest = { messages: [{ role: "user", content: "hi" }] };

describe("createAnthropicProvider", () => {
  it("yields text_delta chunks from content_block_delta events", async () => {
    const client = fakeClient([
      { type: "content_block_delta", delta: { type: "text_delta", text: "Hello" } },
      { type: "content_block_delta", delta: { type: "text_delta", text: " world" } },
      { type: "message_stop" },
    ]);
    const provider = createAnthropicProvider(client, { model: "claude-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks).toEqual([
      { type: "text_delta", textDelta: "Hello" },
      { type: "text_delta", textDelta: " world" },
      { type: "message_stop" },
    ]);
  });

  it("yields a tool_call chunk from a content_block_start tool_use event", async () => {
    const client = fakeClient([
      { type: "content_block_start", content_block: { type: "tool_use", id: "call-1", name: "search", input: { q: "x" } } },
      { type: "message_stop" },
    ]);
    const provider = createAnthropicProvider(client, { model: "claude-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks[0]).toEqual({ type: "tool_call", toolCall: { id: "call-1", name: "search", input: { q: "x" } } });
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pnpm install && pnpm --filter @opentalos/model-providers test -- anthropic`
Expected: FAIL — `createAnthropicProvider` is not defined.

- [ ] **Step 5: Implement `packages/model-providers/src/anthropic.ts`**

```ts
import type { JSONSchema, ModelProvider, ModelRequest, ModelResponseChunk } from "@opentalos/core-types";

export type AnthropicStreamEvent =
  | { type: "content_block_delta"; delta: { type: "text_delta"; text: string } }
  | { type: "content_block_delta"; delta: { type: string } }
  | { type: "content_block_start"; content_block: { type: "tool_use"; id: string; name: string; input: unknown } }
  | { type: "content_block_start"; content_block: { type: string } }
  | { type: "message_stop" }
  | { type: string };

export interface AnthropicClientLike {
  messages: {
    stream(params: {
      model: string;
      max_tokens: number;
      system?: string;
      messages: { role: "user" | "assistant"; content: string }[];
      tools?: { name: string; description: string; input_schema: JSONSchema }[];
    }): AsyncIterable<AnthropicStreamEvent>;
  };
}

export interface AnthropicProviderOptions {
  model: string;
  maxTokens?: number;
}

export function createAnthropicProvider(client: AnthropicClientLike, options: AnthropicProviderOptions): ModelProvider {
  return {
    async *complete(request: ModelRequest): AsyncIterable<ModelResponseChunk> {
      const system = request.messages.find((m) => m.role === "system");
      const conversation = request.messages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));

      const stream = client.messages.stream({
        model: options.model,
        max_tokens: options.maxTokens ?? 1024,
        system: system?.content,
        messages: conversation,
        tools: request.tools?.map((t) => ({ name: t.name, description: t.description, input_schema: t.inputSchema })),
      });

      for await (const event of stream) {
        if (event.type === "content_block_delta" && "delta" in event && event.delta.type === "text_delta") {
          yield { type: "text_delta", textDelta: (event.delta as { text: string }).text };
        } else if (event.type === "content_block_start" && "content_block" in event && event.content_block.type === "tool_use") {
          const block = event.content_block as { id: string; name: string; input: unknown };
          yield { type: "tool_call", toolCall: { id: block.id, name: block.name, input: block.input } };
        } else if (event.type === "message_stop") {
          yield { type: "message_stop" };
        }
      }
    },
  };
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pnpm --filter @opentalos/model-providers test -- anthropic`
Expected: PASS — both tests green.

### Part B — OpenAI-compatible adapter

- [ ] **Step 7: Write the failing test — `packages/model-providers/src/openai-compatible.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { ModelRequest } from "@opentalos/core-types";
import { createOpenAICompatibleProvider, type OpenAIClientLike } from "./openai-compatible.js";

function fakeClient(chunks: unknown[]): OpenAIClientLike {
  return {
    chat: {
      completions: {
        create() {
          return (async function* () {
            for (const chunk of chunks) yield chunk as never;
          })();
        },
      },
    },
  };
}

const request: ModelRequest = { messages: [{ role: "user", content: "hi" }] };

describe("createOpenAICompatibleProvider", () => {
  it("yields text_delta chunks from delta.content", async () => {
    const client = fakeClient([
      { choices: [{ delta: { content: "Hello" } }] },
      { choices: [{ delta: { content: " world" }, finish_reason: "stop" }] },
    ]);
    const provider = createOpenAICompatibleProvider(client, { model: "gpt-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks).toEqual([
      { type: "text_delta", textDelta: "Hello" },
      { type: "text_delta", textDelta: " world" },
      { type: "message_stop" },
    ]);
  });

  it("yields tool_call chunks from delta.tool_calls", async () => {
    const client = fakeClient([
      { choices: [{ delta: { tool_calls: [{ id: "call-1", function: { name: "search", arguments: '{"q":"x"}' } }] } }] },
    ]);
    const provider = createOpenAICompatibleProvider(client, { model: "gpt-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks).toEqual([{ type: "tool_call", toolCall: { id: "call-1", name: "search", input: { q: "x" } } }]);
  });
});
```

- [ ] **Step 8: Run test to verify it fails**

Run: `pnpm --filter @opentalos/model-providers test -- openai-compatible`
Expected: FAIL — `createOpenAICompatibleProvider` is not defined.

- [ ] **Step 9: Implement `packages/model-providers/src/openai-compatible.ts`**

```ts
import type { JSONSchema, ModelProvider, ModelRequest, ModelResponseChunk } from "@opentalos/core-types";

export interface OpenAIStreamChunk {
  choices: {
    delta: {
      content?: string;
      tool_calls?: { id: string; function: { name: string; arguments: string } }[];
    };
    finish_reason?: string | null;
  }[];
}

export interface OpenAIClientLike {
  chat: {
    completions: {
      create(params: {
        model: string;
        messages: { role: string; content: string }[];
        tools?: { type: "function"; function: { name: string; description: string; parameters: JSONSchema } }[];
        stream: true;
      }): AsyncIterable<OpenAIStreamChunk>;
    };
  };
}

export interface OpenAICompatibleProviderOptions {
  model: string;
}

export function createOpenAICompatibleProvider(
  client: OpenAIClientLike,
  options: OpenAICompatibleProviderOptions,
): ModelProvider {
  return {
    async *complete(request: ModelRequest): AsyncIterable<ModelResponseChunk> {
      const stream = client.chat.completions.create({
        model: options.model,
        messages: request.messages.map((m) => ({ role: m.role, content: m.content })),
        tools: request.tools?.map((t) => ({
          type: "function",
          function: { name: t.name, description: t.description, parameters: t.inputSchema },
        })),
        stream: true,
      });

      for await (const chunk of stream) {
        const choice = chunk.choices[0];
        if (choice?.delta.content) {
          yield { type: "text_delta", textDelta: choice.delta.content };
        }
        for (const call of choice?.delta.tool_calls ?? []) {
          yield {
            type: "tool_call",
            toolCall: { id: call.id, name: call.function.name, input: JSON.parse(call.function.arguments || "{}") },
          };
        }
        if (choice?.finish_reason) {
          yield { type: "message_stop" };
        }
      }
    },
  };
}
```

- [ ] **Step 10: Run test to verify it passes**

Run: `pnpm --filter @opentalos/model-providers test -- openai-compatible`
Expected: PASS — both tests green.

### Part C — Ollama adapter

- [ ] **Step 11: Write the failing test — `packages/model-providers/src/ollama.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { ModelRequest } from "@opentalos/core-types";
import { createOllamaProvider, type OllamaFetchLike } from "./ollama.js";

function streamFromLines(lines: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const line of lines) controller.enqueue(encoder.encode(line + "\n"));
      controller.close();
    },
  });
}

const request: ModelRequest = { messages: [{ role: "user", content: "hi" }] };

describe("createOllamaProvider", () => {
  it("parses newline-delimited JSON chunks into text_delta and message_stop", async () => {
    const fetchFn: OllamaFetchLike = async () => ({
      ok: true,
      status: 200,
      body: streamFromLines([
        JSON.stringify({ message: { content: "Hello" } }),
        JSON.stringify({ message: { content: " world" } }),
        JSON.stringify({ done: true }),
      ]),
    });
    const provider = createOllamaProvider(fetchFn, { baseUrl: "http://localhost:11434", model: "llama-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks).toEqual([
      { type: "text_delta", textDelta: "Hello" },
      { type: "text_delta", textDelta: " world" },
      { type: "message_stop" },
    ]);
  });

  it("throws when the response is not ok", async () => {
    const fetchFn: OllamaFetchLike = async () => ({ ok: false, status: 500, body: null });
    const provider = createOllamaProvider(fetchFn, { baseUrl: "http://localhost:11434", model: "llama-test" });
    await expect(async () => {
      for await (const _chunk of provider.complete(request)) {
        // draining the iterator to trigger the throw
      }
    }).rejects.toThrow(/status 500/);
  });
});
```

- [ ] **Step 12: Run test to verify it fails**

Run: `pnpm --filter @opentalos/model-providers test -- ollama`
Expected: FAIL — `createOllamaProvider` is not defined.

- [ ] **Step 13: Implement `packages/model-providers/src/ollama.ts`**

```ts
import type { ModelProvider, ModelRequest, ModelResponseChunk } from "@opentalos/core-types";

export interface OllamaFetchResponse {
  ok: boolean;
  status: number;
  body: ReadableStream<Uint8Array> | null;
}

export type OllamaFetchLike = (
  url: string,
  init: { method: string; body: string; headers: Record<string, string> },
) => Promise<OllamaFetchResponse>;

export interface OllamaProviderOptions {
  baseUrl: string;
  model: string;
}

interface OllamaChatLine {
  message?: { content?: string };
  done?: boolean;
}

export function createOllamaProvider(fetchFn: OllamaFetchLike, options: OllamaProviderOptions): ModelProvider {
  return {
    async *complete(request: ModelRequest): AsyncIterable<ModelResponseChunk> {
      const response = await fetchFn(`${options.baseUrl}/api/chat`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          model: options.model,
          messages: request.messages.map((m) => ({ role: m.role, content: m.content })),
          stream: true,
        }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`Ollama request failed with status ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const parsed = JSON.parse(line) as OllamaChatLine;
          if (parsed.message?.content) {
            yield { type: "text_delta", textDelta: parsed.message.content };
          }
          if (parsed.done) {
            yield { type: "message_stop" };
          }
        }
      }
      // Flush a final unterminated line (no trailing "\n") so the last chunk isn't silently dropped.
      if (buffer.trim()) {
        const parsed = JSON.parse(buffer) as OllamaChatLine;
        if (parsed.message?.content) {
          yield { type: "text_delta", textDelta: parsed.message.content };
        }
        if (parsed.done) {
          yield { type: "message_stop" };
        }
      }
    },
  };
}
```

- [ ] **Step 14: Run test to verify it passes**

Run: `pnpm --filter @opentalos/model-providers test -- ollama`
Expected: PASS — both tests green.

- [ ] **Step 15: Create `packages/model-providers/src/index.ts`**

```ts
export { createAnthropicProvider, type AnthropicClientLike, type AnthropicProviderOptions } from "./anthropic.js";
export {
  createOpenAICompatibleProvider,
  type OpenAIClientLike,
  type OpenAICompatibleProviderOptions,
} from "./openai-compatible.js";
export { createOllamaProvider, type OllamaFetchLike, type OllamaProviderOptions } from "./ollama.js";
```

- [ ] **Step 16: Rebuild and re-run all tests in the package**

Run: `pnpm --filter @opentalos/model-providers build && pnpm --filter @opentalos/model-providers test`
Expected: PASS — all 6 tests green.

- [ ] **Step 17: Commit**

```bash
git add packages/model-providers pnpm-lock.yaml
git commit -m "feat(model-providers): add Anthropic, OpenAI-compatible, and Ollama adapters"
```

---

## Task 8: `core-graph` Package — Sequential Engine

This is the heart of the system. It implements the `GraphEngine` class: sequential node execution, conditional branching, loops, automatic tool-call resolution, and HITL pause/resume with per-step checkpointing.

**Files:**
- Create: `packages/core-graph/package.json`
- Create: `packages/core-graph/tsconfig.json`
- Create: `packages/core-graph/src/types.ts`
- Create: `packages/core-graph/src/reducer.ts`
- Create: `packages/core-graph/src/engine.ts`
- Create: `packages/core-graph/src/index.ts`
- Test: `packages/core-graph/src/engine.test.ts`

- [ ] **Step 1: Create `packages/core-graph/package.json`**

```json
{
  "name": "@opentalos/core-graph",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@opentalos/core-types": "workspace:*"
  },
  "devDependencies": {
    "@opentalos/checkpoint": "workspace:*",
    "@opentalos/tracing": "workspace:*",
    "@opentalos/tool-registry": "workspace:*"
  }
}
```

`checkpoint`, `tracing`, and `tool-registry` are **devDependencies only** — they provide concrete implementations used by the test suite to construct a runnable engine. `core-graph`'s own source code (`src/*.ts`, excluding tests) never imports from them, only from `@opentalos/core-types`. This is what keeps the engine decoupled from any specific persistence/tracing/tool implementation.

- [ ] **Step 2: Create `packages/core-graph/tsconfig.json`**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src"],
  "exclude": ["src/**/*.test.ts"]
}
```

- [ ] **Step 3: Create `packages/core-graph/src/types.ts`**

```ts
import type { EventBus, TenantContext, ToolCall, ToolResult } from "@opentalos/core-types";

export interface NodeContext {
  tenant: TenantContext;
  eventBus: EventBus;
}

export type NodeYield = { type: "awaiting_tool"; toolCall: ToolCall } | { type: "awaiting_approval"; reason: string };

export type NodeResumeValue =
  | { type: "tool_result"; result: ToolResult }
  | { type: "approval"; approved: boolean }
  | undefined;

export type NodeGenerator<TState> = AsyncGenerator<NodeYield, Partial<TState>, NodeResumeValue>;

export type NodeFn<TState> = (state: TState, ctx: NodeContext) => NodeGenerator<TState>;

export interface EdgeDefinition<TState> {
  from: string;
  to: string | string[];
  condition?: (state: TState) => boolean;
  /** Optional when `to` is an array: the node the fan-out branches converge back into. If
   * omitted, the fan-out is treated as the terminal step of the graph (status becomes "done"
   * once all branches complete). */
  joinTo?: string;
}

export interface GraphDefinition<TState> {
  id: string;
  entryNode: string;
  nodes: Record<string, NodeFn<TState>>;
  edges: EdgeDefinition<TState>[];
  reducer: (state: TState, partial: Partial<TState>) => TState;
}

/**
 * Internal representation of "where execution currently is". A plain node id for
 * sequential execution, or a parallel-wave descriptor for an in-flight fan-out.
 * `Checkpoint.nodeCursor` (from @opentalos/core-types) is typed `unknown` precisely so
 * it can hold either shape without core-types knowing about this engine's internals.
 */
export type NodeCursor = string | { type: "parallel"; branches: string[]; joinTo?: string };
```

- [ ] **Step 4: Create `packages/core-graph/src/reducer.ts`**

```ts
export function shallowMergeReducer<TState extends object>(state: TState, partial: Partial<TState>): TState {
  return { ...state, ...partial };
}
```

- [ ] **Step 5: Write the failing tests — `packages/core-graph/src/engine.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { Guardrail, TenantContext } from "@opentalos/core-types";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryToolRegistry } from "@opentalos/tool-registry";
import { GraphEngine } from "./engine.js";
import { shallowMergeReducer } from "./reducer.js";
import type { GraphDefinition, NodeFn } from "./types.js";

interface CounterState {
  count: number;
  approved?: boolean;
}

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

function makeDeps() {
  const toolRegistry = new InMemoryToolRegistry();
  toolRegistry.register({
    definition: { name: "increment", description: "returns +1", inputSchema: {} },
    async execute() {
      return { id: "tool-1", output: 1 };
    },
  });
  const eventBus = new InMemoryEventBus();
  const checkpointStore = new InMemoryCheckpointStore();
  return { toolRegistry, eventBus, checkpointStore };
}

describe("GraphEngine — sequential execution", () => {
  it("runs a two-node sequential graph to completion", async () => {
    const increment: NodeFn<CounterState> = async function* (state) {
      return { count: state.count + 1 };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g1",
      entryNode: "a",
      nodes: { a: increment, b: increment },
      edges: [{ from: "a", to: "b" }],
      reducer: shallowMergeReducer,
    };
    const engine = new GraphEngine(graph, makeDeps());
    let checkpoint = engine.start({ count: 0 }, tenant, "run-1");
    checkpoint = await engine.run(checkpoint);
    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.count).toBe(2);
  });

  it("follows a conditional edge based on state", async () => {
    const setFlag: NodeFn<CounterState> = async function* () {
      return { count: 5 };
    };
    const high: NodeFn<CounterState> = async function* () {
      return { count: 100 };
    };
    const low: NodeFn<CounterState> = async function* () {
      return { count: -100 };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g2",
      entryNode: "start",
      nodes: { start, high, low },
      edges: [
        { from: "start", to: "high", condition: (s) => s.count >= 5 },
        { from: "start", to: "low", condition: (s) => s.count < 5 },
      ],
      reducer: shallowMergeReducer,
    };
    // eslint-disable-next-line no-var
    var start = setFlag;
    const engine = new GraphEngine(graph, makeDeps());
    let checkpoint = engine.start({ count: 0 }, tenant, "run-2");
    checkpoint = await engine.run(checkpoint);
    expect(checkpoint.state.count).toBe(100);
  });

  it("loops back to an earlier node until a condition is met", async () => {
    const tick: NodeFn<CounterState> = async function* (state) {
      return { count: state.count + 1 };
    };
    const done: NodeFn<CounterState> = async function* () {
      return {};
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g3",
      entryNode: "tick",
      nodes: { tick, done },
      edges: [
        { from: "tick", to: "tick", condition: (s) => s.count < 3 },
        { from: "tick", to: "done", condition: (s) => s.count >= 3 },
      ],
      reducer: shallowMergeReducer,
    };
    const engine = new GraphEngine(graph, makeDeps());
    let checkpoint = engine.start({ count: 0 }, tenant, "run-3");
    checkpoint = await engine.run(checkpoint);
    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.count).toBe(3);
  });

  it("auto-resolves an awaiting_tool yield via the injected ToolRegistry", async () => {
    const callTool: NodeFn<CounterState> = async function* (state) {
      const resume = yield { type: "awaiting_tool", toolCall: { id: "t1", name: "increment", input: {} } };
      const delta = resume?.type === "tool_result" ? (resume.result.output as number) : 0;
      return { count: state.count + delta };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g4",
      entryNode: "callTool",
      nodes: { callTool },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engine = new GraphEngine(graph, deps);
    let checkpoint = engine.start({ count: 0 }, tenant, "run-4");
    checkpoint = await engine.run(checkpoint);
    expect(checkpoint.state.count).toBe(1);
    expect(deps.eventBus.getEvents().map((e) => e.type)).toContain("tool_call_start");
    expect(deps.eventBus.getEvents().map((e) => e.type)).toContain("tool_call_end");
  });

  it("pauses on an awaiting_approval yield and persists a paused checkpoint", async () => {
    const askApproval: NodeFn<CounterState> = async function* (state) {
      const resume = yield { type: "awaiting_approval", reason: "please confirm" };
      return { count: state.count + 1, approved: resume?.type === "approval" ? resume.approved : false };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g5",
      entryNode: "ask",
      nodes: { ask: askApproval },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engine = new GraphEngine(graph, deps);
    let checkpoint = engine.start({ count: 0 }, tenant, "run-5");
    checkpoint = await engine.run(checkpoint);

    expect(checkpoint.status).toBe("paused");
    expect(checkpoint.pendingYields).toEqual([{ type: "awaiting_approval", reason: "please confirm" }]);
    const persisted = await deps.checkpointStore.load("run-5");
    expect(persisted?.status).toBe("paused");

    checkpoint = await engine.resume(checkpoint, { type: "approval", approved: true });
    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state).toEqual({ count: 1, approved: true });
  });

  it("throws a clear error when resuming a run with no in-memory paused generator", async () => {
    const askApproval: NodeFn<CounterState> = async function* () {
      yield { type: "awaiting_approval", reason: "please confirm" };
      return {};
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g6",
      entryNode: "ask",
      nodes: { ask: askApproval },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engineA = new GraphEngine(graph, deps);
    let checkpoint = engineA.start({ count: 0 }, tenant, "run-6");
    checkpoint = await engineA.run(checkpoint);

    const engineB = new GraphEngine(graph, deps); // fresh engine instance, no in-memory generator
    await expect(engineB.resume(checkpoint, { type: "approval", approved: true })).rejects.toThrow(
      /Cross-process resume is not supported/,
    );
  });

  it("wraps a thrown error as NodeError, emits an error trace event, and propagates it", async () => {
    const explode: NodeFn<CounterState> = async function* () {
      throw new Error("boom");
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g7",
      entryNode: "explode",
      nodes: { explode },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engine = new GraphEngine(graph, deps);
    const checkpoint = engine.start({ count: 0 }, tenant, "run-7");
    await expect(engine.run(checkpoint)).rejects.toThrow(/Node "explode" failed: boom/);
    const errorEvents = deps.eventBus.getEvents().filter((e) => e.type === "error");
    expect(errorEvents).toHaveLength(1);
    expect(errorEvents[0].payload?.nodeId).toBe("explode");
  });

  it("blocks a node before execution when a guardrail decision is 'block'", async () => {
    const increment: NodeFn<CounterState> = async function* (state) {
      return { count: state.count + 1 };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g8",
      entryNode: "increment",
      nodes: { increment },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const blockingGuardrail: Guardrail = {
      async check() {
        return "block";
      },
    };
    const deps = { ...makeDeps(), guardrails: [blockingGuardrail] };
    const engine = new GraphEngine(graph, deps);
    const checkpoint = engine.start({ count: 0 }, tenant, "run-8");
    await expect(engine.run(checkpoint)).rejects.toThrow(/Guardrail blocked node "increment"/);
  });

  it("pauses for approval when a guardrail requires it, then proceeds or fails based on the decision", async () => {
    const increment: NodeFn<CounterState> = async function* (state) {
      return { count: state.count + 1 };
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g9",
      entryNode: "increment",
      nodes: { increment },
      edges: [],
      reducer: shallowMergeReducer,
    };
    // Requires approval on BOTH the "before" and "after" guardrail phases, exercising the
    // engine's support for a node pausing more than once within a single logical execution
    // (resume() can itself pause again — see engine.ts).
    const approvalGuardrail: Guardrail = {
      async check() {
        return "require_approval";
      },
    };

    const depsApproved = { ...makeDeps(), guardrails: [approvalGuardrail] };
    const engineApproved = new GraphEngine(graph, depsApproved);
    let approvedCheckpoint = engineApproved.start({ count: 0 }, tenant, "run-9a");
    approvedCheckpoint = await engineApproved.run(approvedCheckpoint);
    expect(approvedCheckpoint.status).toBe("paused"); // before-phase pause

    approvedCheckpoint = await engineApproved.resume(approvedCheckpoint, { type: "approval", approved: true });
    expect(approvedCheckpoint.status).toBe("paused"); // after-phase pause; node body already ran

    approvedCheckpoint = await engineApproved.resume(approvedCheckpoint, { type: "approval", approved: true });
    expect(approvedCheckpoint.status).toBe("done");
    expect(approvedCheckpoint.state.count).toBe(1);

    const depsDenied = { ...makeDeps(), guardrails: [approvalGuardrail] };
    const engineDenied = new GraphEngine(graph, depsDenied);
    let deniedCheckpoint = engineDenied.start({ count: 0 }, tenant, "run-9b");
    deniedCheckpoint = await engineDenied.run(deniedCheckpoint);
    await expect(engineDenied.resume(deniedCheckpoint, { type: "approval", approved: false })).rejects.toThrow(
      /Guardrail approval was denied/,
    );
  });

  it("refuses to resume a paused run under a different tenant/session than it was paused with", async () => {
    const askApproval: NodeFn<CounterState> = async function* () {
      yield { type: "awaiting_approval", reason: "please confirm" };
      return {};
    };
    const graph: GraphDefinition<CounterState> = {
      id: "g10",
      entryNode: "ask",
      nodes: { ask: askApproval },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engine = new GraphEngine(graph, deps);
    let checkpoint = engine.start({ count: 0 }, tenant, "run-10");
    checkpoint = await engine.run(checkpoint);

    const spoofedCheckpoint = { ...checkpoint, tenantId: "tenant-b" };
    await expect(engine.resume(spoofedCheckpoint, { type: "approval", approved: true })).rejects.toThrow(
      /different tenant\/session/,
    );
  });
});
```

> **Note on Step 5's second test:** the `start` node reference is intentionally declared with `var` after use via hoisting to keep the example self-contained; when implementing, feel free to instead declare `const start: NodeFn<CounterState> = setFlag;` **before** the `graph` object literal — that is the cleaner form and both are equivalent. Use whichever reads better; the assertions are what matter.

- [ ] **Step 6: Run tests to verify they fail**

Run: `pnpm install && pnpm --filter @opentalos/core-graph test`
Expected: FAIL — `GraphEngine` is not defined.

- [ ] **Step 7: Implement `packages/core-graph/src/engine.ts`**

```ts
import type { Checkpoint, CheckpointStore, EventBus, Guardrail, TenantContext, ToolRegistry } from "@opentalos/core-types";
import type { GraphDefinition, NodeCursor, NodeFn, NodeGenerator, NodeResumeValue } from "./types.js";

export interface EngineDeps {
  toolRegistry: ToolRegistry;
  eventBus: EventBus;
  checkpointStore: CheckpointStore;
  /** Optional cross-cutting before/after hooks; see wrapWithGuardrails for how they compose with a node's own yields. */
  guardrails?: Guardrail[];
}

/** Thrown when a node body (or a guardrail wrapping it) throws; never swallowed, always paired with an "error" trace event. */
export class NodeError extends Error {
  constructor(
    public readonly nodeId: string,
    public readonly cause: unknown,
    public readonly recoverable: boolean,
  ) {
    super(`Node "${nodeId}" failed: ${cause instanceof Error ? cause.message : String(cause)}`);
    this.name = "NodeError";
  }
}

type NodeOutcome<TState> = { status: "done"; partial: Partial<TState> } | { status: "paused"; reason: string };

interface PausedEntry<TState> {
  tenant: TenantContext;
  generator: NodeGenerator<TState>;
}

export class GraphEngine<TState> {
  // The one deliberate exception to "the engine holds no cross-call state": a live, paused
  // generator can only be resumed within the same process (see the "Cross-process resume is
  // not supported" error in resume() below). Keyed by runId, with the originating tenant
  // recorded alongside it so resume() can refuse a runId reused/spoofed under a different
  // tenant — see resume()'s tenant-match check.
  private readonly paused = new Map<string, PausedEntry<TState>>();

  constructor(
    private readonly graph: GraphDefinition<TState>,
    private readonly deps: EngineDeps,
  ) {}

  start(initialState: TState, tenant: TenantContext, runId: string): Checkpoint<TState> {
    return {
      graphId: this.graph.id,
      runId,
      tenantId: tenant.tenantId,
      sessionId: tenant.sessionId,
      nodeCursor: this.graph.entryNode,
      state: initialState,
      pendingYields: [],
      status: "running",
      createdAt: new Date().toISOString(),
    };
  }

  async run(checkpoint: Checkpoint<TState>): Promise<Checkpoint<TState>> {
    let current = checkpoint;
    while (current.status === "running") {
      current = await this.step(current);
    }
    return current;
  }

  async resume(checkpoint: Checkpoint<TState>, resumeValue: NodeResumeValue): Promise<Checkpoint<TState>> {
    if (checkpoint.status !== "paused" || typeof checkpoint.nodeCursor !== "string") {
      throw new Error(`Run ${checkpoint.runId} is not in a resumable paused state`);
    }
    const nodeId = checkpoint.nodeCursor;
    const pausedEntry = this.paused.get(checkpoint.runId);
    if (!pausedEntry) {
      throw new Error(
        `No in-memory paused generator found for run ${checkpoint.runId}. Cross-process resume is not supported in this version.`,
      );
    }
    const tenant: TenantContext = { tenantId: checkpoint.tenantId, sessionId: checkpoint.sessionId };
    if (pausedEntry.tenant.tenantId !== tenant.tenantId || pausedEntry.tenant.sessionId !== tenant.sessionId) {
      throw new Error(`Run ${checkpoint.runId} was paused under a different tenant/session; refusing to resume`);
    }
    // Tentatively remove; re-added below (via onApprovalPause) if the node pauses again.
    this.paused.delete(checkpoint.runId);
    const outcome = await this.runNodeToCompletion(nodeId, pausedEntry.generator, tenant, checkpoint.runId, resumeValue, (g) => {
      this.paused.set(checkpoint.runId, { tenant, generator: g });
    });

    if (outcome.status === "paused") {
      // A node (or a guardrail wrapping it) can legitimately pause more than once within a
      // single logical execution — e.g. a guardrail requiring approval both before and after
      // the node body runs. Each pause is persisted exactly like step()'s own pause handling.
      this.emitTrace("hitl_interrupt", checkpoint.runId, tenant, { nodeId, reason: outcome.reason });
      const pausedCheckpoint: Checkpoint<TState> = {
        ...checkpoint,
        nodeCursor: nodeId,
        status: "paused",
        pendingYields: [{ type: "awaiting_approval", reason: outcome.reason }],
      };
      await this.deps.checkpointStore.save(pausedCheckpoint);
      return pausedCheckpoint;
    }

    this.emitTrace("node_exit", checkpoint.runId, tenant, { nodeId });
    const advanced = await this.completeNode(nodeId, outcome.partial, checkpoint);
    return advanced.status === "running" ? this.run(advanced) : advanced;
  }

  private async step(checkpoint: Checkpoint<TState>): Promise<Checkpoint<TState>> {
    const cursor = checkpoint.nodeCursor as NodeCursor;
    if (typeof cursor !== "string") {
      return this.stepParallel(checkpoint, cursor);
    }

    const nodeId = cursor;
    const nodeFn = this.graph.nodes[nodeId];
    if (!nodeFn) {
      throw new Error(`Unknown node: ${nodeId}`);
    }
    const tenant: TenantContext = { tenantId: checkpoint.tenantId, sessionId: checkpoint.sessionId };
    this.emitTrace("node_enter", checkpoint.runId, tenant, { nodeId });

    const guardedNodeFn = this.wrapWithGuardrails(nodeId, nodeFn);
    const generator = guardedNodeFn(checkpoint.state, { tenant, eventBus: this.deps.eventBus });
    const outcome = await this.runNodeToCompletion(nodeId, generator, tenant, checkpoint.runId, undefined, (g) => {
      this.paused.set(checkpoint.runId, { tenant, generator: g });
    });

    if (outcome.status === "paused") {
      this.emitTrace("hitl_interrupt", checkpoint.runId, tenant, { nodeId, reason: outcome.reason });
      const pausedCheckpoint: Checkpoint<TState> = {
        ...checkpoint,
        nodeCursor: nodeId,
        status: "paused",
        pendingYields: [{ type: "awaiting_approval", reason: outcome.reason }],
      };
      await this.deps.checkpointStore.save(pausedCheckpoint);
      return pausedCheckpoint;
    }

    this.emitTrace("node_exit", checkpoint.runId, tenant, { nodeId });
    return this.completeNode(nodeId, outcome.partial, checkpoint);
  }

  private async completeNode(
    nodeId: string,
    partial: Partial<TState>,
    checkpoint: Checkpoint<TState>,
  ): Promise<Checkpoint<TState>> {
    const nextState = this.graph.reducer(checkpoint.state, partial);
    const edge = this.graph.edges.find((e) => e.from === nodeId && (!e.condition || e.condition(nextState)));

    let nextCheckpoint: Checkpoint<TState>;
    if (!edge) {
      nextCheckpoint = { ...checkpoint, state: nextState, nodeCursor: nodeId, status: "done", pendingYields: [] };
    } else if (Array.isArray(edge.to)) {
      const cursor: NodeCursor = { type: "parallel", branches: edge.to, joinTo: edge.joinTo };
      nextCheckpoint = { ...checkpoint, state: nextState, nodeCursor: cursor, status: "running", pendingYields: [] };
    } else {
      nextCheckpoint = { ...checkpoint, state: nextState, nodeCursor: edge.to, status: "running", pendingYields: [] };
    }
    await this.deps.checkpointStore.save(nextCheckpoint);
    return nextCheckpoint;
  }

  private async stepParallel(
    checkpoint: Checkpoint<TState>,
    cursor: Extract<NodeCursor, { type: "parallel" }>,
  ): Promise<Checkpoint<TState>> {
    const tenant: TenantContext = { tenantId: checkpoint.tenantId, sessionId: checkpoint.sessionId };

    const partials = await Promise.all(
      cursor.branches.map(async (branchId) => {
        const nodeFn = this.graph.nodes[branchId];
        if (!nodeFn) {
          throw new Error(`Unknown node: ${branchId}`);
        }
        this.emitTrace("node_enter", checkpoint.runId, tenant, { nodeId: branchId });
        const guardedNodeFn = this.wrapWithGuardrails(branchId, nodeFn);
        const generator = guardedNodeFn(checkpoint.state, { tenant, eventBus: this.deps.eventBus });
        const outcome = await this.runNodeToCompletion(branchId, generator, tenant, checkpoint.runId, undefined, () => {
          throw new Error(
            `Node "${branchId}" attempted to await approval inside a parallel fan-out branch, which is not supported`,
          );
        });
        if (outcome.status === "paused") {
          throw new Error(
            `Node "${branchId}" attempted to await approval inside a parallel fan-out branch, which is not supported`,
          );
        }
        this.emitTrace("node_exit", checkpoint.runId, tenant, { nodeId: branchId });
        return outcome.partial;
      }),
    );

    const mergedState = partials.reduce((state, partial) => this.graph.reducer(state, partial), checkpoint.state);
    const nextCheckpoint: Checkpoint<TState> = cursor.joinTo
      ? { ...checkpoint, state: mergedState, nodeCursor: cursor.joinTo, status: "running", pendingYields: [] }
      : { ...checkpoint, state: mergedState, nodeCursor: cursor.branches[0], status: "done", pendingYields: [] };

    await this.deps.checkpointStore.save(nextCheckpoint);
    return nextCheckpoint;
  }

  private async runNodeToCompletion(
    nodeId: string,
    generator: NodeGenerator<TState>,
    tenant: TenantContext,
    runId: string,
    initialResume: NodeResumeValue,
    onApprovalPause: (generator: NodeGenerator<TState>) => void,
  ): Promise<NodeOutcome<TState>> {
    const advance = async (value: NodeResumeValue) => {
      try {
        return await generator.next(value);
      } catch (cause) {
        const error = new NodeError(nodeId, cause, false);
        this.emitTrace("error", runId, tenant, { nodeId, message: error.message });
        throw error;
      }
    };

    let result = await advance(initialResume);
    while (!result.done) {
      const yielded = result.value;
      if (yielded.type === "awaiting_tool") {
        this.emitTrace("tool_call_start", runId, tenant, { toolCall: yielded.toolCall });
        const toolResult = await this.deps.toolRegistry.execute(yielded.toolCall, tenant);
        this.emitTrace("tool_call_end", runId, tenant, { toolResult });
        result = await advance({ type: "tool_result", result: toolResult });
        continue;
      }
      onApprovalPause(generator);
      return { status: "paused", reason: yielded.reason };
    }
    return { status: "done", partial: result.value };
  }

  /**
   * Composes a node's own generator with optional before/after Guardrail checks by delegating
   * via `yield*`. A "require_approval" decision reuses the exact same awaiting_approval yield
   * (and therefore the exact same pause/resume/checkpoint machinery) as a node's own HITL yield,
   * so `resume()` needs no changes to support guardrail-triggered pauses.
   */
  private wrapWithGuardrails(nodeId: string, nodeFn: NodeFn<TState>): NodeFn<TState> {
    const guardrails = this.deps.guardrails ?? [];
    if (guardrails.length === 0) {
      return nodeFn;
    }
    return async function* guarded(state, ctx) {
      for (const guardrail of guardrails) {
        const decision = await guardrail.check({ nodeId, phase: "before", state, ctx: ctx.tenant });
        if (decision === "block") {
          throw new Error(`Guardrail blocked node "${nodeId}" before execution`);
        }
        if (decision === "require_approval") {
          const resume = yield {
            type: "awaiting_approval",
            reason: `Guardrail requires approval before running "${nodeId}"`,
          };
          if (!(resume?.type === "approval" && resume.approved)) {
            throw new Error(`Guardrail approval was denied for node "${nodeId}" before execution`);
          }
        }
      }
      const partial = yield* nodeFn(state, ctx);
      for (const guardrail of guardrails) {
        const decision = await guardrail.check({ nodeId, phase: "after", state, ctx: ctx.tenant });
        if (decision === "block") {
          throw new Error(`Guardrail blocked node "${nodeId}" after execution`);
        }
        if (decision === "require_approval") {
          const resume = yield {
            type: "awaiting_approval",
            reason: `Guardrail requires approval after running "${nodeId}"`,
          };
          if (!(resume?.type === "approval" && resume.approved)) {
            throw new Error(`Guardrail approval was denied for node "${nodeId}" after execution`);
          }
        }
      }
      return partial;
    };
  }

  private emitTrace(
    type: Parameters<EventBus["emit"]>[0]["type"],
    runId: string,
    tenant: TenantContext,
    payload?: Record<string, unknown>,
  ): void {
    this.deps.eventBus.emit({
      type,
      runId,
      tenantId: tenant.tenantId,
      sessionId: tenant.sessionId,
      timestamp: new Date().toISOString(),
      payload,
    });
  }
}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pnpm --filter @opentalos/core-graph test`
Expected: PASS — all 10 tests green (3 sequential/branch/loop + 1 tool-call + 1 HITL pause/resume + 1 cross-process resume error + 1 NodeError/error-event + 2 guardrail + 1 tenant-mismatch resume guard).

- [ ] **Step 9: Create `packages/core-graph/src/index.ts`**

```ts
export { GraphEngine, NodeError, type EngineDeps } from "./engine.js";
export { shallowMergeReducer } from "./reducer.js";
export type { EdgeDefinition, GraphDefinition, NodeContext, NodeCursor, NodeFn, NodeGenerator, NodeResumeValue, NodeYield } from "./types.js";
```

- [ ] **Step 10: Rebuild and re-run tests**

Run: `pnpm --filter @opentalos/core-graph build && pnpm --filter @opentalos/core-graph test`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add packages/core-graph pnpm-lock.yaml
git commit -m "feat(core-graph): add generator-driven GraphEngine with checkpointing and HITL pause/resume"
```

---

## Task 9: `core-graph` Package — Fan-out/Fan-in and Subgraph Nesting

**Files:**
- Create: `packages/core-graph/src/subgraph.ts`
- Modify: `packages/core-graph/src/index.ts`
- Test: `packages/core-graph/src/fan-out.test.ts`
- Test: `packages/core-graph/src/subgraph.test.ts`

### Part A — fan-out / fan-in

- [ ] **Step 1: Write the failing test — `packages/core-graph/src/fan-out.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { TenantContext } from "@opentalos/core-types";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryToolRegistry } from "@opentalos/tool-registry";
import { GraphEngine } from "./engine.js";
import { shallowMergeReducer } from "./reducer.js";
import type { GraphDefinition, NodeFn } from "./types.js";

interface FanState {
  a?: number;
  b?: number;
}

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

function makeDeps() {
  return {
    toolRegistry: new InMemoryToolRegistry(),
    eventBus: new InMemoryEventBus(),
    checkpointStore: new InMemoryCheckpointStore(),
  };
}

describe("GraphEngine — fan-out/fan-in", () => {
  it("runs branches concurrently and merges their partial state at the join node", async () => {
    const start: NodeFn<FanState> = async function* () {
      return {};
    };
    const branchA: NodeFn<FanState> = async function* () {
      return { a: 1 };
    };
    const branchB: NodeFn<FanState> = async function* () {
      return { b: 2 };
    };
    const join: NodeFn<FanState> = async function* () {
      return {};
    };
    const graph: GraphDefinition<FanState> = {
      id: "fan1",
      entryNode: "start",
      nodes: { start, branchA, branchB, join },
      edges: [{ from: "start", to: ["branchA", "branchB"], joinTo: "join" }],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const engine = new GraphEngine(graph, deps);
    let checkpoint = engine.start({}, tenant, "fan-run-1");
    checkpoint = await engine.run(checkpoint);

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state).toEqual({ a: 1, b: 2 });
    const enters = deps.eventBus.getEvents().filter((e) => e.type === "node_enter").map((e) => e.payload?.nodeId);
    expect(enters).toContain("branchA");
    expect(enters).toContain("branchB");
  });

  it("rejects a branch that tries to await approval inside a fan-out wave", async () => {
    const start: NodeFn<FanState> = async function* () {
      return {};
    };
    const pausingBranch: NodeFn<FanState> = async function* () {
      yield { type: "awaiting_approval", reason: "not allowed here" };
      return { a: 1 };
    };
    const graph: GraphDefinition<FanState> = {
      id: "fan2",
      entryNode: "start",
      nodes: { start, pausingBranch },
      edges: [{ from: "start", to: ["pausingBranch"], joinTo: undefined }],
      reducer: shallowMergeReducer,
    };
    const engine = new GraphEngine(graph, makeDeps());
    const checkpoint = engine.start({}, tenant, "fan-run-2");
    await expect(engine.run(checkpoint)).rejects.toThrow(/not supported/);
  });
});
```

- [ ] **Step 2: Run test to verify the first case fails**

Run: `pnpm --filter @opentalos/core-graph test -- fan-out`
Expected: The concurrency test should already PASS given Task 8's `stepParallel` implementation (it was built in anticipation of this). The second test (rejecting HITL inside a branch) should also already PASS. If either fails, re-read `stepParallel` in `engine.ts` from Task 8 Step 7 before changing anything else — the merge/error-throwing logic lives there, not in a new file.

- [ ] **Step 3: Confirm and commit**

Run: `pnpm --filter @opentalos/core-graph test`
Expected: PASS — all tests (Task 8's 6 plus these 2) green.

```bash
git add packages/core-graph
git commit -m "test(core-graph): cover fan-out/fan-in concurrency and HITL-in-parallel rejection"
```

### Part B — subgraph nesting

- [ ] **Step 4: Write the failing test — `packages/core-graph/src/subgraph.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { TenantContext } from "@opentalos/core-types";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryToolRegistry } from "@opentalos/tool-registry";
import { GraphEngine } from "./engine.js";
import { shallowMergeReducer } from "./reducer.js";
import { createSubgraphNode } from "./subgraph.js";
import type { GraphDefinition, NodeFn } from "./types.js";

interface ParentState {
  total: number;
}
interface ChildState {
  value: number;
}

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

function makeDeps() {
  return {
    toolRegistry: new InMemoryToolRegistry(),
    eventBus: new InMemoryEventBus(),
    checkpointStore: new InMemoryCheckpointStore(),
  };
}

describe("createSubgraphNode", () => {
  it("runs a nested graph to completion inside a single parent node", async () => {
    const double: NodeFn<ChildState> = async function* (state) {
      return { value: state.value * 2 };
    };
    const childGraph: GraphDefinition<ChildState> = {
      id: "child",
      entryNode: "double",
      nodes: { double },
      edges: [],
      reducer: shallowMergeReducer,
    };

    const deps = makeDeps();
    const subgraphNode = createSubgraphNode<ParentState, ChildState>(
      childGraph,
      deps,
      (parentState) => ({ value: parentState.total }),
      (childState) => ({ total: childState.value }),
    );

    const parentGraph: GraphDefinition<ParentState> = {
      id: "parent",
      entryNode: "child",
      nodes: { child: subgraphNode },
      edges: [],
      reducer: shallowMergeReducer,
    };

    const engine = new GraphEngine(parentGraph, deps);
    let checkpoint = engine.start({ total: 5 }, tenant, "sub-run-1");
    checkpoint = await engine.run(checkpoint);

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.total).toBe(10);
  });

  it("throws when the nested subgraph pauses for approval", async () => {
    const pause: NodeFn<ChildState> = async function* () {
      yield { type: "awaiting_approval", reason: "child needs approval" };
      return {};
    };
    const childGraph: GraphDefinition<ChildState> = {
      id: "child2",
      entryNode: "pause",
      nodes: { pause },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const subgraphNode = createSubgraphNode<ParentState, ChildState>(
      childGraph,
      deps,
      (parentState) => ({ value: parentState.total }),
      (childState) => ({ total: childState.value }),
    );
    const parentGraph: GraphDefinition<ParentState> = {
      id: "parent2",
      entryNode: "child",
      nodes: { child: subgraphNode },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const engine = new GraphEngine(parentGraph, deps);
    const checkpoint = engine.start({ total: 1 }, tenant, "sub-run-2");
    await expect(engine.run(checkpoint)).rejects.toThrow(/not supported when nested/);
  });

  it("invokes the same subgraph node repeatedly via a parent-graph loop without runId collisions", async () => {
    interface LoopState {
      total: number;
      iterations: number;
    }
    const double: NodeFn<ChildState> = async function* (state) {
      return { value: state.value * 2 };
    };
    const childGraph: GraphDefinition<ChildState> = {
      id: "child-loop",
      entryNode: "double",
      nodes: { double },
      edges: [],
      reducer: shallowMergeReducer,
    };
    const deps = makeDeps();
    const subgraphNode = createSubgraphNode<LoopState, ChildState>(
      childGraph,
      deps,
      (parentState) => ({ value: parentState.total }),
      (childState) => ({ total: childState.value }),
    );
    const countIteration: NodeFn<LoopState> = async function* (state) {
      return { iterations: state.iterations + 1 };
    };
    const parentGraph: GraphDefinition<LoopState> = {
      id: "loop-parent",
      entryNode: "child",
      nodes: { child: subgraphNode, count: countIteration },
      edges: [
        { from: "child", to: "count" },
        { from: "count", to: "child", condition: (s) => s.iterations < 3 },
      ],
      reducer: shallowMergeReducer,
    };
    const engine = new GraphEngine(parentGraph, deps);
    let checkpoint = engine.start({ total: 1, iterations: 0 }, tenant, "loop-run-1");
    checkpoint = await engine.run(checkpoint);

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.total).toBe(8); // doubled 3 times
    expect(checkpoint.state.iterations).toBe(3);

    // Each of the 3 subgraph invocations must have persisted under its own distinct runId —
    // a collision in createSubgraphNode's runId scheme would silently overwrite one call's
    // checkpoint with another's.
    const childCheckpoints = (await deps.checkpointStore.list({})).filter((c) => c.graphId === "child-loop");
    const distinctRunIds = new Set(childCheckpoints.map((c) => c.runId));
    expect(distinctRunIds.size).toBe(3);
  });
});
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `pnpm --filter @opentalos/core-graph test -- subgraph`
Expected: FAIL — `createSubgraphNode` is not defined.

- [ ] **Step 6: Implement `packages/core-graph/src/subgraph.ts`**

```ts
import { GraphEngine, type EngineDeps } from "./engine.js";
import type { GraphDefinition, NodeFn } from "./types.js";

/**
 * `deps` is shared as-is with the child engine, which has two consequences worth knowing:
 * - Guardrails match by nodeId only (see engine.ts's wrapWithGuardrails), so a guardrail
 *   configured for a nodeId in the parent graph will also apply if the child graph happens
 *   to reuse that same nodeId — since subgraphs can't handle pauses, this surfaces as the
 *   "not supported when nested" throw below, which can be confusing to debug if the real
 *   cause is an unrelated guardrail rather than the child's own logic.
 * - Every subgraph invocation persists its own checkpoints to the shared checkpointStore
 *   under a synthetic runId that's never queried again once the subgraph completes — for
 *   the in-memory store used in this phase that's harmless, but a real persistent store
 *   would accumulate orphaned rows for each subgraph call (more so inside a loop or a
 *   fan-out branch). Acceptable for now; worth revisiting when a real CheckpointStore lands.
 */
export function createSubgraphNode<TState, TSub>(
  childGraph: GraphDefinition<TSub>,
  deps: EngineDeps,
  toChildState: (state: TState) => TSub,
  fromChildState: (childState: TSub, parentState: TState) => Partial<TState>,
): NodeFn<TState> {
  return async function* subgraphNode(state, ctx) {
    const engine = new GraphEngine(childGraph, deps);
    const runId = `${ctx.tenant.sessionId}:${childGraph.id}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
    let checkpoint = engine.start(toChildState(state), ctx.tenant, runId);
    checkpoint = await engine.run(checkpoint);
    if (checkpoint.status === "paused") {
      throw new Error(
        `Subgraph "${childGraph.id}" paused for approval, which is not supported when nested inside a parent graph in this version`,
      );
    }
    return fromChildState(checkpoint.state, state);
  };
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pnpm --filter @opentalos/core-graph test -- subgraph`
Expected: PASS — all 3 tests green.

- [ ] **Step 8: Update `packages/core-graph/src/index.ts` to export the new helper**

```ts
export { GraphEngine, NodeError, type EngineDeps } from "./engine.js";
export { shallowMergeReducer } from "./reducer.js";
export { createSubgraphNode } from "./subgraph.js";
export type { EdgeDefinition, GraphDefinition, NodeContext, NodeCursor, NodeFn, NodeGenerator, NodeResumeValue, NodeYield } from "./types.js";
```

- [ ] **Step 9: Rebuild and run the full package test suite**

Run: `pnpm --filter @opentalos/core-graph build && pnpm --filter @opentalos/core-graph test`
Expected: PASS — all 15 tests in the package green (10 from Task 8, 2 fan-out, 3 subgraph).

- [ ] **Step 10: Commit**

```bash
git add packages/core-graph pnpm-lock.yaml
git commit -m "feat(core-graph): add subgraph nesting via recursive GraphEngine composition"
```

---

## Task 10: `multi-agent` Package

**Files:**
- Create: `packages/multi-agent/package.json`
- Create: `packages/multi-agent/tsconfig.json`
- Create: `packages/multi-agent/src/router-node.ts`
- Create: `packages/multi-agent/src/supervisor.ts`
- Create: `packages/multi-agent/src/swarm.ts`
- Create: `packages/multi-agent/src/index.ts`
- Test: `packages/multi-agent/src/supervisor.test.ts`
- Test: `packages/multi-agent/src/swarm.test.ts`

- [ ] **Step 1: Create `packages/multi-agent/package.json`**

```json
{
  "name": "@opentalos/multi-agent",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@opentalos/core-types": "workspace:*",
    "@opentalos/core-graph": "workspace:*"
  },
  "devDependencies": {
    "@opentalos/checkpoint": "workspace:*",
    "@opentalos/tracing": "workspace:*",
    "@opentalos/tool-registry": "workspace:*"
  }
}
```

- [ ] **Step 2: Create `packages/multi-agent/tsconfig.json`**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src"],
  "exclude": ["src/**/*.test.ts"]
}
```

- [ ] **Step 3: Create `packages/multi-agent/src/router-node.ts`**

```ts
import type { NodeFn } from "@opentalos/core-graph";

/** A no-op node used purely as a routing/join point in generated graphs. */
export function createRouterNode<TState>(): NodeFn<TState> {
  return async function* router() {
    return {};
  };
}
```

- [ ] **Step 4: Write the failing test — `packages/multi-agent/src/supervisor.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { TenantContext } from "@opentalos/core-types";
import { GraphEngine } from "@opentalos/core-graph";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryToolRegistry } from "@opentalos/tool-registry";
import { buildSupervisorGraph } from "./supervisor.js";
import type { NodeFn } from "@opentalos/core-graph";

interface PlanState {
  plan: string[];
  cursor: number;
  results: string[];
}

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

function makeDeps() {
  return {
    toolRegistry: new InMemoryToolRegistry(),
    eventBus: new InMemoryEventBus(),
    checkpointStore: new InMemoryCheckpointStore(),
  };
}

describe("buildSupervisorGraph", () => {
  it("routes to each named agent in the order the route function returns, then finishes", async () => {
    const researcher: NodeFn<PlanState> = async function* (state) {
      return { results: [...state.results, "researched"], cursor: state.cursor + 1 };
    };
    const writer: NodeFn<PlanState> = async function* (state) {
      return { results: [...state.results, "written"], cursor: state.cursor + 1 };
    };

    const graph = buildSupervisorGraph<PlanState>({
      id: "plan-agent",
      agents: { researcher, writer },
      route: (state) => state.plan[state.cursor] ?? "DONE",
      reducer: (state, partial) => ({ ...state, ...partial }),
    });

    const engine = new GraphEngine(graph, makeDeps());
    let checkpoint = engine.start({ plan: ["researcher", "writer"], cursor: 0, results: [] }, tenant, "sup-run-1");
    checkpoint = await engine.run(checkpoint);

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.results).toEqual(["researched", "written"]);
  });
});
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pnpm install && pnpm --filter @opentalos/multi-agent test -- supervisor`
Expected: FAIL — `buildSupervisorGraph` is not defined.

- [ ] **Step 6: Implement `packages/multi-agent/src/supervisor.ts`**

```ts
import type { EdgeDefinition, GraphDefinition, NodeFn } from "@opentalos/core-graph";
import { createRouterNode } from "./router-node.js";

export interface SupervisorConfig<TState> {
  id: string;
  agents: Record<string, NodeFn<TState>>;
  /** Reads state and returns the key of the agent to call next, or "DONE" to finish. */
  route: (state: TState) => string;
  reducer: (state: TState, partial: Partial<TState>) => TState;
}

export function buildSupervisorGraph<TState>(config: SupervisorConfig<TState>): GraphDefinition<TState> {
  const nodes: Record<string, NodeFn<TState>> = {
    router: createRouterNode<TState>(),
    done: createRouterNode<TState>(),
    ...config.agents,
  };

  const edges: EdgeDefinition<TState>[] = [];
  for (const agentKey of Object.keys(config.agents)) {
    edges.push({ from: "router", to: agentKey, condition: (state) => config.route(state) === agentKey });
    edges.push({ from: agentKey, to: "router" });
  }
  edges.push({ from: "router", to: "done", condition: (state) => config.route(state) === "DONE" });

  return { id: config.id, entryNode: "router", nodes, edges, reducer: config.reducer };
}
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pnpm --filter @opentalos/multi-agent test -- supervisor`
Expected: PASS.

- [ ] **Step 8: Write the failing test — `packages/multi-agent/src/swarm.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { TenantContext } from "@opentalos/core-types";
import { GraphEngine } from "@opentalos/core-graph";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryToolRegistry } from "@opentalos/tool-registry";
import { buildSwarmGraph } from "./swarm.js";
import type { NodeFn } from "@opentalos/core-graph";

interface SwarmState {
  votes: string[];
}

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

function makeDeps() {
  return {
    toolRegistry: new InMemoryToolRegistry(),
    eventBus: new InMemoryEventBus(),
    checkpointStore: new InMemoryCheckpointStore(),
  };
}

describe("buildSwarmGraph", () => {
  it("fans out to every agent in parallel and merges their partial state at the join", async () => {
    const optimist: NodeFn<SwarmState> = async function* (state) {
      return { votes: [...state.votes, "yes"] };
    };
    const skeptic: NodeFn<SwarmState> = async function* (state) {
      return { votes: [...state.votes, "no"] };
    };
    // reducer concatenates votes arrays instead of overwriting, since both branches read the same starting state
    const graph = buildSwarmGraph<SwarmState>({
      id: "swarm-agent",
      agents: { optimist, skeptic },
      reducer: (state, partial) => ({ votes: [...state.votes, ...(partial.votes ?? []).slice(state.votes.length)] }),
    });
    const engine = new GraphEngine(graph, makeDeps());
    let checkpoint = engine.start({ votes: [] }, tenant, "swarm-run-1");
    checkpoint = await engine.run(checkpoint);

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.votes.sort()).toEqual(["no", "yes"]);
  });
});
```

- [ ] **Step 9: Run test to verify it fails**

Run: `pnpm --filter @opentalos/multi-agent test -- swarm`
Expected: FAIL — `buildSwarmGraph` is not defined.

- [ ] **Step 10: Implement `packages/multi-agent/src/swarm.ts`**

```ts
import type { GraphDefinition, NodeFn } from "@opentalos/core-graph";
import { createRouterNode } from "./router-node.js";

export interface SwarmConfig<TState> {
  id: string;
  agents: Record<string, NodeFn<TState>>;
  reducer: (state: TState, partial: Partial<TState>) => TState;
}

export function buildSwarmGraph<TState>(config: SwarmConfig<TState>): GraphDefinition<TState> {
  const nodes: Record<string, NodeFn<TState>> = {
    start: createRouterNode<TState>(),
    join: createRouterNode<TState>(),
    ...config.agents,
  };
  return {
    id: config.id,
    entryNode: "start",
    nodes,
    edges: [{ from: "start", to: Object.keys(config.agents), joinTo: "join" }],
    reducer: config.reducer,
  };
}
```

- [ ] **Step 11: Run test to verify it passes**

Run: `pnpm --filter @opentalos/multi-agent test -- swarm`
Expected: PASS.

- [ ] **Step 12: Create `packages/multi-agent/src/index.ts`**

```ts
export { createRouterNode } from "./router-node.js";
export { buildSupervisorGraph, type SupervisorConfig } from "./supervisor.js";
export { buildSwarmGraph, type SwarmConfig } from "./swarm.js";
```

- [ ] **Step 13: Rebuild and run the full package test suite**

Run: `pnpm --filter @opentalos/multi-agent build && pnpm --filter @opentalos/multi-agent test`
Expected: PASS — both tests green.

- [ ] **Step 14: Commit**

```bash
git add packages/multi-agent pnpm-lock.yaml
git commit -m "feat(multi-agent): add supervisor and swarm graph builders on top of core-graph"
```

---

## Task 11: `sdk` Package

**Files:**
- Create: `packages/sdk/package.json`
- Create: `packages/sdk/tsconfig.json`
- Create: `packages/sdk/src/index.ts`
- Test: `packages/sdk/src/index.test.ts`

- [ ] **Step 1: Create `packages/sdk/package.json`**

```json
{
  "name": "@opentalos/sdk",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@opentalos/core-types": "workspace:*",
    "@opentalos/core-graph": "workspace:*",
    "@opentalos/checkpoint": "workspace:*",
    "@opentalos/tracing": "workspace:*",
    "@opentalos/tool-registry": "workspace:*"
  }
}
```

- [ ] **Step 2: Create `packages/sdk/tsconfig.json`**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src"],
  "exclude": ["src/**/*.test.ts"]
}
```

- [ ] **Step 3: Write the failing tests — `packages/sdk/src/index.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { TenantContext } from "@opentalos/core-types";
import type { NodeFn } from "@opentalos/core-graph";
import { createEngine, defineGraph } from "./index.js";

interface State {
  count: number;
}

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

describe("sdk", () => {
  it("defineGraph fills in a default shallow-merge reducer when none is given", async () => {
    const increment: NodeFn<State> = async function* (state) {
      return { count: state.count + 1 };
    };
    const graph = defineGraph<State>({ id: "g1", entryNode: "inc", nodes: { inc: increment }, edges: [] });
    const engine = createEngine(graph);
    let checkpoint = engine.start({ count: 0 }, tenant, "sdk-run-1");
    checkpoint = await engine.run(checkpoint);
    expect(checkpoint.state.count).toBe(1);
  });

  it("createEngine wires in-memory defaults for tool registry, event bus, and checkpoint store", async () => {
    const graph = defineGraph<State>({
      id: "g2",
      entryNode: "inc",
      nodes: {
        inc: async function* (state) {
          return { count: state.count + 1 };
        },
      },
      edges: [],
    });
    const engine = createEngine(graph);
    let checkpoint = engine.start({ count: 0 }, tenant, "sdk-run-2");
    checkpoint = await engine.run(checkpoint);
    expect(checkpoint.status).toBe("done");
  });
});
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pnpm install && pnpm --filter @opentalos/sdk test`
Expected: FAIL — `defineGraph`/`createEngine` are not defined.

- [ ] **Step 5: Implement `packages/sdk/src/index.ts`**

```ts
import type { CheckpointStore, EventBus, ToolRegistry } from "@opentalos/core-types";
import { GraphEngine, shallowMergeReducer, type EdgeDefinition, type GraphDefinition, type NodeFn } from "@opentalos/core-graph";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryToolRegistry } from "@opentalos/tool-registry";

export interface DefineGraphOptions<TState> {
  id: string;
  entryNode: string;
  nodes: Record<string, NodeFn<TState>>;
  edges: EdgeDefinition<TState>[];
  reducer?: (state: TState, partial: Partial<TState>) => TState;
}

export function defineGraph<TState extends object>(options: DefineGraphOptions<TState>): GraphDefinition<TState> {
  return {
    id: options.id,
    entryNode: options.entryNode,
    nodes: options.nodes,
    edges: options.edges,
    reducer: options.reducer ?? shallowMergeReducer,
  };
}

export interface CreateEngineOptions {
  toolRegistry?: ToolRegistry;
  eventBus?: EventBus;
  checkpointStore?: CheckpointStore;
}

export function createEngine<TState>(graph: GraphDefinition<TState>, deps: CreateEngineOptions = {}): GraphEngine<TState> {
  return new GraphEngine(graph, {
    toolRegistry: deps.toolRegistry ?? new InMemoryToolRegistry(),
    eventBus: deps.eventBus ?? new InMemoryEventBus(),
    checkpointStore: deps.checkpointStore ?? new InMemoryCheckpointStore(),
  });
}

export { GraphEngine, shallowMergeReducer } from "@opentalos/core-graph";
export type { EdgeDefinition, GraphDefinition, NodeContext, NodeFn, NodeGenerator, NodeResumeValue, NodeYield } from "@opentalos/core-graph";
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pnpm --filter @opentalos/sdk test`
Expected: PASS — both tests green.

- [ ] **Step 7: Rebuild**

Run: `pnpm --filter @opentalos/sdk build`
Expected: PASS, no TypeScript errors.

- [ ] **Step 8: Commit**

```bash
git add packages/sdk pnpm-lock.yaml
git commit -m "feat(sdk): add defineGraph/createEngine code-driven entry point"
```

---

## Task 12: `config-loader` Package

**Files:**
- Create: `packages/config-loader/package.json`
- Create: `packages/config-loader/tsconfig.json`
- Create: `packages/config-loader/src/schema.ts`
- Create: `packages/config-loader/src/compile.ts`
- Create: `packages/config-loader/src/index.ts`
- Test: `packages/config-loader/src/schema.test.ts`
- Test: `packages/config-loader/src/compile.test.ts`

Declarative config cannot embed arbitrary executable logic safely, so a config graph references pre-registered **node factories** and **condition factories** by name; the actual TypeScript implementations of those factories are supplied by the calling application.

- [ ] **Step 1: Create `packages/config-loader/package.json`**

```json
{
  "name": "@opentalos/config-loader",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@opentalos/core-graph": "workspace:*",
    "js-yaml": "^5.4.1",
    "zod": "^4.5.4"
  }
}
```

- [ ] **Step 2: Create `packages/config-loader/tsconfig.json`**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src"],
  "exclude": ["src/**/*.test.ts"]
}
```

- [ ] **Step 3: Write the failing tests — `packages/config-loader/src/schema.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import { loadGraphConfig } from "./schema.js";

describe("loadGraphConfig", () => {
  it("parses a YAML graph config into a validated GraphConfig", () => {
    const yaml = `
id: greeting-agent
entryNode: greet
nodes:
  greet:
    use: greetNode
edges:
  - from: greet
    to: greet
    when: shouldRepeat
`;
    const config = loadGraphConfig(yaml);
    expect(config).toEqual({
      id: "greeting-agent",
      entryNode: "greet",
      nodes: { greet: { use: "greetNode" } },
      edges: [{ from: "greet", to: "greet", when: "shouldRepeat" }],
    });
  });

  it("parses a JSON graph config", () => {
    const json = JSON.stringify({
      id: "g",
      entryNode: "n1",
      nodes: { n1: { use: "factoryA" } },
      edges: [],
    });
    const config = loadGraphConfig(json);
    expect(config.id).toBe("g");
  });

  it("rejects a config missing a required field", () => {
    expect(() => loadGraphConfig(JSON.stringify({ id: "g", nodes: {}, edges: [] }))).toThrow();
  });
});
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pnpm install && pnpm --filter @opentalos/config-loader test -- schema`
Expected: FAIL — `loadGraphConfig` is not defined.

- [ ] **Step 5: Implement `packages/config-loader/src/schema.ts`**

```ts
import { load as loadYaml } from "js-yaml";
import { z } from "zod";

const edgeSchema = z.object({
  from: z.string(),
  to: z.union([z.string(), z.array(z.string())]),
  joinTo: z.string().optional(),
  when: z.string().optional(),
});

const nodeRefSchema = z.object({
  use: z.string(),
  params: z.record(z.string(), z.unknown()).optional(),
});

const graphConfigSchema = z.object({
  id: z.string(),
  entryNode: z.string(),
  nodes: z.record(z.string(), nodeRefSchema),
  edges: z.array(edgeSchema),
});

export type GraphConfig = z.infer<typeof graphConfigSchema>;
export type NodeRefConfig = z.infer<typeof nodeRefSchema>;
export type EdgeConfig = z.infer<typeof edgeSchema>;

export function loadGraphConfig(yamlOrJson: string): GraphConfig {
  const trimmed = yamlOrJson.trim();
  const raw = trimmed.startsWith("{") ? JSON.parse(trimmed) : loadYaml(trimmed);
  return graphConfigSchema.parse(raw);
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pnpm --filter @opentalos/config-loader test -- schema`
Expected: PASS — all 3 tests green.

- [ ] **Step 7: Write the failing test — `packages/config-loader/src/compile.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { TenantContext } from "@opentalos/core-types";
import { GraphEngine, shallowMergeReducer, type NodeFn } from "@opentalos/core-graph";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryToolRegistry } from "@opentalos/tool-registry";
import { loadGraphConfig } from "./schema.js";
import { compileGraphConfig } from "./compile.js";

interface State {
  count: number;
}

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

describe("compileGraphConfig", () => {
  it("resolves node factories by name and builds a runnable GraphDefinition", async () => {
    const config = loadGraphConfig(`
id: counter
entryNode: tick
nodes:
  tick:
    use: incrementBy
    params:
      amount: 3
edges: []
`);
    const incrementByFactory = (params: Record<string, unknown> | undefined): NodeFn<State> => {
      const amount = (params?.amount as number) ?? 1;
      return async function* (state) {
        return { count: state.count + amount };
      };
    };

    const graph = compileGraphConfig<State>(config, { incrementBy: incrementByFactory }, {}, shallowMergeReducer);
    const engine = new GraphEngine(graph, {
      toolRegistry: new InMemoryToolRegistry(),
      eventBus: new InMemoryEventBus(),
      checkpointStore: new InMemoryCheckpointStore(),
    });
    let checkpoint = engine.start({ count: 0 }, tenant, "cfg-run-1");
    checkpoint = await engine.run(checkpoint);
    expect(checkpoint.state.count).toBe(3);
  });

  it("throws a clear error when a node references an unregistered factory", () => {
    const config = loadGraphConfig(`
id: bad
entryNode: n1
nodes:
  n1:
    use: doesNotExist
edges: []
`);
    expect(() => compileGraphConfig<State>(config, {}, {}, shallowMergeReducer)).toThrow(/doesNotExist/);
  });
});
```

- [ ] **Step 8: Run test to verify it fails**

Run: `pnpm --filter @opentalos/config-loader test -- compile`
Expected: FAIL — `compileGraphConfig` is not defined.

- [ ] **Step 9: Implement `packages/config-loader/src/compile.ts`**

```ts
import type { EdgeDefinition, GraphDefinition, NodeFn } from "@opentalos/core-graph";
import type { GraphConfig } from "./schema.js";

export type NodeFactory<TState> = (params: Record<string, unknown> | undefined) => NodeFn<TState>;
export type ConditionFactory<TState> = (state: TState) => boolean;

export function compileGraphConfig<TState>(
  config: GraphConfig,
  nodeFactories: Record<string, NodeFactory<TState>>,
  conditionFactories: Record<string, ConditionFactory<TState>>,
  reducer: (state: TState, partial: Partial<TState>) => TState,
): GraphDefinition<TState> {
  const nodes: Record<string, NodeFn<TState>> = {};
  for (const [nodeId, ref] of Object.entries(config.nodes)) {
    const factory = nodeFactories[ref.use];
    if (!factory) {
      throw new Error(`Unknown node factory "${ref.use}" referenced by node "${nodeId}"`);
    }
    nodes[nodeId] = factory(ref.params);
  }

  const edges: EdgeDefinition<TState>[] = config.edges.map((edge) => {
    if (edge.when && !conditionFactories[edge.when]) {
      throw new Error(`Unknown condition factory "${edge.when}" referenced by edge from "${edge.from}"`);
    }
    return {
      from: edge.from,
      to: edge.to,
      joinTo: edge.joinTo,
      condition: edge.when ? conditionFactories[edge.when] : undefined,
    };
  });

  return { id: config.id, entryNode: config.entryNode, nodes, edges, reducer };
}
```

- [ ] **Step 10: Run test to verify it passes**

Run: `pnpm --filter @opentalos/config-loader test -- compile`
Expected: PASS — both tests green.

- [ ] **Step 11: Create `packages/config-loader/src/index.ts`**

```ts
export { loadGraphConfig, type GraphConfig, type NodeRefConfig, type EdgeConfig } from "./schema.js";
export { compileGraphConfig, type ConditionFactory, type NodeFactory } from "./compile.js";
```

- [ ] **Step 12: Rebuild and run the full package test suite**

Run: `pnpm --filter @opentalos/config-loader build && pnpm --filter @opentalos/config-loader test`
Expected: PASS — all 5 tests green.

- [ ] **Step 13: Commit**

```bash
git add packages/config-loader pnpm-lock.yaml
git commit -m "feat(config-loader): add YAML/JSON graph config schema and compiler"
```

---

## Task 13: `examples/research-agent` — End-to-End Integration Example

This proves the full stack together: multi-agent supervisor orchestration, automatic tool-call resolution, HITL pause/resume, checkpoint persistence, and trace event emission, all wired through the `sdk`-style composition.

**Files:**
- Create: `examples/research-agent/package.json`
- Create: `examples/research-agent/tsconfig.json`
- Create: `examples/research-agent/src/state.ts`
- Create: `examples/research-agent/src/tools.ts`
- Create: `examples/research-agent/src/graph.ts`
- Test: `examples/research-agent/src/index.test.ts`

- [ ] **Step 1: Create `examples/research-agent/package.json`**

```json
{
  "name": "@opentalos/example-research-agent",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "dependencies": {
    "@opentalos/core-types": "workspace:*",
    "@opentalos/core-graph": "workspace:*",
    "@opentalos/multi-agent": "workspace:*",
    "@opentalos/checkpoint": "workspace:*",
    "@opentalos/tracing": "workspace:*",
    "@opentalos/tool-registry": "workspace:*"
  }
}
```

- [ ] **Step 2: Create `examples/research-agent/tsconfig.json`**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src"],
  "exclude": ["src/**/*.test.ts"]
}
```

- [ ] **Step 3: Create `examples/research-agent/src/state.ts`**

```ts
export interface ResearchState {
  topic: string;
  findings: string[];
  draft: string;
  approved: boolean;
  nextAgent: "researcher" | "writer" | "DONE";
}
```

- [ ] **Step 4: Create `examples/research-agent/src/tools.ts`**

```ts
import type { Tool } from "@opentalos/core-types";

export const searchTool: Tool = {
  definition: {
    name: "search",
    description: "Looks up findings for a research topic",
    inputSchema: { type: "object", properties: { query: { type: "string" } }, required: ["query"] },
  },
  async execute(input) {
    const { query } = input as { query: string };
    return {
      id: `search-result-${Date.now()}`,
      output: [`${query} is a widely studied subject`, `${query} has active open-source implementations`],
    };
  },
};
```

- [ ] **Step 5: Create `examples/research-agent/src/graph.ts`**

```ts
import { shallowMergeReducer, type NodeFn } from "@opentalos/core-graph";
import { buildSupervisorGraph } from "@opentalos/multi-agent";
import type { ResearchState } from "./state.js";

export const researcherNode: NodeFn<ResearchState> = async function* researcher(state) {
  const resume = yield {
    type: "awaiting_tool",
    toolCall: { id: `search-${Date.now()}`, name: "search", input: { query: state.topic } },
  };
  const output = resume?.type === "tool_result" ? resume.result.output : [];
  const findings = Array.isArray(output) ? (output as string[]) : [String(output)];
  return { findings, nextAgent: "writer" };
};

export const writerNode: NodeFn<ResearchState> = async function* writer(state) {
  const draft = `Report on ${state.topic}: ${state.findings.join("; ")}`;
  const resume = yield { type: "awaiting_approval", reason: "Please approve the draft before publishing" };
  if (resume?.type === "approval" && resume.approved) {
    return { draft, approved: true, nextAgent: "DONE" };
  }
  return { nextAgent: "researcher" };
};

export const researchAgentGraph = buildSupervisorGraph<ResearchState>({
  id: "research-agent",
  agents: { researcher: researcherNode, writer: writerNode },
  route: (state) => state.nextAgent,
  reducer: shallowMergeReducer,
});
```

- [ ] **Step 6: Write the failing integration test — `examples/research-agent/src/index.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import { GraphEngine } from "@opentalos/core-graph";
import { InMemoryToolRegistry } from "@opentalos/tool-registry";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import { researchAgentGraph } from "./graph.js";
import { searchTool } from "./tools.js";
import type { ResearchState } from "./state.js";

describe("research agent example", () => {
  it("runs researcher -> writer, pauses for approval, resumes, and finishes", async () => {
    const toolRegistry = new InMemoryToolRegistry();
    toolRegistry.register(searchTool);
    const eventBus = new InMemoryEventBus();
    const checkpointStore = new InMemoryCheckpointStore();
    const engine = new GraphEngine<ResearchState>(researchAgentGraph, { toolRegistry, eventBus, checkpointStore });

    const initialState: ResearchState = {
      topic: "agent harness",
      findings: [],
      draft: "",
      approved: false,
      nextAgent: "researcher",
    };
    let checkpoint = engine.start(initialState, { tenantId: "tenant-a", sessionId: "session-1" }, "run-1");
    checkpoint = await engine.run(checkpoint);

    expect(checkpoint.status).toBe("paused");
    expect(checkpoint.pendingYields).toEqual([
      { type: "awaiting_approval", reason: "Please approve the draft before publishing" },
    ]);

    checkpoint = await engine.resume(checkpoint, { type: "approval", approved: true });

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.approved).toBe(true);
    expect(checkpoint.state.draft).toContain("agent harness");

    const persisted = await checkpointStore.load("run-1");
    expect(persisted?.status).toBe("done");

    const eventTypes = eventBus.getEvents().map((e) => e.type);
    expect(eventTypes).toContain("tool_call_start");
    expect(eventTypes).toContain("tool_call_end");
    expect(eventTypes).toContain("hitl_interrupt");
    expect(eventTypes.filter((t) => t === "node_enter").length).toBeGreaterThanOrEqual(3);
  });
});
```

- [ ] **Step 7: Run test to verify it fails**

Run: `pnpm install && pnpm --filter @opentalos/example-research-agent test`
Expected: FAIL — modules not resolvable until Step 3-5 files exist (if run out of order) or assertion failures if wiring is wrong.

- [ ] **Step 8: Run test to verify it passes**

Run: `pnpm --filter @opentalos/example-research-agent test`
Expected: PASS — the single end-to-end test green.

- [ ] **Step 9: Build and run the entire monorepo test suite from the root**

Run: `pnpm run build && pnpm run test`
Expected: PASS — every package across the whole monorepo builds and all tests pass.

- [ ] **Step 10: Commit**

```bash
git add examples/research-agent pnpm-lock.yaml
git commit -m "test(examples): add end-to-end research-agent example covering the full engine stack"
```

---

## Final Verification

- [ ] Run `pnpm run typecheck` from the repo root — expect PASS with no type errors across every package.
- [ ] Run `pnpm run test` from the repo root — expect PASS across all 13 packages/examples.
- [ ] Re-read `docs/superpowers/specs/2026-09-09-core-agent-runtime-engine-design.md` section by section and confirm each capability (tool calling + MCP, multi-agent, planning-style branching/looping, memory, HITL/guardrail hooks, model provider abstraction, tracing) has a corresponding implemented package and passing test from this plan.
