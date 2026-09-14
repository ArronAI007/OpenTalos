import type { ModelProvider, ModelResponseChunk } from "@opentalos/core-types";

/** Deterministic, offline, no-network-call ModelProvider — used by Playwright's E2E suite (via
 * `MODEL_PROVIDER=mock`) and for manual smoke testing without a real API key. NOT a production
 * fallback: createModelProviderFromEnv() never selects this implicitly, only when
 * MODEL_PROVIDER is explicitly set to "mock". */
export function createMockProvider(): ModelProvider {
  return {
    async *complete(request, options): AsyncIterable<ModelResponseChunk> {
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
      // Chunked (not yielded whole) so MODEL_PROVIDER=mock — used by the whole E2E suite and for
      // manual smoke testing without a real API key — also visibly demonstrates streaming rather
      // than looking identical to the old one-shot behavior. Final concatenated text is unchanged.
      // 120ms/chunk (not e.g. 15ms) is deliberate: apps/web's e2e stop-control test needs the
      // streaming window to be wide enough for Playwright to observe and click the 停止 button
      // before the reply finishes — a ~50-char reply now takes ~2-3s to stream, comfortably inside
      // every e2e test's existing per-assertion timeouts (10s+) without approaching the 30s test
      // timeout even across a whole test's multiple waits.
      for (const chunk of reply.match(/.{1,4}/gu) ?? [reply]) {
        if (options?.signal?.aborted) return;
        yield { type: "text_delta", textDelta: chunk };
        await new Promise((resolve) => setTimeout(resolve, 120));
      }
      if (options?.signal?.aborted) return;
      yield { type: "message_stop" };
    },
  };
}
