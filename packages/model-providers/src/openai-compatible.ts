import type { JSONSchema, ModelProvider, ModelRequest, ModelResponseChunk } from "@opentalos/core-types";

export interface OpenAIStreamChunk {
  choices: {
    delta: {
      content?: string;
      // Not part of the standard OpenAI protocol — a Moonshot/DeepSeek-style extension some
      // "thinking" models (e.g. Kimi K3, which has reasoning on by default) stream as a field
      // separate from `content`. Absent entirely for non-thinking models/providers.
      reasoning_content?: string;
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

type OpenAIContentPart = { type: "text"; text: string } | { type: "image_url"; image_url: { url: string } };

interface OpenAIOutMessage {
  role: string;
  // A plain string for an ordinary text-only message; an array of parts only when this message
  // carries image attachments (see `images` below) — matches Moonshot's documented vision format
  // (https://platform.kimi.ai/docs/guide/use-kimi-vision-model): "message.content must be an
  // array[object] ... Serializing it as a string is non-standard and may not process visual input
  // correctly."
  content: string | OpenAIContentPart[];
  tool_calls?: { id: string; type: "function"; function: { name: string; arguments: string } }[];
  tool_call_id?: string;
}

// A "builtin_function" tool (e.g. Kimi/Moonshot's `$web_search`) is provider-hosted: only its
// name is declared, never description/parameters — the provider knows what it does and executes
// it server-side. Sending description/parameters for one would be meaningless (and Moonshot's API
// docs don't show any), so the two variants are kept structurally distinct rather than just making
// description/parameters optional on one shared shape.
type OpenAIToolDeclaration =
  | { type: "function"; function: { name: string; description: string; parameters: JSONSchema } }
  | { type: "builtin_function"; function: { name: string } };

export interface OpenAIClientLike {
  chat: {
    completions: {
      create(
        params: { model: string; messages: OpenAIOutMessage[]; tools?: OpenAIToolDeclaration[]; stream: true },
        options?: { signal?: AbortSignal },
      ): AsyncIterable<OpenAIStreamChunk>;
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
    async *complete(request: ModelRequest, callOptions?: { signal?: AbortSignal }): AsyncIterable<ModelResponseChunk> {
      const stream = client.chat.completions.create(
        {
          model: options.model,
          messages: request.messages.map((m): OpenAIOutMessage => ({
            role: m.role,
            content: m.images?.length
              ? [...m.images.map((url): OpenAIContentPart => ({ type: "image_url", image_url: { url } })), { type: "text", text: m.content }]
              : m.content,
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
          tools: request.tools?.map((t): OpenAIToolDeclaration =>
            t.kind === "builtin"
              ? { type: "builtin_function", function: { name: t.name } }
              : { type: "function", function: { name: t.name, description: t.description, parameters: t.inputSchema } },
          ),
          stream: true,
        },
        { signal: callOptions?.signal },
      );

      // Keyed by each tool call's `index` (stable across fragments within one completion) and
      // accumulated across chunks until `finish_reason` arrives, since `id`/`function.name` only
      // arrive on the first fragment and `function.arguments` is split across many.
      const pendingToolCalls = new Map<number, { id: string; name: string; argsJson: string }>();

      for await (const chunk of stream) {
        const choice = chunk.choices[0];
        if (choice?.delta.reasoning_content) {
          yield { type: "reasoning_delta", reasoningDelta: choice.delta.reasoning_content };
        }
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
