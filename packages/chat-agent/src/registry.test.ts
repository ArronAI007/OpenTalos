import { describe, expect, it } from "vitest";
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
});
