import { describe, expect, it } from "vitest";
import type { MemoryStore, TenantContext } from "@opentalos/core-types";
import { createSearchMemoryTool, webSearchTool } from "./tools.js";

describe("webSearchTool", () => {
  it("is declared as a builtin tool", () => {
    expect(webSearchTool.definition.kind).toBe("builtin");
    expect(webSearchTool.definition.name).toBe("$web_search");
  });

  it("echoes its input back verbatim as JSON, rather than performing any search itself", async () => {
    const result = await webSearchTool.execute({ query: "今天美元兑人民币汇率" });
    expect(result.output).toBe(JSON.stringify({ query: "今天美元兑人民币汇率" }));
    expect(result.isError).toBeUndefined();
  });
});

describe("createSearchMemoryTool", () => {
  // Regression test for the bug caught in review: packages/sdk's runModelWithTools does
  // `String(result.output)` before splicing a tool's result back into the conversation. An array
  // of objects would stringify to "[object Object],[object Object]" garbage instead of the actual
  // memory content, so `output` must be a real string (matching lookupExchangeRateTool/
  // webSearchTool above), never the raw MemoryRecord[] array.
  it("returns output as a JSON string, not the raw array of memory records", async () => {
    const fakeMemoryStore: MemoryStore = {
      read: async () => undefined,
      write: async () => {},
      search: async (_query: string, _ctx: TenantContext) => [
        { key: "职业", value: "后端工程师" },
      ],
    };
    const tool = createSearchMemoryTool(fakeMemoryStore);
    const result = await tool.execute({ query: "职业" }, { tenantId: "tenant-a", sessionId: "session-a" });

    expect(typeof result.output).toBe("string");
    expect(result.output).toBe(JSON.stringify([{ key: "职业", value: "后端工程师" }]));
  });
});
