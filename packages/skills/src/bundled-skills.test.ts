import { describe, expect, it } from "vitest";
import { loadSkills } from "./discovery.js";
import { createRunSkillScriptTool } from "./run-skill-script-tool.js";
import { BUNDLED_SKILLS_DIR } from "./bundled-dir.js";

describe("bundled skills", () => {
  it("discovers text-to-table with a valid name and description", () => {
    const skills = loadSkills(BUNDLED_SKILLS_DIR);
    const textToTable = skills.find((s) => s.name === "text-to-table");
    expect(textToTable).toBeDefined();
    expect(textToTable?.description).toContain("Markdown table");
  });

  it(
    "actually runs text-to-table's format.js in the real sandbox and produces a correct table",
    async () => {
      const skills = loadSkills(BUNDLED_SKILLS_DIR);
      const tool = createRunSkillScriptTool(skills);
      const result = await tool.execute(
        {
          skillName: "text-to-table",
          scriptRelativePath: "format.js",
          args: [","],
          input: "name,age\nAlice,30\nBob,25",
        },
        { tenantId: "t", sessionId: "s" },
      );
      expect(result.isError).toBeFalsy();
      const output = String(result.output).trim();
      expect(output).toContain("| name | age |");
      expect(output).toContain("| Alice | 30 |");
      expect(output).toContain("| Bob | 25 |");
    },
    30_000,
  );
});
