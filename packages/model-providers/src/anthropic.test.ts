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

  it("accumulates input_json_delta fragments across a tool_use block and yields one tool_call on content_block_stop", async () => {
    // Regression test: the real Anthropic streaming API sends a tool_use block's `input` as `{}`
    // on content_block_start, then streams the actual JSON as `input_json_delta` `partial_json`
    // fragments (often split mid-token) across one or more content_block_delta events, closing
    // with content_block_stop. A prior version of this fixture (and the code it was matching)
    // incorrectly assumed the full `input` object arrived synchronously on content_block_start,
    // which would silently produce `input: {}` for every real Anthropic tool call.
    const client = fakeClient([
      { type: "content_block_start", index: 0, content_block: { type: "tool_use", id: "call-1", name: "search", input: {} } },
      { type: "content_block_delta", index: 0, delta: { type: "input_json_delta", partial_json: '{"q":' } },
      { type: "content_block_delta", index: 0, delta: { type: "input_json_delta", partial_json: '"x"}' } },
      { type: "content_block_stop", index: 0 },
      { type: "message_stop" },
    ]);
    const provider = createAnthropicProvider(client, { model: "claude-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks).toEqual([
      { type: "tool_call", toolCall: { id: "call-1", name: "search", input: { q: "x" } } },
      { type: "message_stop" },
    ]);
  });

  it("interleaves a text block and a tool_use block by index without cross-contaminating them", async () => {
    const client = fakeClient([
      { type: "content_block_start", index: 0, content_block: { type: "text" } },
      { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: "Let me check. " } },
      { type: "content_block_stop", index: 0 },
      { type: "content_block_start", index: 1, content_block: { type: "tool_use", id: "call-1", name: "search", input: {} } },
      { type: "content_block_delta", index: 1, delta: { type: "input_json_delta", partial_json: '{"q":"x"}' } },
      { type: "content_block_stop", index: 1 },
      { type: "message_stop" },
    ]);
    const provider = createAnthropicProvider(client, { model: "claude-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks).toEqual([
      { type: "text_delta", textDelta: "Let me check. " },
      { type: "tool_call", toolCall: { id: "call-1", name: "search", input: { q: "x" } } },
      { type: "message_stop" },
    ]);
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
