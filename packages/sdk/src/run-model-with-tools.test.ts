import { describe, expect, it } from "vitest";
import type { ModelProvider, ModelResponseChunk, ToolDefinition } from "@opentalos/core-types";
import type { NodeResumeValue, NodeYield, SteerChannel } from "@opentalos/core-graph";
import { runModelWithTools, type AgentTurnResult } from "./run-model-with-tools.js";

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

function alwaysToolCallProvider(): ModelProvider {
  let callIndex = 0;
  return {
    async *complete() {
      callIndex += 1;
      yield { type: "tool_call", toolCall: { id: `call-${callIndex}`, name: "search", input: {} } };
    },
  };
}

async function drive(
  gen: AsyncGenerator<NodeYield, AgentTurnResult, NodeResumeValue>,
  toolOutputs: Record<string, unknown>,
): Promise<AgentTurnResult> {
  let next = await gen.next();
  while (!next.done) {
    // Mirrors GraphEngine.runNodeToCompletion: an "emit" yield never pauses, so a test driver
    // (like the real engine) just auto-continues past it.
    if (next.value.type === "emit") {
      next = await gen.next(undefined);
      continue;
    }
    if (next.value.type !== "awaiting_tool") {
      throw new Error(`Unexpected yield type in test helper: ${next.value.type}`);
    }
    const { toolCall } = next.value;
    next = await gen.next({ type: "tool_result", result: { id: toolCall.id, output: toolOutputs[toolCall.name] } });
  }
  return next.value;
}

const tools: ToolDefinition[] = [{ name: "search", description: "search", inputSchema: { type: "object" } }];

describe("runModelWithTools", () => {
  it("returns immediately when the model replies with no tool calls", async () => {
    const provider = scriptedProvider([[{ type: "text_delta", textDelta: "hello" }, { type: "message_stop" }]]);
    const gen = runModelWithTools(provider, tools, [{ role: "user", content: "hi" }]);
    const result = await drive(gen, {});
    expect(result.finalText).toBe("hello");
    expect(result.messages).toEqual([{ role: "user", content: "hi" }]);
  });

  it("yields awaiting_tool once for a single tool call, then returns the follow-up reply", async () => {
    const provider = scriptedProvider([
      [{ type: "tool_call", toolCall: { id: "call-1", name: "search", input: { q: "x" } } }, { type: "message_stop" }],
      [{ type: "text_delta", textDelta: "found it" }, { type: "message_stop" }],
    ]);
    const gen = runModelWithTools(provider, tools, [{ role: "user", content: "hi" }]);
    const result = await drive(gen, { search: "some result" });
    expect(result.finalText).toBe("found it");
    expect(result.messages).toEqual([
      { role: "user", content: "hi" },
      { role: "assistant", content: "", toolCalls: [{ id: "call-1", name: "search", input: { q: "x" } }] },
      { role: "tool", content: "some result", toolCallId: "call-1" },
    ]);
  });

  it("loops through multiple rounds until the model stops requesting tools", async () => {
    const provider = scriptedProvider([
      [{ type: "tool_call", toolCall: { id: "call-1", name: "search", input: { q: "round 1" } } }],
      [{ type: "tool_call", toolCall: { id: "call-2", name: "search", input: { q: "round 2" } } }],
      [{ type: "text_delta", textDelta: "done after two rounds" }, { type: "message_stop" }],
    ]);
    const gen = runModelWithTools(provider, tools, [{ role: "user", content: "hi" }]);
    const result = await drive(gen, { search: "ok" });
    expect(result.finalText).toBe("done after two rounds");
    expect(result.messages.filter((m) => m.role === "tool")).toHaveLength(2);
  });

  it("handles multiple tool calls requested within a single model turn", async () => {
    const provider = scriptedProvider([
      [
        { type: "tool_call", toolCall: { id: "call-1", name: "search", input: { q: "a" } } },
        { type: "tool_call", toolCall: { id: "call-2", name: "search", input: { q: "b" } } },
      ],
      [{ type: "text_delta", textDelta: "combined answer" }, { type: "message_stop" }],
    ]);
    const gen = runModelWithTools(provider, tools, [{ role: "user", content: "hi" }]);
    const result = await drive(gen, { search: "ok" });
    expect(result.finalText).toBe("combined answer");
    const toolMessages = result.messages.filter((m) => m.role === "tool");
    expect(toolMessages.map((m) => m.toolCallId)).toEqual(["call-1", "call-2"]);
  });

  it("yields llm_call_start, one llm_text_delta per chunk, and llm_call_end around a round with no tool calls", async () => {
    const provider = scriptedProvider([
      [{ type: "text_delta", textDelta: "hel" }, { type: "text_delta", textDelta: "lo" }, { type: "message_stop" }],
    ]);
    const gen = runModelWithTools(provider, tools, [{ role: "user", content: "hi" }]);
    const emitted: NodeYield[] = [];
    let next = await gen.next();
    while (!next.done) {
      if (next.value.type !== "emit") {
        throw new Error(`Unexpected yield type in this test: ${next.value.type}`);
      }
      emitted.push(next.value);
      next = await gen.next(undefined);
    }
    expect(emitted).toEqual([
      { type: "emit", eventType: "llm_call_start" },
      { type: "emit", eventType: "llm_text_delta", payload: { delta: "hel" } },
      { type: "emit", eventType: "llm_text_delta", payload: { delta: "lo" } },
      { type: "emit", eventType: "llm_call_end", payload: { text: "hello", toolCallCount: 0 } },
    ]);
    expect(next.value.finalText).toBe("hello");
  });

  it("accumulates reasoningText across rounds and emits llm_reasoning_delta for each fragment", async () => {
    const provider = scriptedProvider([
      [
        { type: "reasoning_delta", reasoningDelta: "I should search first. " },
        { type: "tool_call", toolCall: { id: "call-1", name: "search", input: { q: "x" } } },
      ],
      [
        { type: "reasoning_delta", reasoningDelta: "Now I can answer." },
        { type: "text_delta", textDelta: "found it" },
        { type: "message_stop" },
      ],
    ]);
    const gen = runModelWithTools(provider, tools, [{ role: "user", content: "hi" }]);
    const emitted: NodeYield[] = [];
    let next = await gen.next();
    while (!next.done) {
      if (next.value.type === "emit") {
        emitted.push(next.value);
        next = await gen.next(undefined);
        continue;
      }
      if (next.value.type !== "awaiting_tool") throw new Error(`Unexpected yield type: ${next.value.type}`);
      const { toolCall } = next.value;
      next = await gen.next({ type: "tool_result", result: { id: toolCall.id, output: "some result" } });
    }
    expect(next.value.reasoningText).toBe("I should search first. Now I can answer.");
    expect(next.value.finalText).toBe("found it");
    expect(emitted).toContainEqual({
      type: "emit",
      eventType: "llm_reasoning_delta",
      payload: { delta: "I should search first. " },
    });
    expect(emitted).toContainEqual({
      type: "emit",
      eventType: "llm_reasoning_delta",
      payload: { delta: "Now I can answer." },
    });
  });

  it("returns an empty reasoningText when the provider never emits reasoning_delta chunks", async () => {
    const provider = scriptedProvider([[{ type: "text_delta", textDelta: "hello" }, { type: "message_stop" }]]);
    const gen = runModelWithTools(provider, tools, [{ role: "user", content: "hi" }]);
    const result = await drive(gen, {});
    expect(result.reasoningText).toBe("");
  });

  it("splices a steering instruction into the conversation and starts a fresh round, without ending the turn", async () => {
    let callIndex = 0;
    const provider: ModelProvider = {
      async *complete() {
        callIndex += 1;
        if (callIndex === 1) {
          // First round: stream some text, then hang forever (simulating an in-progress reply) —
          // this round must never reach message_stop on its own; only the steer interrupt ends it.
          yield { type: "text_delta", textDelta: "快速排序是一种" };
          await new Promise(() => {}); // never resolves
        } else {
          yield { type: "text_delta", textDelta: "好的，用 Python 实现快速排序" };
          yield { type: "message_stop" };
        }
      },
    };
    let deliverSteer: ((message: string) => void) | undefined;
    const steer: SteerChannel = {
      waitForNext: () => new Promise((resolve) => { deliverSteer = resolve; }),
    };

    const gen = runModelWithTools(provider, tools, [{ role: "user", content: "帮我写一个排序算法" }], undefined, undefined, steer);
    // Drive past the first round's llm_call_start + first text_delta, then steer.
    let next = await gen.next();
    while (next.value?.type === "emit" && next.value.eventType !== "llm_text_delta") {
      next = await gen.next(undefined);
    }
    // The first text_delta ("快速排序是一种") has now been emitted. Steer before round 1 ever ends.
    expect(deliverSteer).toBeDefined();
    deliverSteer!("用 Python 写");

    while (!next.done) {
      next = await gen.next(undefined);
    }

    expect(next.value.finalText).toBe("好的，用 Python 实现快速排序");
    const roles = next.value.messages.map((m) => m.role);
    expect(roles).toEqual(["user", "assistant", "user"]);
    expect(next.value.messages[1]).toEqual({ role: "assistant", content: "快速排序是一种" });
    expect(next.value.messages[2]).toEqual({
      role: "user",
      content: "（用户在你刚才的回答过程中补充了新的指示，请据此调整）：用 Python 写",
    });
  });

  it("a real cancel (signal) still ends the turn exactly as before, even when a steer channel is also provided but never used", async () => {
    const controller = new AbortController();
    const provider: ModelProvider = {
      async *complete(_request, options) {
        yield { type: "text_delta", textDelta: "par" };
        controller.abort();
        if (options?.signal?.aborted) return;
        yield { type: "text_delta", textDelta: "tial" };
      },
    };
    const neverSteers: SteerChannel = { waitForNext: () => new Promise(() => {}) };
    const gen = runModelWithTools(
      provider,
      tools,
      [{ role: "user", content: "hi" }],
      undefined,
      controller.signal,
      neverSteers,
    );
    let next = await gen.next();
    while (!next.done) {
      if (next.value.type !== "emit") throw new Error(`Unexpected yield type: ${next.value.type}`);
      next = await gen.next(undefined);
    }
    expect(next.value.finalText).toBe("par");
  });

  it("throws once maxRounds is exceeded when the model never stops requesting tools", async () => {
    const provider = alwaysToolCallProvider();
    const gen = runModelWithTools(provider, tools, [{ role: "user", content: "hi" }], 3);
    await expect(drive(gen, { search: "ok" })).rejects.toThrow(
      "runModelWithTools: exceeded maxRounds (3) without the model producing a turn with no tool calls — the model may be stuck in a repetitive tool-calling loop",
    );
  });

  it("defaults maxRounds to 10, succeeding when the model stops exactly on the 10th round", async () => {
    const responses: ModelResponseChunk[][] = [];
    for (let round = 1; round <= 9; round += 1) {
      responses.push([{ type: "tool_call", toolCall: { id: `call-${round}`, name: "search", input: { round } } }]);
    }
    responses.push([{ type: "text_delta", textDelta: "done on round 10" }, { type: "message_stop" }]);
    const provider = scriptedProvider(responses);

    // maxRounds intentionally omitted — this test pins the default at (at least) 10 rounds.
    const gen = runModelWithTools(provider, tools, [{ role: "user", content: "hi" }]);
    const result = await drive(gen, { search: "ok" });

    expect(result.finalText).toBe("done on round 10");
    expect(result.messages.filter((m) => m.role === "tool")).toHaveLength(9);
  });

  it("returns the partial text streamed so far when the signal aborts mid-stream, instead of throwing", async () => {
    const controller = new AbortController();
    const provider: ModelProvider = {
      async *complete(_request, options) {
        yield { type: "text_delta", textDelta: "hel" };
        controller.abort();
        if (options?.signal?.aborted) return; // simulates the underlying HTTP call stopping here
        yield { type: "text_delta", textDelta: "lo world" };
        yield { type: "message_stop" };
      },
    };
    const gen = runModelWithTools(provider, tools, [{ role: "user", content: "hi" }], undefined, controller.signal);
    let next = await gen.next();
    while (!next.done) {
      if (next.value.type !== "emit") throw new Error(`Unexpected yield type in this test: ${next.value.type}`);
      next = await gen.next(undefined);
    }
    expect(next.value.finalText).toBe("hel");
  });

  it("returns a placeholder when the signal aborts before any text streamed at all", async () => {
    const controller = new AbortController();
    controller.abort();
    const provider: ModelProvider = {
      async *complete(_request, options) {
        if (options?.signal?.aborted) return;
        yield { type: "text_delta", textDelta: "unreachable" };
        yield { type: "message_stop" };
      },
    };
    const gen = runModelWithTools(provider, tools, [{ role: "user", content: "hi" }], undefined, controller.signal);
    let next = await gen.next();
    while (!next.done) {
      next = await gen.next(undefined);
    }
    expect(next.value.finalText).toBe("（已停止，无内容）");
  });

  it("returns the partial text streamed so far even when the provider THROWS on abort (the real anthropic/openai-compatible/ollama behavior, unlike the two mock-style providers above)", async () => {
    const controller = new AbortController();
    const provider: ModelProvider = {
      async *complete(_request, options) {
        yield { type: "text_delta", textDelta: "par" };
        controller.abort();
        yield { type: "text_delta", textDelta: "tial" };
        // A real fetch()/SDK call rejects with an AbortError once its signal fires — simulate that
        // directly rather than only the mock provider's cooperative early-return style.
        const error = new Error("The operation was aborted");
        error.name = "AbortError";
        throw error;
      },
    };
    const gen = runModelWithTools(provider, tools, [{ role: "user", content: "hi" }], undefined, controller.signal);
    let next = await gen.next();
    while (!next.done) {
      if (next.value.type !== "emit") throw new Error(`Unexpected yield type in this test: ${next.value.type}`);
      next = await gen.next(undefined);
    }
    expect(next.value.finalText).toBe("partial");
  });

  it("re-throws a non-abort error instead of swallowing it", async () => {
    const provider: ModelProvider = {
      async *complete() {
        yield { type: "text_delta", textDelta: "x" };
        throw new Error("a real network failure, unrelated to any signal");
      },
    };
    const gen = runModelWithTools(provider, tools, [{ role: "user", content: "hi" }]);
    let next = await gen.next();
    await expect(
      (async () => {
        while (!next.done) next = await gen.next(undefined);
      })(),
    ).rejects.toThrow("a real network failure");
  });
});
