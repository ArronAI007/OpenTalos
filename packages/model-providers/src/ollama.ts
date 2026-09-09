import type { ModelProvider, ModelRequest, ModelResponseChunk } from "@opentalos/core-types";

export interface OllamaFetchResponse {
  ok: boolean;
  status: number;
  body: ReadableStream<Uint8Array> | null;
}

export type OllamaFetchLike = (
  url: string,
  init: { method: string; body: string; headers: Record<string, string> },
) => Promise<OllamaFetchResponse>;

export interface OllamaProviderOptions {
  baseUrl: string;
  model: string;
}

interface OllamaChatLine {
  message?: { content?: string };
  done?: boolean;
}

export function createOllamaProvider(fetchFn: OllamaFetchLike, options: OllamaProviderOptions): ModelProvider {
  return {
    async *complete(request: ModelRequest): AsyncIterable<ModelResponseChunk> {
      const response = await fetchFn(`${options.baseUrl}/api/chat`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          model: options.model,
          messages: request.messages.map((m) => ({ role: m.role, content: m.content })),
          stream: true,
        }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`Ollama request failed with status ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const parsed = JSON.parse(line) as OllamaChatLine;
          if (parsed.message?.content) {
            yield { type: "text_delta", textDelta: parsed.message.content };
          }
          if (parsed.done) {
            yield { type: "message_stop" };
          }
        }
      }
    },
  };
}
