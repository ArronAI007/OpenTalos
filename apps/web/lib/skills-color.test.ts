import { describe, expect, it } from "vitest";
import { skillCardTint } from "./skills-color";

describe("skillCardTint", () => {
  it("同一个名字每次返回同一个色块", () => {
    expect(skillCardTint("date")).toEqual(skillCardTint("date"));
  });

  it("返回的 bg 和 icon 都是非空字符串", () => {
    const tint = skillCardTint("csv-to-json");
    expect(tint.bg.length).toBeGreaterThan(0);
    expect(tint.icon.length).toBeGreaterThan(0);
  });

  it("空字符串也不抛错", () => {
    expect(() => skillCardTint("")).not.toThrow();
  });
});
