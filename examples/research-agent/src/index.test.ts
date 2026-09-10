import { describe, expect, it } from "vitest";
import { GraphEngine } from "@opentalos/core-graph";
import { InMemoryToolRegistry } from "@opentalos/tool-registry";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import type { ModelProvider, ModelResponseChunk } from "@opentalos/core-types";
import { buildResearchAgentGraph } from "./graph.js";
import { searchTool } from "./tools.js";
import type { ResearchState } from "./state.js";

function scriptedProvider(responses: ModelResponseChunk[][]): ModelProvider {
  let callIndex = 0;
  return {
    async *complete() {
      const chunks = responses[callIndex] ?? [];
      callIndex += 1;
      for (const chunk of chunks) yield chunk;
    },
  };
}

describe("research agent example", () => {
  it("runs researcher (via a tool call) -> writer (drafts from findings), pauses for approval, resumes, and finishes", async () => {
    const toolRegistry = new InMemoryToolRegistry();
    toolRegistry.register(searchTool);
    const eventBus = new InMemoryEventBus();
    const checkpointStore = new InMemoryCheckpointStore();
    const modelProvider = scriptedProvider([
      // researcher's turn: request the search tool once, then stop requesting tools
      [{ type: "tool_call", toolCall: { id: "call-1", name: "search", input: { query: "agent harness" } } }],
      [{ type: "text_delta", textDelta: "agent harness is a widely studied subject" }, { type: "message_stop" }],
      // writer's turn: draft the report from findings
      [{ type: "text_delta", textDelta: "Report: agent harness is a widely studied subject" }, { type: "message_stop" }],
    ]);
    const engine = new GraphEngine<ResearchState>(buildResearchAgentGraph(modelProvider, toolRegistry), {
      toolRegistry,
      eventBus,
      checkpointStore,
    });

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
  });
});
