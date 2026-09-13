import { describe, expect, it } from "vitest";
import { webSearchTool } from "./tools.js";

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
