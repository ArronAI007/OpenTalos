import type { JSONSchema, Message, ModelProvider, ModelRequest, ModelResponseChunk } from "@opentalos/core-types";

export type AnthropicStreamEvent =
  | { type: "content_block_delta"; delta: { type: "text_delta"; text: string } }
  | { type: "content_block_delta"; delta: { type: string } }
  | { type: "content_block_start"; content_block: { type: "tool_use"; id: string; name: string; input: unknown } }
  | { type: "content_block_start"; content_block: { type: string } }
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

      for await (const event of stream) {
        if (event.type === "content_block_delta" && "delta" in event && event.delta.type === "text_delta") {
          yield { type: "text_delta", textDelta: (event.delta as { text: string }).text };
        } else if (event.type === "content_block_start" && "content_block" in event && event.content_block.type === "tool_use") {
          const block = event.content_block as { id: string; name: string; input: unknown };
          yield { type: "tool_call", toolCall: { id: block.id, name: block.name, input: block.input } };
        } else if (event.type === "message_stop") {
          yield { type: "message_stop" };
        }
      }
    },
  };
}
