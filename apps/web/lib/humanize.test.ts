import { describe, expect, it } from "vitest";
import { humanizeReasoning, humanizeToolCall } from "./humanize";

describe("humanizeReasoning", () => {
  it("removes fenced code blocks entirely ('natural language, not code')", () => {
    const raw = "先看这段：\n```python\nprint('hi')\n```\n然后继续推理。";
    expect(humanizeReasoning(raw)).toBe("先看这段：\n\n然后继续推理。");
  });

  it("removes an unclosed fence while still streaming", () => {
    expect(humanizeReasoning("继续推理\n```ts\nconst x = 1;")).toBe("继续推理");
  });

  it("unwraps inline code backticks but keeps their text", () => {
    expect(humanizeReasoning("调用 `web_search` 工具")).toBe("调用 web_search 工具");
  });

  it("drops markdown heading markers and unifies bullet symbols", () => {
    expect(humanizeReasoning("## 思路\n- 第一步\n* 第二步")).toBe("思路\n• 第一步\n• 第二步");
  });

  it("collapses 3+ blank lines and trims trailing spaces", () => {
    expect(humanizeReasoning("甲   \n\n\n\n乙")).toBe("甲\n\n乙");
  });

  it("returns empty string for empty input", () => {
    expect(humanizeReasoning("")).toBe("");
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
