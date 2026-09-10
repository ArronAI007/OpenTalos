import Anthropic from "@anthropic-ai/sdk";
import OpenAI from "openai";
import type { ChatCompletionCreateParamsStreaming } from "openai/resources/chat/completions";
import type { ModelProvider } from "@opentalos/core-types";
import { createAnthropicProvider, type AnthropicClientLike } from "./anthropic.js";
import {
  createOpenAICompatibleProvider,
  type OpenAIClientLike,
  type OpenAIStreamChunk,
} from "./openai-compatible.js";
import { createOllamaProvider } from "./ollama.js";
import { createMockProvider } from "./mock.js";

/**
 * Bridges the real `openai` SDK into `OpenAIClientLike`, whose `create()` is declared to return
 * `AsyncIterable<OpenAIStreamChunk>` *synchronously* (no `Promise` wrapper) — matching
 * openai-compatible.ts's `for await (const chunk of stream)` call site, which does not await the
 * return value first.
 *
 * The real SDK does NOT match that contract: `client.chat.completions.create({stream:true})`
 * returns `APIPromise<Stream<ChatCompletionChunk>>`, a `Promise` subclass that only becomes
 * iterable once awaited. Casting the raw `OpenAI` instance to `OpenAIClientLike` (as the previous
 * code did) satisfies the type checker but not the runtime: `for await` in openai-compatible.ts
 * would throw `TypeError: stream is not async iterable` immediately, before any request is sent.
 *
 * An `async function*` fixes this for real, not just at the type level: calling an async
 * generator function returns its `AsyncGenerator` immediately and synchronously (never a
 * `Promise`), so `create(...)` genuinely satisfies the synchronous-return contract. The `await` on
 * the real SDK's promise only happens lazily, inside the generator body, the first time something
 * iterates the result.
 */
function createRealOpenAIClient(apiKey: string, baseURL: string | undefined): OpenAIClientLike {
  const client = new OpenAI({ apiKey, baseURL });
  return {
    chat: {
      completions: {
        async *create(params) {
          // `params` is typed against our minimal `OpenAIClientLike` contract (see
          // openai-compatible.ts), which is structurally compatible with — but not the same
          // nominal type as — the real SDK's much richer `ChatCompletionCreateParamsStreaming`
          // (e.g. `role` is a plain `string` here vs. a literal union there). This cast is the
          // deliberate boundary between the two; it does not paper over the actual runtime bug
          // this function exists to fix.
          const stream = await client.chat.completions.create(
            params as unknown as ChatCompletionCreateParamsStreaming,
          );
          for await (const chunk of stream) {
            yield chunk as unknown as OpenAIStreamChunk;
          }
        },
      },
    },
  };
}

const CHINESE_PROVIDER_PRESET_BASE_URLS: Record<string, string> = {
  dashscope: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  doubao: "https://ark.cn-beijing.volces.com/api/v3",
  kimi: "https://api.moonshot.cn/v1",
  minimax: "https://api.minimax.chat/v1",
};

const KNOWN_PROVIDERS = ["anthropic", "openai-compatible", "ollama", "mock", ...Object.keys(CHINESE_PROVIDER_PRESET_BASE_URLS)];

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} environment variable is required for the selected MODEL_PROVIDER`);
  }
  return value;
}

/** Builds the ModelProvider this deployment uses, from environment variables. Fails fast (throws)
 * on missing/invalid configuration rather than silently falling back — mirrors the ADMIN_API_KEY
 * pattern in apps/api: running with a misconfigured or absent model provider is a real deployment
 * error, not something to paper over with a default. */
export function createModelProviderFromEnv(): ModelProvider {
  const providerName = requireEnv("MODEL_PROVIDER");
  if (!KNOWN_PROVIDERS.includes(providerName)) {
    throw new Error(`Unknown MODEL_PROVIDER "${providerName}" — expected one of: ${KNOWN_PROVIDERS.join(", ")}`);
  }

  if (providerName === "mock") {
    return createMockProvider();
  }

  const model = requireEnv("MODEL_NAME");

  if (providerName === "anthropic") {
    const apiKey = requireEnv("MODEL_API_KEY");
    const client = new Anthropic({ apiKey, baseURL: process.env.MODEL_BASE_URL }) as unknown as AnthropicClientLike;
    return createAnthropicProvider(client, { model });
  }

  if (providerName === "ollama") {
    const baseUrl = requireEnv("MODEL_BASE_URL");
    return createOllamaProvider(fetch, { baseUrl, model });
  }

  // "openai-compatible" and every Chinese-provider preset all route through the same real
  // OpenAI-SDK-backed client, differing only in which base URL they default to.
  const apiKey = requireEnv("MODEL_API_KEY");
  const baseURL = process.env.MODEL_BASE_URL ?? CHINESE_PROVIDER_PRESET_BASE_URLS[providerName];
  const client = createRealOpenAIClient(apiKey, baseURL);
  return createOpenAICompatibleProvider(client, { model });
}
