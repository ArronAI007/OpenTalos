import { describe, expect, it } from "vitest";
import type { ModelRequest, ModelResponseChunk } from "@opentalos/core-types";
import { createMockProvider } from "./mock.js";

describe("createMockProvider", () => {
  it("requests the first available tool when no tool result is in history yet", async () => {
    const provider = createMockProvider();
    const request: ModelRequest = {
      messages: [{ role: "user", content: "今天美元兑人民币汇率是多少？" }],
      tools: [{ name: "lookup_exchange_rate", description: "looks up a rate", inputSchema: { type: "object" } }],
    };
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks[0].type).toBe("reasoning_delta");
    expect(chunks.find((c) => c.type === "tool_call")).toEqual({
      type: "tool_call",
      toolCall: { id: expect.any(String), name: "lookup_exchange_rate", input: { pair: "USD/CNY" } },
    });
    expect(chunks[chunks.length - 1]).toEqual({ type: "message_stop" });
  });

  it("emits a reasoning_delta chunk ahead of every round, for exercising the reasoning-display UI without a real model", async () => {
    const provider = createMockProvider();
    const request: ModelRequest = { messages: [{ role: "user", content: "你好" }] };
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    const reasoningChunks = chunks.filter((c): c is { type: "reasoning_delta"; reasoningDelta: string } => c.type === "reasoning_delta");
    expect(reasoningChunks.length).toBeGreaterThan(0);
    expect(reasoningChunks[0].reasoningDelta.length).toBeGreaterThan(0);
  });

  it("replies with the tool result once one is present in history, without requesting another tool", async () => {
    const provider = createMockProvider();
    const request: ModelRequest = {
      messages: [
        { role: "user", content: "今天美元兑人民币汇率是多少？" },
        { role: "assistant", content: "", toolCalls: [{ id: "call-1", name: "lookup_exchange_rate", input: { pair: "USD/CNY" } }] },
        { role: "tool", content: "1 USD/CNY = 7.13", toolCallId: "call-1" },
      ],
      tools: [{ name: "lookup_exchange_rate", description: "looks up a rate", inputSchema: { type: "object" } }],
    };
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks.some((c) => c.type === "tool_call")).toBe(false);
    const textChunks = chunks.filter((c): c is { type: "text_delta"; textDelta: string } => c.type === "text_delta");
    const fullText = textChunks.map((c) => c.textDelta).join("");
    expect(fullText).toContain("根据查询结果");
    expect(fullText).toContain("1 USD/CNY = 7.13");
  });

  it("replies with a generic greeting when no tools are offered at all", async () => {
    const provider = createMockProvider();
    const request: ModelRequest = { messages: [{ role: "user", content: "你好" }] };
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    expect(chunks.some((c) => c.type === "tool_call")).toBe(false);
    const textChunks = chunks.filter((c): c is { type: "text_delta"; textDelta: string } => c.type === "text_delta");
    expect(textChunks.map((c) => c.textDelta).join("").length).toBeGreaterThan(0);
  });

  it("acknowledges attached images in its reply, once a tool result is present", async () => {
    const provider = createMockProvider();
    const request: ModelRequest = {
      messages: [
        { role: "user", content: "这张图是什么？", images: ["data:image/png;base64,AAA", "data:image/png;base64,BBB"] },
        { role: "assistant", content: "", toolCalls: [{ id: "call-1", name: "lookup_exchange_rate", input: { pair: "USD/CNY" } }] },
        { role: "tool", content: "1 USD/CNY = 7.13", toolCallId: "call-1" },
      ],
      tools: [{ name: "lookup_exchange_rate", description: "looks up a rate", inputSchema: { type: "object" } }],
    };
    const chunks = [];
    for await (const chunk of provider.complete(request)) chunks.push(chunk);
    const textChunks = chunks.filter((c): c is { type: "text_delta"; textDelta: string } => c.type === "text_delta");
    expect(textChunks.map((c) => c.textDelta).join("")).toContain("收到 2 张图片");
  });

  it("stops yielding once the signal is aborted, without throwing", async () => {
    const provider = createMockProvider();
    const controller = new AbortController();
    const chunks: ModelResponseChunk[] = [];
    const iterator = provider.complete({ messages: [{ role: "user", content: "hi" }] }, { signal: controller.signal });
    for await (const chunk of iterator) {
      chunks.push(chunk);
      if (chunks.length === 1) controller.abort();
    }
    expect(chunks.length).toBeGreaterThanOrEqual(1);
    expect(chunks.every((c) => c.type !== "message_stop")).toBe(true);
  });
});
