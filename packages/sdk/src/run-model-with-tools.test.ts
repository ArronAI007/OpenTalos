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

async function drive(
  gen: AsyncGenerator<NodeYield, AgentTurnResult, NodeResumeValue>,
  toolOutputs: Record<string, unknown>,
): Promise<AgentTurnResult> {
  let next = await gen.next();
  while (!next.done) {
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
});
