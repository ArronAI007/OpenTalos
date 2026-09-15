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

function capturingClientWithOptions(chunks: unknown[]): { client: OpenAIClientLike; getCapturedOptions: () => unknown } {
  let capturedOptions: unknown;
  const client: OpenAIClientLike = {
    chat: {
      completions: {
        create(_params, options) {
          capturedOptions = options;
          return (async function* () {
            for (const chunk of chunks) yield chunk as never;
          })();
        },
      },
    },
  };
  return { client, getCapturedOptions: () => capturedOptions };
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

  it("yields reasoning_delta chunks from delta.reasoning_content, ahead of the matching text_delta", async () => {
    const client = fakeClient([
      { choices: [{ delta: { reasoning_content: "let me think" } }] },
      { choices: [{ delta: { reasoning_content: "..." } }] },
      { choices: [{ delta: { content: "the answer" }, finish_reason: "stop" }] },
    ]);
    const provider = createOpenAICompatibleProvider(client, { model: "gpt-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks).toEqual([
      { type: "reasoning_delta", reasoningDelta: "let me think" },
      { type: "reasoning_delta", reasoningDelta: "..." },
      { type: "text_delta", textDelta: "the answer" },
      { type: "message_stop" },
    ]);
  });

  it("yields both reasoning_delta and text_delta when both fields are present on the same chunk", async () => {
    const client = fakeClient([
      { choices: [{ delta: { reasoning_content: "thinking", content: "answering" }, finish_reason: "stop" }] },
    ]);
    const provider = createOpenAICompatibleProvider(client, { model: "gpt-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks).toEqual([
      { type: "reasoning_delta", reasoningDelta: "thinking" },
      { type: "text_delta", textDelta: "answering" },
      { type: "message_stop" },
    ]);
  });

  it("yields a tool_call chunk once a single-fragment delta.tool_calls completes at finish_reason", async () => {
    const client = fakeClient([
      {
        choices: [
          { delta: { tool_calls: [{ index: 0, id: "call-1", function: { name: "search", arguments: '{"q":"x"}' } }] } },
        ],
      },
      { choices: [{ delta: {}, finish_reason: "tool_calls" }] },
    ]);
    const provider = createOpenAICompatibleProvider(client, { model: "gpt-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks).toEqual([
      { type: "tool_call", toolCall: { id: "call-1", name: "search", input: { q: "x" } } },
      { type: "message_stop" },
    ]);
  });

  it("accumulates a tool call whose id/name/arguments arrive fragmented across multiple chunks, keyed by index", async () => {
    // Regression test: real OpenAI-protocol streaming sends `id`/`function.name` only on a tool
    // call's first fragment and splits `function.arguments` across many fragments (e.g. mid-token,
    // like `{"q` then `":"x` then `"}`). A prior version of this fixture (and the code it was
    // matching) treated each `delta.tool_calls` entry as one complete, standalone call and called
    // `JSON.parse` on each fragment independently — which throws a `SyntaxError` on any fragment
    // after the first, since a partial JSON string like `{"q` is not valid JSON on its own.
    const client = fakeClient([
      { choices: [{ delta: { tool_calls: [{ index: 0, id: "call-1", function: { name: "search", arguments: '{"q' } }] } }] },
      { choices: [{ delta: { tool_calls: [{ index: 0, function: { arguments: '":"x' } }] } }] },
      { choices: [{ delta: { tool_calls: [{ index: 0, function: { arguments: '"}' } }] } }] },
      { choices: [{ delta: {}, finish_reason: "tool_calls" }] },
    ]);
    const provider = createOpenAICompatibleProvider(client, { model: "gpt-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks).toEqual([
      { type: "tool_call", toolCall: { id: "call-1", name: "search", input: { q: "x" } } },
      { type: "message_stop" },
    ]);
  });

  it("keeps two concurrent tool calls' argument fragments separate by index", async () => {
    const client = fakeClient([
      {
        choices: [
          {
            delta: {
              tool_calls: [
                { index: 0, id: "call-1", function: { name: "search", arguments: '{"q":"x"}' } },
                { index: 1, id: "call-2", function: { name: "lookup_rate", arguments: '{"pai' } },
              ],
            },
          },
        ],
      },
      { choices: [{ delta: { tool_calls: [{ index: 1, function: { arguments: 'r":"USD/CNY"}' } }] } }] },
      { choices: [{ delta: {}, finish_reason: "tool_calls" }] },
    ]);
    const provider = createOpenAICompatibleProvider(client, { model: "gpt-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks).toEqual([
      { type: "tool_call", toolCall: { id: "call-1", name: "search", input: { q: "x" } } },
      { type: "tool_call", toolCall: { id: "call-2", name: "lookup_rate", input: { pair: "USD/CNY" } } },
      { type: "message_stop" },
    ]);
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

  it("maps a builtin tool definition to a bare builtin_function declaration, with no description or parameters", async () => {
    const requestWithBuiltinTool: ModelRequest = {
      messages: [{ role: "user", content: "hi" }],
      tools: [
        { name: "$web_search", description: "unused for builtin tools", inputSchema: {}, kind: "builtin" },
        { name: "search", description: "search the web", inputSchema: { type: "object" } },
      ],
    };
    const { client, getCapturedParams } = capturingClient([{ choices: [{ delta: {}, finish_reason: "stop" }] }]);
    const provider = createOpenAICompatibleProvider(client, { model: "gpt-test" });
    for await (const _chunk of provider.complete(requestWithBuiltinTool)) {
      // draining the iterator to trigger the create() call
    }
    const params = getCapturedParams() as { tools?: unknown[] };
    expect(params.tools?.[0]).toEqual({ type: "builtin_function", function: { name: "$web_search" } });
    expect(params.tools?.[1]).toEqual({
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

  it("sends a message's images as image_url content parts alongside its text, per Moonshot's documented vision format", async () => {
    const requestWithImages: ModelRequest = {
      messages: [
        {
          role: "user",
          content: "这张图里有什么？",
          images: ["data:image/png;base64,AAA", "data:image/jpeg;base64,BBB"],
        },
      ],
    };
    const { client, getCapturedParams } = capturingClient([{ choices: [{ delta: {}, finish_reason: "stop" }] }]);
    const provider = createOpenAICompatibleProvider(client, { model: "gpt-test" });
    for await (const _chunk of provider.complete(requestWithImages)) {
      // draining the iterator to trigger the create() call
    }
    const params = getCapturedParams() as { messages: { content: unknown }[] };
    expect(params.messages[0].content).toEqual([
      { type: "image_url", image_url: { url: "data:image/png;base64,AAA" } },
      { type: "image_url", image_url: { url: "data:image/jpeg;base64,BBB" } },
      { type: "text", text: "这张图里有什么？" },
    ]);
  });

  it("sends a message with no images as a plain string, unchanged from before images were supported", async () => {
    const { client, getCapturedParams } = capturingClient([{ choices: [{ delta: {}, finish_reason: "stop" }] }]);
    const provider = createOpenAICompatibleProvider(client, { model: "gpt-test" });
    for await (const _chunk of provider.complete(request)) {
      // draining the iterator to trigger the create() call
    }
    const params = getCapturedParams() as { messages: { content: unknown }[] };
    expect(params.messages[0].content).toBe("hi");
  });

  it("forwards an AbortSignal to the underlying client.chat.completions.create call", async () => {
    const controller = new AbortController();
    const { client, getCapturedOptions } = capturingClientWithOptions([{ choices: [{ delta: {}, finish_reason: "stop" }] }]);
    const provider = createOpenAICompatibleProvider(client, { model: "gpt-test" });
    for await (const _chunk of provider.complete(request, { signal: controller.signal })) {
      // draining the iterator to trigger the create() call
    }
    expect(getCapturedOptions()).toEqual({ signal: controller.signal });
  });
});
