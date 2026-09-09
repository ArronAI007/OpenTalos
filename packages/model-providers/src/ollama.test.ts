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
});
