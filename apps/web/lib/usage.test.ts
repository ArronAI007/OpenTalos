import { describe, expect, it } from "vitest";
import { formatUsage } from "./usage";

describe("formatUsage", () => {
  it("formats tokens and cost", () => {
    expect(formatUsage({ total_tokens: 1234, cost: 0.0034 })).toBe("1,234 tokens · $0.0034");
  });

  it("shows tokens only when cost is unknown", () => {
    expect(formatUsage({ total_tokens: 10 })).toBe("10 tokens");
  });

  it("is empty when there is nothing to show", () => {
    expect(formatUsage(undefined)).toBe("");
    expect(formatUsage({})).toBe("");
  });
});
