import type { JSONSchema, ModelProvider, ModelRequest, ModelResponseChunk } from "@opentalos/core-types";

export type AnthropicStreamEvent =
  | { type: "content_block_delta"; delta: { type: "text_delta"; text: string } }
  | { type: "content_block_delta"; delta: { type: string } }
  | { type: "content_block_start"; content_block: { type: "tool_use"; id: string; name: string; input: unknown } }
  | { type: "content_block_start"; content_block: { type: string } }
  | { type: "message_stop" }
  | { type: string };

export interface AnthropicClientLike {
  messages: {
    stream(params: {
      model: string;
      max_tokens: number;
      system?: string;
      messages: { role: "user" | "assistant"; content: string }[];
      tools?: { name: string; description: string; input_schema: JSONSchema }[];
    }): AsyncIterable<AnthropicStreamEvent>;
  };
}

export interface AnthropicProviderOptions {
  model: string;
  maxTokens?: number;
}

export function createAnthropicProvider(client: AnthropicClientLike, options: AnthropicProviderOptions): ModelProvider {
  return {
    async *complete(request: ModelRequest): AsyncIterable<ModelResponseChunk> {
      const system = request.messages.find((m) => m.role === "system");
      const conversation = request.messages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));

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
