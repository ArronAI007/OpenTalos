import type { JSONSchema, ModelProvider, ModelRequest, ModelResponseChunk } from "@opentalos/core-types";

export interface OpenAIStreamChunk {
  choices: {
    delta: {
      content?: string;
      // Real OpenAI-protocol streaming fragments each tool call across many chunks: `index`
      // identifies which tool call a fragment belongs to (always present), `id`/`function.name`
      // arrive only on that call's first fragment, and `function.arguments` is split into partial
      // JSON-string fragments that must be concatenated (never parsed on their own — a lone
      // fragment like `{"lo` is not valid JSON) and only parsed once the call is complete.
      // Confirmed against the installed `openai@7.12.1` types (`Delta.ToolCall` has a required
      // `index: number` and optional `id`/`function`).
      tool_calls?: { index: number; id?: string; function?: { name?: string; arguments?: string } }[];
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

      // Keyed by each tool call's `index` (stable across fragments within one completion) and
      // accumulated across chunks until `finish_reason` arrives, since `id`/`function.name` only
      // arrive on the first fragment and `function.arguments` is split across many.
      const pendingToolCalls = new Map<number, { id: string; name: string; argsJson: string }>();

      for await (const chunk of stream) {
        const choice = chunk.choices[0];
        if (choice?.delta.content) {
          yield { type: "text_delta", textDelta: choice.delta.content };
        }
        for (const call of choice?.delta.tool_calls ?? []) {
          const existing = pendingToolCalls.get(call.index);
          pendingToolCalls.set(call.index, {
            id: call.id ?? existing?.id ?? "",
            name: call.function?.name ?? existing?.name ?? "",
            argsJson: (existing?.argsJson ?? "") + (call.function?.arguments ?? ""),
          });
        }
        if (choice?.finish_reason) {
          for (const [, call] of [...pendingToolCalls].sort(([a], [b]) => a - b)) {
            yield {
              type: "tool_call",
              toolCall: { id: call.id, name: call.name, input: JSON.parse(call.argsJson || "{}") },
            };
          }
          pendingToolCalls.clear();
          yield { type: "message_stop" };
        }
      }
    },
  };
}
