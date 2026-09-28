import { describe, expect, it } from "vitest";
import { filterSkills, filterSkillsByCategory } from "./skills-filter";

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

interface TaggedSkill { name: string; tags: string[] }

describe("filterSkillsByCategory", () => {
  const skills: TaggedSkill[] = [
    { name: "date", tags: ["编程"] },
    { name: "csv-to-json", tags: ["数据", "编程"] },
    { name: "text-to-table", tags: ["数据"] },
  ];

  it("分类是全部时原样返回", () => {
    expect(filterSkillsByCategory(skills, "全部")).toBe(skills);
  });

  it("按标签精确匹配", () => {
    expect(filterSkillsByCategory(skills, "编程").map((s) => s.name)).toEqual(["date", "csv-to-json"]);
  });

  it("没有匹配返回空数组", () => {
    expect(filterSkillsByCategory(skills, "设计")).toEqual([]);
  });

  it("没有标签的技能在任何具体分类下都不匹配", () => {
    const untagged: TaggedSkill[] = [{ name: "alpha", tags: [] }];
    expect(filterSkillsByCategory(untagged, "编程")).toEqual([]);
  });
});
