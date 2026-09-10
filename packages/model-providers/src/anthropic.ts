import type { JSONSchema, Message, ModelProvider, ModelRequest, ModelResponseChunk } from "@opentalos/core-types";

export type AnthropicStreamEvent =
  | { type: "content_block_delta"; index: number; delta: { type: "text_delta"; text: string } }
  // `input_json_delta` is how the real Anthropic streaming API actually sends a tool_use block's
  // arguments: NOT as a complete `input` object on `content_block_start` (that event's `input` is
  // always `{}` at start-of-block) — the JSON is streamed token-by-token as `partial_json` string
  // fragments across one or more `content_block_delta` events, to be concatenated and parsed only
  // once the block closes (`content_block_stop`). Confirmed against the installed
  // `@anthropic-ai/sdk@0.124.0` types (`RawContentBlockDelta = TextDelta | InputJSONDelta | ...`).
  | { type: "content_block_delta"; index: number; delta: { type: "input_json_delta"; partial_json: string } }
  | { type: "content_block_delta"; index: number; delta: { type: string } }
  | { type: "content_block_start"; index: number; content_block: { type: "tool_use"; id: string; name: string; input: unknown } }
  | { type: "content_block_start"; index: number; content_block: { type: string } }
  | { type: "content_block_stop"; index: number }
  | { type: "message_stop" }
  | { type: string };

type AnthropicContentBlock =
  | { type: "tool_use"; id: string; name: string; input: unknown }
  | { type: "tool_result"; tool_use_id: string; content: string };

interface AnthropicOutMessage {
  role: "user" | "assistant";
  content: string | AnthropicContentBlock[];
}

export interface AnthropicClientLike {
  messages: {
    stream(params: {
      model: string;
      max_tokens: number;
      system?: string;
      messages: AnthropicOutMessage[];
      tools?: { name: string; description: string; input_schema: JSONSchema }[];
    }): AsyncIterable<AnthropicStreamEvent>;
  };
}

export interface AnthropicProviderOptions {
  model: string;
  maxTokens?: number;
}

/** Anthropic has no wire-level "tool" role: a tool result is a `user`-role message whose content
 * is a `tool_result` block. An assistant message that requested tool calls becomes `tool_use`
 * blocks instead of plain text. Everything else maps through as plain string content, matching
 * the existing (pre-tool-calling) behavior exactly. */
function toAnthropicMessage(message: Message): AnthropicOutMessage | undefined {
  if (message.role === "tool") {
    return {
      role: "user",
      content: [{ type: "tool_result", tool_use_id: message.toolCallId ?? "", content: message.content }],
    };
  }
  if (message.role === "assistant" && message.toolCalls && message.toolCalls.length > 0) {
    return {
      role: "assistant",
      content: message.toolCalls.map((tc) => ({ type: "tool_use" as const, id: tc.id, name: tc.name, input: tc.input })),
    };
  }
  if (message.role === "user" || message.role === "assistant") {
    return { role: message.role, content: message.content };
  }
  return undefined; // "system" is extracted separately below, not sent as a regular message
}

export function createAnthropicProvider(client: AnthropicClientLike, options: AnthropicProviderOptions): ModelProvider {
  return {
    async *complete(request: ModelRequest): AsyncIterable<ModelResponseChunk> {
      const system = request.messages.find((m) => m.role === "system");
      const conversation = request.messages
        .map(toAnthropicMessage)
        .filter((m): m is AnthropicOutMessage => m !== undefined);

      const stream = client.messages.stream({
        model: options.model,
        max_tokens: options.maxTokens ?? 1024,
        system: system?.content,
        messages: conversation,
        tools: request.tools?.map((t) => ({ name: t.name, description: t.description, input_schema: t.inputSchema })),
      });

      // Keyed by the block's `index` (Anthropic streams multiple content blocks — text and
      // tool_use — interleaved in one message, each independently identified by index). Holds
      // the tool_use block's id/name (from content_block_start) and its `input` JSON accumulated
      // so far from `input_json_delta` fragments (from content_block_delta), until the block
      // closes and the full JSON can be parsed.
      const pendingToolBlocks = new Map<number, { id: string; name: string; json: string }>();

      const flushToolBlock = (index: number): ModelResponseChunk | undefined => {
        const pending = pendingToolBlocks.get(index);
        if (!pending) return undefined;
        pendingToolBlocks.delete(index);
        return {
          type: "tool_call",
          toolCall: { id: pending.id, name: pending.name, input: JSON.parse(pending.json || "{}") },
        };
      };

      for await (const event of stream) {
        if (event.type === "content_block_start" && "content_block" in event && event.content_block.type === "tool_use") {
          const block = event.content_block as { id: string; name: string };
          pendingToolBlocks.set(event.index, { id: block.id, name: block.name, json: "" });
        } else if (event.type === "content_block_delta" && "delta" in event && event.delta.type === "text_delta") {
          yield { type: "text_delta", textDelta: (event.delta as { text: string }).text };
        } else if (event.type === "content_block_delta" && "delta" in event && event.delta.type === "input_json_delta") {
          const pending = pendingToolBlocks.get(event.index);
          if (pending) pending.json += (event.delta as { partial_json: string }).partial_json;
        } else if (event.type === "content_block_stop" && "index" in event) {
          const chunk = flushToolBlock(event.index);
          if (chunk) yield chunk;
        } else if (event.type === "message_stop") {
          // Defensive: flush any tool_use block that somehow never got a content_block_stop
          // (should not happen per the real protocol, but avoids silently dropping a tool call
          // rather than crashing or losing it if a provider or test double omits it).
          for (const index of [...pendingToolBlocks.keys()]) {
            const chunk = flushToolBlock(index);
            if (chunk) yield chunk;
          }
          yield { type: "message_stop" };
        }
      }
    },
  };
}
