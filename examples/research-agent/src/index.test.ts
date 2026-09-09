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
