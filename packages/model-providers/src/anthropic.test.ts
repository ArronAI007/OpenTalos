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
});
