import { describe, expect, it } from "vitest";
import { filterSkills } from "./skills-filter";

interface Skill { name: string; description: string }

describe("filterSkills", () => {
  const skills: Skill[] = [
    { name: "date", description: "计算相对于今天的日期" },
    { name: "csv-to-json", description: "把 CSV 转成 JSON" },
    { name: "text-to-table", description: "把文本转成表格" },
  ];

  it("空 query 原样返回全部", () => {
    expect(filterSkills(skills, "")).toBe(skills);
    expect(filterSkills(skills, "   ")).toBe(skills);
  });

  it("按 name 匹配，大小写不敏感", () => {
    expect(filterSkills(skills, "CSV").map((s) => s.name)).toEqual(["csv-to-json"]);
  });

  it("按 description 匹配", () => {
    expect(filterSkills(skills, "日期").map((s) => s.name)).toEqual(["date"]);
  });

  it("无匹配返回空数组", () => {
    expect(filterSkills(skills, "不存在的技能")).toEqual([]);
  });

  it("首尾空格不影响匹配", () => {
    expect(filterSkills(skills, "  date  ").map((s) => s.name)).toEqual(["date"]);
  });
});
