import { describe, expect, it } from "vitest";
import { humanizeReasoning, humanizeToolCall, thinkingSummary, toolActionLabel } from "./humanize";

describe("humanizeReasoning", () => {
  it("strips code fences, commands and paths into natural language", () => {
    const out = humanizeReasoning("先运行 bash scripts/main.py 看一下\n```py\nprint(1)\n```\n然后 web_search 确认");
    expect(out).not.toMatch(/scripts\/main\.py|python3|\bbash\b|web_search|```/);
    expect(out).toContain("运行命令");
    expect(out).toContain("网页搜索");
  });
});

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

describe("thinkingSummary", () => {
  it("summarizes web retrieval and generic actions for the collapsed header", () => {
    expect(
      thinkingSummary([
        { id: "t1", kind: "tool", name: "web_search", arguments: {}, result: "x", ok: true },
        { id: "t2", kind: "tool", name: "web_search", arguments: {}, result: "y", ok: true },
      ]),
    ).toBe("已联网搜索 · 2 步");
    expect(thinkingSummary([{ id: "r", kind: "reasoning", content: "想" }])).toBe("已深度思考");
    expect(thinkingSummary([{ id: "t", kind: "tool", name: "get_weather", arguments: {}, result: "x", ok: true }])).toBe(
      "已执行 · 1 步",
    );
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
