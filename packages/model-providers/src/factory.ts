import Anthropic from "@anthropic-ai/sdk";
import OpenAI from "openai";
import type { ModelProvider } from "@opentalos/core-types";
import { createAnthropicProvider, type AnthropicClientLike } from "./anthropic.js";
import { createOpenAICompatibleProvider, type OpenAIClientLike } from "./openai-compatible.js";
import { createOllamaProvider } from "./ollama.js";
import { createMockProvider } from "./mock.js";

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
  const client = new OpenAI({ apiKey, baseURL }) as unknown as OpenAIClientLike;
  return createOpenAICompatibleProvider(client, { model });
}
