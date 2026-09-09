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
});
