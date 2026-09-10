import { describe, expect, it } from "vitest";
import type { ModelRequest } from "@opentalos/core-types";
import { createOpenAICompatibleProvider, type OpenAIClientLike } from "./openai-compatible.js";

function fakeClient(chunks: unknown[]): OpenAIClientLike {
  return {
    chat: {
      completions: {
        create() {
          return (async function* () {
            for (const chunk of chunks) yield chunk as never;
          })();
        },
      },
    },
  };
}

function capturingClient(chunks: unknown[]): { client: OpenAIClientLike; getCapturedParams: () => unknown } {
  let capturedParams: unknown;
  const client: OpenAIClientLike = {
    chat: {
      completions: {
        create(params) {
          capturedParams = params;
          return (async function* () {
            for (const chunk of chunks) yield chunk as never;
          })();
        },
      },
    },
  };
  return { client, getCapturedParams: () => capturedParams };
}

const request: ModelRequest = { messages: [{ role: "user", content: "hi" }] };

describe("createOpenAICompatibleProvider", () => {
  it("yields text_delta chunks from delta.content", async () => {
    const client = fakeClient([
      { choices: [{ delta: { content: "Hello" } }] },
      { choices: [{ delta: { content: " world" }, finish_reason: "stop" }] },
    ]);
    const provider = createOpenAICompatibleProvider(client, { model: "gpt-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks).toEqual([
      { type: "text_delta", textDelta: "Hello" },
      { type: "text_delta", textDelta: " world" },
      { type: "message_stop" },
    ]);
  });

  it("yields tool_call chunks from delta.tool_calls", async () => {
    const client = fakeClient([
      { choices: [{ delta: { tool_calls: [{ id: "call-1", function: { name: "search", arguments: '{"q":"x"}' } }] } }] },
    ]);
    const provider = createOpenAICompatibleProvider(client, { model: "gpt-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks).toEqual([{ type: "tool_call", toolCall: { id: "call-1", name: "search", input: { q: "x" } } }]);
  });

  it("maps tool definitions to function.parameters matching inputSchema", async () => {
    const requestWithTools: ModelRequest = {
      messages: [{ role: "user", content: "hi" }],
      tools: [{ name: "search", description: "search the web", inputSchema: { type: "object" } }],
    };
    const { client, getCapturedParams } = capturingClient([{ choices: [{ delta: {}, finish_reason: "stop" }] }]);
    const provider = createOpenAICompatibleProvider(client, { model: "gpt-test" });
    for await (const _chunk of provider.complete(requestWithTools)) {
      // draining the iterator to trigger the create() call
    }
    const params = getCapturedParams() as {
      tools?: { type: "function"; function: { name: string; description: string; parameters: unknown } }[];
    };
    expect(params.tools?.[0]).toEqual({
      type: "function",
      function: { name: "search", description: "search the web", parameters: { type: "object" } },
    });
  });

  it("sends tool_calls on an assistant message and tool_call_id on a tool message", async () => {
    const requestWithHistory: ModelRequest = {
      messages: [
        { role: "user", content: "what's the rate?" },
        {
          role: "assistant",
          content: "",
          toolCalls: [{ id: "call-1", name: "lookup_rate", input: { pair: "USD/CNY" } }],
        },
        { role: "tool", content: "7.13", toolCallId: "call-1" },
      ],
    };
    const { client, getCapturedParams } = capturingClient([{ choices: [{ delta: {}, finish_reason: "stop" }] }]);
    const provider = createOpenAICompatibleProvider(client, { model: "gpt-test" });
    for await (const _chunk of provider.complete(requestWithHistory)) {
      // draining the iterator to trigger the create() call
    }
    const params = getCapturedParams() as {
      messages: { role: string; content: string; tool_calls?: unknown; tool_call_id?: string }[];
    };
    expect(params.messages[1]).toEqual({
      role: "assistant",
      content: "",
      tool_calls: [{ id: "call-1", type: "function", function: { name: "lookup_rate", arguments: JSON.stringify({ pair: "USD/CNY" }) } }],
    });
    expect(params.messages[2]).toEqual({ role: "tool", content: "7.13", tool_call_id: "call-1" });
  });
});
