import { describe, expect, it } from "vitest";
import type { MemoryStore } from "@opentalos/core-types";
import { createChatAgentToolRegistry } from "./registry.js";

describe("createChatAgentToolRegistry", () => {
  it("always registers lookup_exchange_rate", () => {
    const registry = createChatAgentToolRegistry();
    expect(registry.list().map((tool) => tool.name)).toContain("lookup_exchange_rate");
  });

  it("does not register $web_search for a provider other than kimi", () => {
    const registry = createChatAgentToolRegistry({ modelProvider: "openai-compatible" });
    expect(registry.list().map((tool) => tool.name)).not.toContain("$web_search");
  });

  it("does not register $web_search when no provider is given", () => {
    const registry = createChatAgentToolRegistry();
    expect(registry.list().map((tool) => tool.name)).not.toContain("$web_search");
  });

  it("registers $web_search as a builtin tool only when modelProvider is kimi", () => {
    const registry = createChatAgentToolRegistry({ modelProvider: "kimi" });
    const definitions = registry.list();
    expect(definitions.map((tool) => tool.name)).toContain("$web_search");
    expect(definitions.find((tool) => tool.name === "$web_search")?.kind).toBe("builtin");
  });

  it("does not register search_memory when no memoryStore is given", () => {
    const registry = createChatAgentToolRegistry();
    expect(registry.list().map((tool) => tool.name)).not.toContain("search_memory");
  });

  it("registers search_memory when a memoryStore is given", () => {
    const fakeMemoryStore: MemoryStore = { read: async () => undefined, write: async () => {}, search: async () => [] };
    const registry = createChatAgentToolRegistry({ memoryStore: fakeMemoryStore });
    expect(registry.list().map((tool) => tool.name)).toContain("search_memory");
  });
});
