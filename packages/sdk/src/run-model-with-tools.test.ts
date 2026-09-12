import { describe, expect, it } from "vitest";
import type { ModelProvider, ModelResponseChunk, ToolDefinition } from "@opentalos/core-types";
import type { NodeResumeValue, NodeYield } from "@opentalos/core-graph";
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
      { type: "emit", eventType: "llm_call_end" },
    ]);
    expect(next.value.finalText).toBe("hello");
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
});
