import type { JSONSchema, ModelProvider, ModelRequest, ModelResponseChunk } from "@opentalos/core-types";

export interface OpenAIStreamChunk {
  choices: {
    delta: {
      content?: string;
      tool_calls?: { id: string; function: { name: string; arguments: string } }[];
    };
    finish_reason?: string | null;
  }[];
}

interface OpenAIOutMessage {
  role: string;
  content: string;
  tool_calls?: { id: string; type: "function"; function: { name: string; arguments: string } }[];
  tool_call_id?: string;
}

export interface OpenAIClientLike {
  chat: {
    completions: {
      create(params: {
        model: string;
        messages: OpenAIOutMessage[];
        tools?: { type: "function"; function: { name: string; description: string; parameters: JSONSchema } }[];
        stream: true;
      }): AsyncIterable<OpenAIStreamChunk>;
    };
  };
}

export interface OpenAICompatibleProviderOptions {
  model: string;
}

export function createOpenAICompatibleProvider(
  client: OpenAIClientLike,
  options: OpenAICompatibleProviderOptions,
): ModelProvider {
  return {
    async *complete(request: ModelRequest): AsyncIterable<ModelResponseChunk> {
      const stream = client.chat.completions.create({
        model: options.model,
        messages: request.messages.map((m): OpenAIOutMessage => ({
          role: m.role,
          content: m.content,
          ...(m.toolCalls
            ? {
                tool_calls: m.toolCalls.map((tc) => ({
                  id: tc.id,
                  type: "function" as const,
                  function: { name: tc.name, arguments: JSON.stringify(tc.input) },
                })),
              }
            : {}),
          ...(m.toolCallId ? { tool_call_id: m.toolCallId } : {}),
        })),
        tools: request.tools?.map((t) => ({
          type: "function",
          function: { name: t.name, description: t.description, parameters: t.inputSchema },
        })),
        stream: true,
      });

      for await (const chunk of stream) {
        const choice = chunk.choices[0];
        if (choice?.delta.content) {
          yield { type: "text_delta", textDelta: choice.delta.content };
        }
        for (const call of choice?.delta.tool_calls ?? []) {
          yield {
            type: "tool_call",
            toolCall: { id: call.id, name: call.function.name, input: JSON.parse(call.function.arguments || "{}") },
          };
        }
        if (choice?.finish_reason) {
          yield { type: "message_stop" };
        }
      }
    },
  };
}
