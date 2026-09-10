import { describe, expect, it } from "vitest";
import type { ModelRequest } from "@opentalos/core-types";
import { createAnthropicProvider, type AnthropicClientLike } from "./anthropic.js";

function fakeClient(events: unknown[]): AnthropicClientLike {
  return {
    messages: {
      stream() {
        return (async function* () {
          for (const event of events) yield event as never;
        })();
      },
    },
  };
}

function capturingClient(events: unknown[]): { client: AnthropicClientLike; getCapturedParams: () => unknown } {
  let capturedParams: unknown;
  const client: AnthropicClientLike = {
    messages: {
      stream(params) {
        capturedParams = params;
        return (async function* () {
          for (const event of events) yield event as never;
        })();
      },
    },
  };
  return { client, getCapturedParams: () => capturedParams };
}

const request: ModelRequest = { messages: [{ role: "user", content: "hi" }] };

describe("createAnthropicProvider", () => {
  it("yields text_delta chunks from content_block_delta events", async () => {
    const client = fakeClient([
      { type: "content_block_delta", delta: { type: "text_delta", text: "Hello" } },
      { type: "content_block_delta", delta: { type: "text_delta", text: " world" } },
      { type: "message_stop" },
    ]);
    const provider = createAnthropicProvider(client, { model: "claude-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks).toEqual([
      { type: "text_delta", textDelta: "Hello" },
      { type: "text_delta", textDelta: " world" },
      { type: "message_stop" },
    ]);
  });

  it("yields a tool_call chunk from a content_block_start tool_use event", async () => {
    const client = fakeClient([
      { type: "content_block_start", content_block: { type: "tool_use", id: "call-1", name: "search", input: { q: "x" } } },
      { type: "message_stop" },
    ]);
    const provider = createAnthropicProvider(client, { model: "claude-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks[0]).toEqual({ type: "tool_call", toolCall: { id: "call-1", name: "search", input: { q: "x" } } });
  });

  it("extracts the system message and maps tool definitions to input_schema", async () => {
    const requestWithSystemAndTools: ModelRequest = {
      messages: [
        { role: "system", content: "be concise" },
        { role: "user", content: "hi" },
      ],
      tools: [{ name: "search", description: "search the web", inputSchema: { type: "object" } }],
    };
    const { client, getCapturedParams } = capturingClient([{ type: "message_stop" }]);
    const provider = createAnthropicProvider(client, { model: "claude-test" });
    for await (const _chunk of provider.complete(requestWithSystemAndTools)) {
      // draining the iterator to trigger the stream() call
    }
    const params = getCapturedParams() as {
      system?: string;
      tools?: { name: string; description: string; input_schema: unknown }[];
    };
    expect(params.system).toBe("be concise");
    expect(params.tools?.[0]).toEqual({ name: "search", description: "search the web", input_schema: { type: "object" } });
  });

  it("builds tool_use and tool_result content blocks from toolCalls/toolCallId", async () => {
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
    const { client, getCapturedParams } = capturingClient([{ type: "message_stop" }]);
    const provider = createAnthropicProvider(client, { model: "claude-test" });
    for await (const _chunk of provider.complete(requestWithHistory)) {
      // draining the iterator to trigger the stream() call
    }
    const params = getCapturedParams() as {
      messages: { role: string; content: string | unknown[] }[];
    };
    expect(params.messages[1]).toEqual({
      role: "assistant",
      content: [{ type: "tool_use", id: "call-1", name: "lookup_rate", input: { pair: "USD/CNY" } }],
    });
    expect(params.messages[2]).toEqual({
      role: "user",
      content: [{ type: "tool_result", tool_use_id: "call-1", content: "7.13" }],
    });
  });
});
