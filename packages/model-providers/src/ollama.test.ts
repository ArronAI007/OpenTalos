import { describe, expect, it } from "vitest";
import type { ModelRequest } from "@opentalos/core-types";
import { createOllamaProvider, type OllamaFetchLike } from "./ollama.js";

function streamFromLines(lines: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const line of lines) controller.enqueue(encoder.encode(line + "\n"));
      controller.close();
    },
  });
}

function streamFromLinesNoTrailingNewline(lines: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(lines.join("\n")));
      controller.close();
    },
  });
}

const request: ModelRequest = { messages: [{ role: "user", content: "hi" }] };

describe("createOllamaProvider", () => {
  it("parses newline-delimited JSON chunks into text_delta and message_stop", async () => {
    const fetchFn: OllamaFetchLike = async () => ({
      ok: true,
      status: 200,
      body: streamFromLines([
        JSON.stringify({ message: { content: "Hello" } }),
        JSON.stringify({ message: { content: " world" } }),
        JSON.stringify({ done: true }),
      ]),
    });
    const provider = createOllamaProvider(fetchFn, { baseUrl: "http://localhost:11434", model: "llama-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks).toEqual([
      { type: "text_delta", textDelta: "Hello" },
      { type: "text_delta", textDelta: " world" },
      { type: "message_stop" },
    ]);
  });

  it("throws when the response is not ok", async () => {
    const fetchFn: OllamaFetchLike = async () => ({ ok: false, status: 500, body: null });
    const provider = createOllamaProvider(fetchFn, { baseUrl: "http://localhost:11434", model: "llama-test" });
    await expect(async () => {
      for await (const _chunk of provider.complete(request)) {
        // draining the iterator to trigger the throw
      }
    }).rejects.toThrow(/status 500/);
  });

  it("flushes a trailing NDJSON line that has no terminating newline", async () => {
    const fetchFn: OllamaFetchLike = async () => ({
      ok: true,
      status: 200,
      body: streamFromLinesNoTrailingNewline([
        JSON.stringify({ message: { content: "Hello" } }),
        JSON.stringify({ message: { content: " world" }, done: true }),
      ]),
    });
    const provider = createOllamaProvider(fetchFn, { baseUrl: "http://localhost:11434", model: "llama-test" });
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks).toEqual([
      { type: "text_delta", textDelta: "Hello" },
      { type: "text_delta", textDelta: " world" },
      { type: "message_stop" },
    ]);
  });

  it("sends the expected request URL and body shape", async () => {
    let capturedUrl: string | undefined;
    let capturedInit: { method: string; body: string; headers: Record<string, string> } | undefined;
    const fetchFn: OllamaFetchLike = async (url, init) => {
      capturedUrl = url;
      capturedInit = init;
      return { ok: true, status: 200, body: streamFromLines([JSON.stringify({ done: true })]) };
    };
    const provider = createOllamaProvider(fetchFn, { baseUrl: "http://localhost:11434", model: "llama-test" });
    for await (const _chunk of provider.complete(request)) {
      // draining the iterator to trigger the fetch call
    }
    expect(capturedUrl).toBe("http://localhost:11434/api/chat");
    const body = JSON.parse(capturedInit?.body ?? "{}");
    expect(body).toMatchObject({
      model: "llama-test",
      messages: [{ role: "user", content: "hi" }],
      stream: true,
    });
  });

  it("sends tools in the request body and parses tool_calls out of a response line matching Ollama's real shape (no id, object arguments)", async () => {
    // Regression test: Ollama's actual `/api/chat` response (confirmed against
    // github.com/ollama/ollama/docs/api.md) sends tool_calls with NO `id` field and
    // `function.arguments` as a plain JSON *object*, not a JSON-encoded string. A prior version
    // of this fixture (and the code it was matching) incorrectly assumed an OpenAI-shaped
    // `{ id, function: { arguments: "<json string>" } }`, which crashes `JSON.parse` on a real
    // Ollama server the first time a tool-calling model actually responds.
    let capturedInit: { method: string; body: string; headers: Record<string, string> } | undefined;
    const fetchFn: OllamaFetchLike = async (_url, init) => {
      capturedInit = init;
      return {
        ok: true,
        status: 200,
        body: streamFromLines([
          JSON.stringify({ message: { tool_calls: [{ function: { name: "search", arguments: { q: "x" } } }] } }),
          JSON.stringify({ done: true }),
        ]),
      };
    };
    const requestWithTools: ModelRequest = {
      messages: [{ role: "user", content: "hi" }],
      tools: [{ name: "search", description: "search the web", inputSchema: { type: "object" } }],
    };
    const provider = createOllamaProvider(fetchFn, { baseUrl: "http://localhost:11434", model: "llama-test" });
    const chunks = [];
    for await (const chunk of provider.complete(requestWithTools)) chunks.push(chunk);

    const sentBody = JSON.parse(capturedInit?.body ?? "{}");
    expect(sentBody.tools).toEqual([
      { type: "function", function: { name: "search", description: "search the web", parameters: { type: "object" } } },
    ]);
    expect(chunks).toHaveLength(2);
    expect(chunks[0]).toMatchObject({ type: "tool_call", toolCall: { name: "search", input: { q: "x" } } });
    // No id was in the response — the adapter must synthesize a non-empty one rather than pass
    // through `undefined` (which would break downstream tool-result correlation).
    expect((chunks[0] as { toolCall: { id: string } }).toolCall.id).toEqual(expect.any(String));
    expect((chunks[0] as { toolCall: { id: string } }).toolCall.id.length).toBeGreaterThan(0);
    expect(chunks[1]).toEqual({ type: "message_stop" });
  });

  it("also accepts a JSON-string-encoded arguments field and a present id, defensively", async () => {
    const fetchFn: OllamaFetchLike = async () => ({
      ok: true,
      status: 200,
      body: streamFromLines([
        JSON.stringify({ message: { tool_calls: [{ id: "call-1", function: { name: "search", arguments: '{"q":"x"}' } }] } }),
        JSON.stringify({ done: true }),
      ]),
    });
    const provider = createOllamaProvider(fetchFn, { baseUrl: "http://localhost:11434", model: "llama-test" });
    const chunks = [];
    for await (const chunk of provider.complete({ messages: [{ role: "user", content: "hi" }] })) chunks.push(chunk);
    expect(chunks).toEqual([
      { type: "tool_call", toolCall: { id: "call-1", name: "search", input: { q: "x" } } },
      { type: "message_stop" },
    ]);
  });

  it("sends tool_calls on an assistant message and tool_name on a tool message", async () => {
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
    let capturedInit: { method: string; body: string; headers: Record<string, string> } | undefined;
    const fetchFn: OllamaFetchLike = async (_url, init) => {
      capturedInit = init;
      return { ok: true, status: 200, body: streamFromLines([JSON.stringify({ done: true })]) };
    };
    const provider = createOllamaProvider(fetchFn, { baseUrl: "http://localhost:11434", model: "llama-test" });
    for await (const _chunk of provider.complete(requestWithHistory)) {
      // draining the iterator to trigger the fetch call
    }

    const sentBody = JSON.parse(capturedInit?.body ?? "{}") as {
      messages: { role: string; content: string; tool_calls?: unknown; tool_name?: string }[];
    };
    expect(sentBody.messages[1]).toEqual({
      role: "assistant",
      content: "",
      tool_calls: [{ type: "function", function: { name: "lookup_rate", arguments: { pair: "USD/CNY" } } }],
    });
    expect(sentBody.messages[2]).toEqual({ role: "tool", content: "7.13", tool_name: "lookup_rate" });
  });
});
