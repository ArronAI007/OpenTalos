import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { loadSkills } from "./discovery.js";

const FIXTURES_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "fixtures");

describe("loadSkills", () => {
  it("discovers every subdirectory containing a valid SKILL.md", () => {
    const skills = loadSkills(resolve(FIXTURES_DIR, "valid-set"));
    const names = skills.map((s) => s.name).sort();
    expect(names).toEqual(["alpha-skill", "beta-skill"]);
  });

  it("parses name, description, and full content correctly", () => {
    const skills = loadSkills(resolve(FIXTURES_DIR, "valid-set"));
    const alpha = skills.find((s) => s.name === "alpha-skill");
    expect(alpha?.description).toBe("Does alpha things. Use for alpha tasks.");
    expect(alpha?.content).toContain("# alpha-skill");
    expect(alpha?.dir).toBe(resolve(FIXTURES_DIR, "valid-set", "alpha-skill"));
  });

  it("skips a directory whose SKILL.md is missing the description field, without throwing", () => {
    const skills = loadSkills(resolve(FIXTURES_DIR, "with-invalid"));
    const names = skills.map((s) => s.name);
    expect(names).toEqual(["good-skill"]);
  });

  it("skips a directory with no SKILL.md at all", () => {
    const skills = loadSkills(resolve(FIXTURES_DIR, "with-non-skill-dir"));
    const names = skills.map((s) => s.name);
    expect(names).toEqual(["real-skill"]);
  });

  it("returns an empty array for a directory that doesn't exist", () => {
    expect(loadSkills(resolve(FIXTURES_DIR, "does-not-exist"))).toEqual([]);
  });
});
