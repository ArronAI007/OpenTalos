import type { JSONSchema, Message, ModelProvider, ModelRequest, ModelResponseChunk } from "@opentalos/core-types";

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
  message?: {
    content?: string;
    // Verified against current Ollama docs (docs.ollama.com/capabilities/tool-calling,
    // github.com/ollama/ollama/docs/api.md) as of this writing: a real `/api/chat` response's
    // `tool_calls` entries have NO `id` field (see the OllamaOutMessage-building comment above —
    // same open upstream gap, ollama/ollama#11417) and `function.arguments` is a plain JSON
    // *object*, not a JSON-encoded string (unlike OpenAI's wire format, which this shape
    // otherwise mirrors). Both fields are typed optional/union here — rather than assumed present
    // in OpenAI's shape — so parseLine below can handle the real response without throwing.
    tool_calls?: { id?: string; function: { name: string; arguments: string | Record<string, unknown> } }[];
  };
  done?: boolean;
}

interface OllamaOutMessage {
  role: string;
  content: string;
  tool_calls?: { type: "function"; function: { name: string; arguments: unknown } }[];
  tool_name?: string;
}

/**
 * Ollama's `/api/chat` schema has no opaque tool-call id, unlike OpenAI/Anthropic. Verified
 * against current Ollama documentation (docs.ollama.com/capabilities/tool-calling and
 * github.com/ollama/ollama/docs/api.md) as of this writing:
 *   - An assistant history message with prior tool calls carries
 *     `tool_calls: [{ type: "function", function: { name, arguments } }]` — no `id` field.
 *     (There is an open, unresolved upstream feature request — ollama/ollama#11417 — asking
 *     Ollama to add OpenAI-style call ids; until that lands, there is nothing to send.)
 *   - A tool-result history message correlates back to the call it answers by function name:
 *     `{ role: "tool", content, tool_name: "<function name>" }`.
 * Confidence is high for the shapes above (directly quoted from current docs), but Ollama's
 * tool-calling support is young and still evolving, so if a future Ollama version adds an `id`
 * field to `tool_calls` and/or starts accepting it on `role: "tool"` messages, this mapping
 * should be revisited — this was a documented-and-verified choice, not a permanent guarantee.
 *
 * Our internal `Message.toolCallId` only stores an opaque id (to match OpenAI/Anthropic's
 * id-based correlation scheme), so to produce the `tool_name` Ollama needs we scan backward
 * through the conversation for the assistant message whose `toolCalls` array contains a call
 * with a matching `id`, and use that call's `name`.
 */
function findToolNameForCallId(messages: Message[], beforeIndex: number, toolCallId: string | undefined): string | undefined {
  if (!toolCallId) return undefined;
  for (let i = beforeIndex - 1; i >= 0; i--) {
    const match = messages[i]?.toolCalls?.find((tc) => tc.id === toolCallId);
    if (match) return match.name;
  }
  return undefined;
}

function toOllamaMessage(message: Message, index: number, messages: Message[]): OllamaOutMessage {
  if (message.role === "tool") {
    const toolName = findToolNameForCallId(messages, index, message.toolCallId);
    return { role: message.role, content: message.content, ...(toolName ? { tool_name: toolName } : {}) };
  }
  if (message.role === "assistant" && message.toolCalls && message.toolCalls.length > 0) {
    return {
      role: message.role,
      content: message.content,
      tool_calls: message.toolCalls.map((tc) => ({ type: "function" as const, function: { name: tc.name, arguments: tc.input } })),
    };
  }
  return { role: message.role, content: message.content };
}

function parseLine(line: string): ModelResponseChunk[] {
  const parsed = JSON.parse(line) as OllamaChatLine;
  const chunks: ModelResponseChunk[] = [];
  if (parsed.message?.content) {
    chunks.push({ type: "text_delta", textDelta: parsed.message.content });
  }
  for (const call of parsed.message?.tool_calls ?? []) {
    // `id`: real Ollama responses don't send one (see OllamaChatLine above) — synthesize a
    // unique one so this ToolCall can still be correlated through the rest of the pipeline
    // (runModelWithTools / the tool registry / the eventual `tool` result message), the same way
    // every other real id would be. `crypto.randomUUID()` is a Node >=20 global (this repo's
    // minimum engine), no import needed.
    // `arguments`: accept either a plain object (the real shape) or a JSON string (defensive,
    // in case a future Ollama version — or an OpenAI-compatible proxy in front of it — encodes it
    // as a string instead); only JSON.parse when it actually is a string, to avoid crashing on
    // `JSON.parse` being handed a non-string value.
    const args = call.function.arguments;
    chunks.push({
      type: "tool_call",
      toolCall: {
        id: call.id ?? crypto.randomUUID(),
        name: call.function.name,
        input: typeof args === "string" ? JSON.parse(args || "{}") : (args ?? {}),
      },
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
          messages: request.messages.map(toOllamaMessage),
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
