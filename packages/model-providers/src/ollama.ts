import type { JSONSchema, ModelProvider, ModelRequest, ModelResponseChunk } from "@opentalos/core-types";

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
  message?: { content?: string; tool_calls?: { id: string; function: { name: string; arguments: string } }[] };
  done?: boolean;
}

function parseLine(line: string): ModelResponseChunk[] {
  const parsed = JSON.parse(line) as OllamaChatLine;
  const chunks: ModelResponseChunk[] = [];
  if (parsed.message?.content) {
    chunks.push({ type: "text_delta", textDelta: parsed.message.content });
  }
  for (const call of parsed.message?.tool_calls ?? []) {
    chunks.push({
      type: "tool_call",
      toolCall: { id: call.id, name: call.function.name, input: JSON.parse(call.function.arguments || "{}") },
    });
  }
  if (parsed.done) {
    chunks.push({ type: "message_stop" });
  }
  return chunks;
}

export function createOllamaProvider(fetchFn: OllamaFetchLike, options: OllamaProviderOptions): ModelProvider {
  return {
    async *complete(request: ModelRequest): AsyncIterable<ModelResponseChunk> {
      const tools: { type: "function"; function: { name: string; description: string; parameters: JSONSchema } }[] | undefined =
        request.tools?.map((t) => ({
          type: "function",
          function: { name: t.name, description: t.description, parameters: t.inputSchema },
        }));

      const response = await fetchFn(`${options.baseUrl}/api/chat`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          model: options.model,
          messages: request.messages.map((m) => ({ role: m.role, content: m.content })),
          ...(tools ? { tools } : {}),
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
          for (const chunk of parseLine(line)) yield chunk;
        }
      }
      if (buffer.trim()) {
        for (const chunk of parseLine(buffer)) yield chunk;
      }
    },
  };
}
