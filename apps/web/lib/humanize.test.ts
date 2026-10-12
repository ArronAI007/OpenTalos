import { describe, expect, it } from "vitest";
import { humanizeToolCall, toolActionLabel } from "./humanize";

describe("toolActionLabel", () => {
  it("maps known tools to natural-language actions", () => {
    expect(toolActionLabel("bash")).toBe("运行技能脚本");
    expect(toolActionLabel("read")).toBe("读取技能文档");
    expect(toolActionLabel("web_search")).toBe("网页搜索");
  });

  it("falls back to the raw name for unknown (e.g. MCP) tools", () => {
    expect(toolActionLabel("get_weather")).toBe("get_weather");
  });
});

describe("humanizeToolCall", () => {
  it("maps a known tool to a natural-language label and picks the query detail", () => {
    expect(humanizeToolCall("web_search", { query: "manus 招聘", max_results: 10 })).toEqual({
      label: "网页搜索",
      detail: "manus 招聘",
    });
  });

  it("prefers a short description over a long prompt", () => {
    expect(humanizeToolCall("dispatch_subagent", { description: "查一下", prompt: "很长的任务描述" })).toEqual({
      label: "派发子任务",
      detail: "查一下",
    });
  });

  it("joins array details (urls)", () => {
    expect(humanizeToolCall("web_extractor", { urls: ["https://a.com", "https://b.com"] }).detail).toBe(
      "https://a.com, https://b.com",
    );
  });

  it("falls back to the raw name for unknown (e.g. MCP) tools", () => {
    expect(humanizeToolCall("get_weather", { city: "上海" })).toEqual({ label: "get_weather", detail: "" });
  });

  it("truncates an overlong detail", () => {
    const { detail } = humanizeToolCall("web_search", { query: "x".repeat(120) });
    expect(detail.endsWith("…")).toBe(true);
    expect(detail.length).toBe(61);
  });
});
