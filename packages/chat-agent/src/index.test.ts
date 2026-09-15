import { describe, expect, it } from "vitest";
import { GraphEngine } from "@opentalos/core-graph";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import type { ModelProvider, ModelResponseChunk } from "@opentalos/core-types";
import type { Skill } from "@opentalos/skills";
import { buildChatAgentGraph } from "./graph.js";
import { createChatAgentToolRegistry } from "./registry.js";
import type { ChatState } from "./state.js";

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

describe("chat agent", () => {
  it("lets the model decide to call the exchange-rate tool, pauses for approval, resumes, and replies with the model's own text", async () => {
    const toolRegistry = createChatAgentToolRegistry();
    const eventBus = new InMemoryEventBus();
    const checkpointStore = new InMemoryCheckpointStore();
    const modelProvider = scriptedProvider([
      [{ type: "tool_call", toolCall: { id: "call-1", name: "lookup_exchange_rate", input: { pair: "USD/CNY" } } }],
      [{ type: "text_delta", textDelta: "根据查询结果：今天汇率是 7.13" }, { type: "message_stop" }],
    ]);
    const engine = new GraphEngine<ChatState>(buildChatAgentGraph(modelProvider, toolRegistry), {
      toolRegistry,
      eventBus,
      checkpointStore,
    });

    const initialState: ChatState = { message: "今天美元兑人民币汇率是多少？" };
    let checkpoint = engine.start(initialState, { tenantId: "tenant-a", sessionId: "session-1" }, "run-1");
    checkpoint = await engine.run(checkpoint);

    expect(checkpoint.status).toBe("paused");

    checkpoint = await engine.resume(checkpoint, { type: "approval", approved: true });

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.reply).toBe("根据查询结果：今天汇率是 7.13");

    const eventTypes = eventBus.getEvents().map((e) => e.type);
    expect(eventTypes).toContain("tool_call_start");
    expect(eventTypes).toContain("tool_call_end");
    expect(eventTypes).toContain("hitl_interrupt");
  });

  it("does not send the model's reply when the user declines approval", async () => {
    const toolRegistry = createChatAgentToolRegistry();
    const eventBus = new InMemoryEventBus();
    const checkpointStore = new InMemoryCheckpointStore();
    const modelProvider = scriptedProvider([
      [{ type: "tool_call", toolCall: { id: "call-1", name: "lookup_exchange_rate", input: { pair: "USD/CNY" } } }],
      [{ type: "text_delta", textDelta: "今天汇率是 7.13" }, { type: "message_stop" }],
    ]);
    const engine = new GraphEngine<ChatState>(buildChatAgentGraph(modelProvider, toolRegistry), {
      toolRegistry,
      eventBus,
      checkpointStore,
    });

    const initialState: ChatState = { message: "今天美元兑人民币汇率是多少？" };
    let checkpoint = engine.start(initialState, { tenantId: "tenant-a", sessionId: "session-2" }, "run-2");
    checkpoint = await engine.run(checkpoint);
    checkpoint = await engine.resume(checkpoint, { type: "approval", approved: false });

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.approved).toBe(false);
    expect(checkpoint.state.reply).toBe("好的，我不会发送这条回复。");
  });

  it("skips the approval pause entirely when the model replies without calling a tool", async () => {
    const toolRegistry = createChatAgentToolRegistry();
    const eventBus = new InMemoryEventBus();
    const checkpointStore = new InMemoryCheckpointStore();
    const modelProvider = scriptedProvider([
      [{ type: "text_delta", textDelta: "你好！有什么我可以帮你的吗？" }, { type: "message_stop" }],
    ]);
    const engine = new GraphEngine<ChatState>(buildChatAgentGraph(modelProvider, toolRegistry), {
      toolRegistry,
      eventBus,
      checkpointStore,
    });

    const initialState: ChatState = { message: "你好" };
    let checkpoint = engine.start(initialState, { tenantId: "tenant-a", sessionId: "session-3" }, "run-3");
    checkpoint = await engine.run(checkpoint);

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.reply).toBe("你好！有什么我可以帮你的吗？");

    const eventTypes = eventBus.getEvents().map((e) => e.type);
    expect(eventTypes).not.toContain("hitl_interrupt");
  });

  it("returns the partial reply and skips HITL approval when the signal is aborted mid-stream", async () => {
    const toolRegistry = createChatAgentToolRegistry();
    const eventBus = new InMemoryEventBus();
    const checkpointStore = new InMemoryCheckpointStore();
    const controller = new AbortController();
    const modelProvider: ModelProvider = {
      async *complete(_request, options) {
        yield { type: "text_delta", textDelta: "部分回复" };
        controller.abort();
        if (options?.signal?.aborted) return;
        yield { type: "text_delta", textDelta: "，不应该出现" };
        yield { type: "message_stop" };
      },
    };
    const engine = new GraphEngine<ChatState>(buildChatAgentGraph(modelProvider, toolRegistry), {
      toolRegistry,
      eventBus,
      checkpointStore,
    });

    const initialState: ChatState = { message: "你好" };
    const checkpoint = await engine.run(
      engine.start(initialState, { tenantId: "tenant-a", sessionId: "session-1" }, "run-cancel"),
      { signal: controller.signal },
    );

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.reply).toBe("部分回复");
  });

  it("registers load_skill and run_skill_script when skills are provided, and the model can use them in one turn", async () => {
    const fakeSkill: Skill = {
      name: "fake-skill",
      description: "A fake skill for this test.",
      content: "# fake-skill\ninstructions",
      dir: "/tmp/does-not-matter-for-this-test",
    };
    const toolRegistry = createChatAgentToolRegistry({ skills: [fakeSkill] });
    const toolNames = toolRegistry.list().map((t) => t.name);
    expect(toolNames).toContain("load_skill");
    expect(toolNames).toContain("run_skill_script");

    const eventBus = new InMemoryEventBus();
    const checkpointStore = new InMemoryCheckpointStore();
    const modelProvider = scriptedProvider([
      [{ type: "tool_call", toolCall: { id: "call-1", name: "load_skill", input: { name: "fake-skill" } } }],
      [{ type: "text_delta", textDelta: "loaded the fake skill" }, { type: "message_stop" }],
    ]);
    const engine = new GraphEngine<ChatState>(buildChatAgentGraph(modelProvider, toolRegistry), {
      toolRegistry,
      eventBus,
      checkpointStore,
    });
    const initialState: ChatState = { message: "use the fake skill" };
    let checkpoint = engine.start(initialState, { tenantId: "tenant-a", sessionId: "session-skill" }, "run-skill-1");
    checkpoint = await engine.run(checkpoint);
    // load_skill isn't marked `dangerous` (it's a read-only lookup), so it skips the HITL pause
    // entirely — unlike lookup_exchange_rate (see the tests above), which is.
    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.reply).toBe("loaded the fake skill");
  });
});
