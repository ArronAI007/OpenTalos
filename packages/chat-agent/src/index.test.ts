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

  it("carries the model's reasoning text through to the checkpoint state, regardless of the approval gate", async () => {
    const toolRegistry = createChatAgentToolRegistry();
    const eventBus = new InMemoryEventBus();
    const checkpointStore = new InMemoryCheckpointStore();
    const modelProvider = scriptedProvider([
      [
        { type: "reasoning_delta", reasoningDelta: "用户在问候，我直接回复就好。" },
        { type: "text_delta", textDelta: "你好！" },
        { type: "message_stop" },
      ],
    ]);
    const engine = new GraphEngine<ChatState>(buildChatAgentGraph(modelProvider, toolRegistry), {
      toolRegistry,
      eventBus,
      checkpointStore,
    });

    const initialState: ChatState = { message: "你好" };
    let checkpoint = engine.start(initialState, { tenantId: "tenant-a", sessionId: "session-reasoning" }, "run-reasoning-1");
    checkpoint = await engine.run(checkpoint);

    // No tool was called (lookup_exchange_rate isn't relevant here), so this skips the approval
    // pause entirely — reasoningText must still be present on the final state either way.
    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.reply).toBe("你好！");
    expect(checkpoint.state.reasoningText).toBe("用户在问候，我直接回复就好。");

    const eventTypes = eventBus.getEvents().map((e) => e.type);
    expect(eventTypes).toContain("llm_reasoning_delta");
  });

  it("forwards ctx.steer through to the model provider, letting a mid-reply steer redirect the final answer", async () => {
    const toolRegistry = createChatAgentToolRegistry();
    const eventBus = new InMemoryEventBus();
    const checkpointStore = new InMemoryCheckpointStore();
    let callIndex = 0;
    const modelProvider: ModelProvider = {
      async *complete() {
        callIndex += 1;
        if (callIndex === 1) {
          yield { type: "text_delta", textDelta: "快速排序是一种" };
          await new Promise(() => {});
        } else {
          yield { type: "text_delta", textDelta: "好的，用 Python 实现" };
          yield { type: "message_stop" };
        }
      },
    };
    const engine = new GraphEngine<ChatState>(buildChatAgentGraph(modelProvider, toolRegistry), {
      toolRegistry,
      eventBus,
      checkpointStore,
    });

    let deliverSteer: ((message: string) => void) | undefined;
    const steer = { waitForNext: () => new Promise<string>((resolve) => { deliverSteer = resolve; }) };

    const initialState: ChatState = { message: "帮我写一个排序算法" };
    const runPromise = engine.run(engine.start(initialState, { tenantId: "tenant-a", sessionId: "session-steer" }, "run-steer-1"), {
      steer,
    });
    // Give the respond node a tick to start streaming and begin racing ctx.steer.waitForNext().
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(deliverSteer).toBeDefined();
    deliverSteer!("用 Python 写");

    const checkpoint = await runPromise;
    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.reply).toBe("好的，用 Python 实现");
  });

  it("forwards the user's image attachments to the model provider on the initial user message", async () => {
    const toolRegistry = createChatAgentToolRegistry();
    const eventBus = new InMemoryEventBus();
    const checkpointStore = new InMemoryCheckpointStore();
    let capturedMessages: unknown;
    const modelProvider: ModelProvider = {
      async *complete(request) {
        capturedMessages = request.messages;
        yield { type: "text_delta", textDelta: "这是一只猫。" };
        yield { type: "message_stop" };
      },
    };
    const engine = new GraphEngine<ChatState>(buildChatAgentGraph(modelProvider, toolRegistry), {
      toolRegistry,
      eventBus,
      checkpointStore,
    });

    const initialState: ChatState = { message: "这张图里有什么？", images: ["data:image/png;base64,AAA"] };
    const checkpoint = await engine.run(
      engine.start(initialState, { tenantId: "tenant-a", sessionId: "session-images" }, "run-images-1"),
    );

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.reply).toBe("这是一只猫。");
    expect(capturedMessages).toContainEqual({
      role: "user",
      content: "这张图里有什么？\n\n（提醒：你接下来的思考过程和回复都必须全程使用中文。）",
      images: ["data:image/png;base64,AAA"],
    });
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

  it("injects a compact memory summary into the system prompt when listMemories is provided", async () => {
    const toolRegistry = createChatAgentToolRegistry();
    const eventBus = new InMemoryEventBus();
    const checkpointStore = new InMemoryCheckpointStore();
    let capturedSystemPrompt: string | undefined;
    const modelProvider: ModelProvider = {
      async *complete(request) {
        capturedSystemPrompt = request.messages.find((m) => m.role === "system")?.content;
        yield { type: "text_delta", textDelta: "好的" };
        yield { type: "message_stop" };
      },
    };
    const listMemories = async (tenantId: string) => {
      expect(tenantId).toBe("tenant-memory");
      return [{ type: "preference", title: "回复偏好简洁" }];
    };
    const engine = new GraphEngine<ChatState>(buildChatAgentGraph(modelProvider, toolRegistry, listMemories), {
      toolRegistry,
      eventBus,
      checkpointStore,
    });

    const initialState: ChatState = { message: "你好" };
    const checkpoint = await engine.run(
      engine.start(initialState, { tenantId: "tenant-memory", sessionId: "session-memory" }, "run-memory-1"),
    );

    expect(checkpoint.status).toBe("done");
    expect(capturedSystemPrompt).toContain("[preference] 回复偏好简洁");
    expect(capturedSystemPrompt).toContain("可能已过时");
  });

  it("injects no memory summary section when listMemories is omitted (existing callers unaffected)", async () => {
    const toolRegistry = createChatAgentToolRegistry();
    const eventBus = new InMemoryEventBus();
    const checkpointStore = new InMemoryCheckpointStore();
    let capturedSystemPrompt: string | undefined;
    const modelProvider: ModelProvider = {
      async *complete(request) {
        capturedSystemPrompt = request.messages.find((m) => m.role === "system")?.content;
        yield { type: "text_delta", textDelta: "好的" };
        yield { type: "message_stop" };
      },
    };
    const engine = new GraphEngine<ChatState>(buildChatAgentGraph(modelProvider, toolRegistry), {
      toolRegistry,
      eventBus,
      checkpointStore,
    });

    const initialState: ChatState = { message: "你好" };
    await engine.run(engine.start(initialState, { tenantId: "tenant-no-memory", sessionId: "s1" }, "run-no-memory-1"));

    expect(capturedSystemPrompt).not.toContain("[已知用户信息]");
  });
});
