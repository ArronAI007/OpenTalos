import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { Pool } from "pg";
import type { TraceEvent } from "@opentalos/core-types";
import { PostgresEventBus, listEventsSince } from "./event-bus.js";

let container: StartedPostgreSqlContainer;
let pool: Pool;

beforeAll(async () => {
  container = await new PostgreSqlContainer("postgres:16-alpine").start();
  pool = new Pool({ connectionString: container.getConnectionUri() });
  await pool.query(`
    CREATE TABLE trace_events (
      id SERIAL PRIMARY KEY,
      run_id TEXT NOT NULL,
      tenant_id TEXT NOT NULL,
      session_id TEXT NOT NULL,
      type TEXT NOT NULL,
      payload JSONB,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
  `);
}, 120_000);

afterAll(async () => {
  await pool.end();
  await container.stop();
});

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

describe("PostgresEventBus", () => {
  it("persists an emitted event and it becomes visible via listEventsSince", async () => {
    const bus = new PostgresEventBus(pool);
    bus.emit(makeEvent({ runId: "run-emit-1", payload: { nodeId: "plan" } }));
    await bus.flush();

    const events = await listEventsSince(pool, "run-emit-1", 0);
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("node_enter");
    expect(events[0].payload).toEqual({ nodeId: "plan" });
  });

  it("preserves emission order across multiple events for the same run", async () => {
    const bus = new PostgresEventBus(pool);
    bus.emit(makeEvent({ runId: "run-order-1", type: "node_enter" }));
    bus.emit(makeEvent({ runId: "run-order-1", type: "tool_call_start" }));
    bus.emit(makeEvent({ runId: "run-order-1", type: "tool_call_end" }));
    await bus.flush();

    const events = await listEventsSince(pool, "run-order-1", 0);
    expect(events.map((e) => e.type)).toEqual(["node_enter", "tool_call_start", "tool_call_end"]);
  });

  it("listEventsSince only returns events after the given cursor", async () => {
    const bus = new PostgresEventBus(pool);
    bus.emit(makeEvent({ runId: "run-cursor-1", type: "node_enter" }));
    await bus.flush();
    const first = await listEventsSince(pool, "run-cursor-1", 0);
    expect(first).toHaveLength(1);
    const cursor = first[0].id;

    bus.emit(makeEvent({ runId: "run-cursor-1", type: "node_exit" }));
    await bus.flush();

    const onlyNew = await listEventsSince(pool, "run-cursor-1", cursor);
    expect(onlyNew).toHaveLength(1);
    expect(onlyNew[0].type).toBe("node_exit");
  });

  it("only returns events for the requested runId", async () => {
    const bus = new PostgresEventBus(pool);
    bus.emit(makeEvent({ runId: "run-scope-a", type: "node_enter" }));
    bus.emit(makeEvent({ runId: "run-scope-b", type: "node_enter" }));
    await bus.flush();

    const eventsA = await listEventsSince(pool, "run-scope-a", 0);
    expect(eventsA).toHaveLength(1);
    expect(eventsA[0].runId).toBe("run-scope-a");
  });

  it("subscribe() returns a no-op unsubscribe function and does not throw", () => {
    const bus = new PostgresEventBus(pool);
    const unsubscribe = bus.subscribe(() => {});
    expect(() => unsubscribe()).not.toThrow();
  });
});
