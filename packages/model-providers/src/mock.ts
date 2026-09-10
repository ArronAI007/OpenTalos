import type { ModelProvider, ModelResponseChunk } from "@opentalos/core-types";

/** Deterministic, offline, no-network-call ModelProvider — used by Playwright's E2E suite (via
 * `MODEL_PROVIDER=mock`) and for manual smoke testing without a real API key. NOT a production
 * fallback: createModelProviderFromEnv() never selects this implicitly, only when
 * MODEL_PROVIDER is explicitly set to "mock". */
export function createMockProvider(): ModelProvider {
  return {
    async *complete(request): AsyncIterable<ModelResponseChunk> {
      const hasToolResult = request.messages.some((m) => m.role === "tool");
      if (!hasToolResult && request.tools && request.tools.length > 0) {
        const tool = request.tools[0];
        const defaultInput = tool.name === "lookup_exchange_rate" ? { pair: "USD/CNY" } : { query: "test" };
        yield { type: "tool_call", toolCall: { id: `mock-${Date.now()}`, name: tool.name, input: defaultInput } };
        yield { type: "message_stop" };
        return;
      }
      const lastToolMessage = [...request.messages].reverse().find((m) => m.role === "tool");
      const reply = lastToolMessage ? `根据查询结果：${lastToolMessage.content}` : "你好，我是 OpenTalos 的模拟回复（MODEL_PROVIDER=mock）。";
      yield { type: "text_delta", textDelta: reply };
      yield { type: "message_stop" };
    },
  };
}
