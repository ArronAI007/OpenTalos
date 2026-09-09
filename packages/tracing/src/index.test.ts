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
