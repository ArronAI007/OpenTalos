import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createModelProviderFromEnv } from "./factory.js";

const ORIGINAL_ENV = { ...process.env };

describe("createModelProviderFromEnv", () => {
  beforeEach(() => {
    for (const key of ["MODEL_PROVIDER", "MODEL_API_KEY", "MODEL_NAME", "MODEL_BASE_URL"]) {
      delete process.env[key];
    }
  });

  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
  });

  it("throws when MODEL_PROVIDER is unset", () => {
    expect(() => createModelProviderFromEnv()).toThrow(/MODEL_PROVIDER/);
  });

  it("throws when MODEL_PROVIDER is an unrecognized value", () => {
    process.env.MODEL_PROVIDER = "not-a-real-provider";
    process.env.MODEL_NAME = "whatever";
    expect(() => createModelProviderFromEnv()).toThrow(/not-a-real-provider/);
  });

  it("throws when MODEL_NAME is unset for a non-mock provider", () => {
    process.env.MODEL_PROVIDER = "anthropic";
    process.env.MODEL_API_KEY = "test-key";
    expect(() => createModelProviderFromEnv()).toThrow(/MODEL_NAME/);
  });

  it("throws when MODEL_API_KEY is unset for anthropic", () => {
    process.env.MODEL_PROVIDER = "anthropic";
    process.env.MODEL_NAME = "claude-test";
    expect(() => createModelProviderFromEnv()).toThrow(/MODEL_API_KEY/);
  });

  it("constructs a real anthropic provider given a key and model", () => {
    process.env.MODEL_PROVIDER = "anthropic";
    process.env.MODEL_API_KEY = "test-key";
    process.env.MODEL_NAME = "claude-test";
    const provider = createModelProviderFromEnv();
    expect(provider).toHaveProperty("complete");
  });

  it("constructs an openai-compatible provider given a key and model", () => {
    process.env.MODEL_PROVIDER = "openai-compatible";
    process.env.MODEL_API_KEY = "test-key";
    process.env.MODEL_NAME = "gpt-test";
    expect(() => createModelProviderFromEnv()).not.toThrow();
  });

  it("constructs an ollama provider without requiring MODEL_API_KEY, but requires MODEL_BASE_URL", () => {
    process.env.MODEL_PROVIDER = "ollama";
    process.env.MODEL_NAME = "llama-test";
    expect(() => createModelProviderFromEnv()).toThrow(/MODEL_BASE_URL/);
    process.env.MODEL_BASE_URL = "http://localhost:11434";
    expect(() => createModelProviderFromEnv()).not.toThrow();
  });

  it.each(["dashscope", "doubao", "kimi", "minimax"])(
    "constructs a %s provider given a key and model, using its built-in preset base URL",
    (providerName) => {
      process.env.MODEL_PROVIDER = providerName;
      process.env.MODEL_API_KEY = "test-key";
      process.env.MODEL_NAME = "some-model";
      expect(() => createModelProviderFromEnv()).not.toThrow();
    },
  );

  it("returns the deterministic mock provider when MODEL_PROVIDER=mock, requiring neither MODEL_API_KEY nor MODEL_NAME", () => {
    process.env.MODEL_PROVIDER = "mock";
    expect(() => createModelProviderFromEnv()).not.toThrow();
  });

  it("lets MODEL_BASE_URL override a Chinese-provider preset", () => {
    process.env.MODEL_PROVIDER = "kimi";
    process.env.MODEL_API_KEY = "test-key";
    process.env.MODEL_NAME = "moonshot-v1-8k";
    process.env.MODEL_BASE_URL = "https://custom.example.com/v1";
    expect(() => createModelProviderFromEnv()).not.toThrow();
  });

  // Regression test for a real runtime bug: the real `openai` SDK's `create({stream:true})`
  // returns a `Promise` (an `APIPromise`) that is NOT itself async-iterable — only the resolved
  // `Stream` value is, once awaited. `openai-compatible.ts`'s `for await (const chunk of stream)`
  // does not await first, so a naive `new OpenAI(...) as unknown as OpenAIClientLike` cast throws
  // `TypeError: stream is not async iterable` immediately. `createModelProviderFromEnv()` must
  // bridge this by wrapping `create` in an async generator function (see `createRealOpenAIClient`
  // in factory.ts) so the synchronous-AsyncIterable contract is genuinely satisfied.
  //
  // This test mocks the global `fetch` the `openai` SDK calls under the hood with a real
  // SSE-formatted streaming response, so it runs fully offline in CI while still driving the
  // entire real client -> provider pipeline end to end. Without the fix, this test fails with
  // the synchronous iterability TypeError before the mocked `fetch` is even invoked.
  it("streams real text_delta/message_stop chunks through the real OpenAI-SDK-backed client (regression: async-iterable Promise bridging)", async () => {
    process.env.MODEL_PROVIDER = "openai-compatible";
    process.env.MODEL_API_KEY = "test-key";
    process.env.MODEL_NAME = "gpt-test";

    const sseBody =
      'data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":null}]}\n\n' +
      'data: {"choices":[{"delta":{"content":" world"},"finish_reason":"stop"}]}\n\n' +
      "data: [DONE]\n\n";

    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () =>
      new Response(sseBody, {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      })) as typeof fetch;

    try {
      const provider = createModelProviderFromEnv();
      const chunks = [];
      for await (const chunk of provider.complete({ messages: [{ role: "user", content: "hi" }] })) {
        chunks.push(chunk);
      }
      expect(chunks).toEqual([
        { type: "text_delta", textDelta: "Hello" },
        { type: "text_delta", textDelta: " world" },
        { type: "message_stop" },
      ]);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
