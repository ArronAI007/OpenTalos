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
});
