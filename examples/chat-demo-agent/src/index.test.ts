import { describe, expect, it } from "vitest";
import { GraphEngine } from "@opentalos/core-graph";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import { buildChatDemoAgentGraph } from "./graph.js";
import { createChatDemoAgentToolRegistry } from "./registry.js";
import type { ChatState } from "./state.js";

describe("chat demo agent example", () => {
  it("plans, calls the exchange-rate tool, pauses for approval, resumes, and replies", async () => {
    const toolRegistry = createChatDemoAgentToolRegistry();
    const eventBus = new InMemoryEventBus();
    const checkpointStore = new InMemoryCheckpointStore();
    const engine = new GraphEngine<ChatState>(buildChatDemoAgentGraph(), { toolRegistry, eventBus, checkpointStore });

    const initialState: ChatState = { message: "今天美元兑人民币汇率是多少？" };
    let checkpoint = engine.start(initialState, { tenantId: "tenant-a", sessionId: "session-1" }, "run-1");
    checkpoint = await engine.run(checkpoint);

    expect(checkpoint.status).toBe("paused");
    expect(checkpoint.state.searchResult).toContain("USD/CNY");

    checkpoint = await engine.resume(checkpoint, { type: "approval", approved: true });

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.reply).toContain(checkpoint.state.searchResult as string);

    const eventTypes = eventBus.getEvents().map((e) => e.type);
    expect(eventTypes).toContain("tool_call_start");
    expect(eventTypes).toContain("tool_call_end");
    expect(eventTypes).toContain("hitl_interrupt");
  });

  it("does not include the search result in the reply when the user declines approval", async () => {
    const toolRegistry = createChatDemoAgentToolRegistry();
    const eventBus = new InMemoryEventBus();
    const checkpointStore = new InMemoryCheckpointStore();
    const engine = new GraphEngine<ChatState>(buildChatDemoAgentGraph(), { toolRegistry, eventBus, checkpointStore });

    const initialState: ChatState = { message: "今天美元兑人民币汇率是多少？" };
    let checkpoint = engine.start(initialState, { tenantId: "tenant-a", sessionId: "session-2" }, "run-2");
    checkpoint = await engine.run(checkpoint);
    checkpoint = await engine.resume(checkpoint, { type: "approval", approved: false });

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.approved).toBe(false);
    expect(checkpoint.state.reply).toBe("好的，我不会发送这条回复。");
  });
});
