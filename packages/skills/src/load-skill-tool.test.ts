import { describe, expect, it } from "vitest";
import { createLoadSkillTool } from "./load-skill-tool.js";
import type { Skill } from "./discovery.js";

const skills: Skill[] = [
  { name: "alpha-skill", description: "Does alpha things.", content: "# alpha-skill\nfull content here", dir: "/skills/alpha-skill" },
  { name: "beta-skill", description: "Does beta things.", content: "# beta-skill\nfull content here", dir: "/skills/beta-skill" },
];

describe("createLoadSkillTool", () => {
  it("names every known skill in its own tool description", () => {
    const tool = createLoadSkillTool(skills);
    expect(tool.definition.description).toContain("alpha-skill: Does alpha things.");
    expect(tool.definition.description).toContain("beta-skill: Does beta things.");
  });

  it("returns the full content of the requested skill", async () => {
    const tool = createLoadSkillTool(skills);
    const result = await tool.execute({ name: "alpha-skill" }, { tenantId: "t", sessionId: "s" });
    expect(result.output).toBe("# alpha-skill\nfull content here");
    expect(result.isError).toBeFalsy();
  });

  it("returns a clear error for an unknown skill name, without throwing", async () => {
    const tool = createLoadSkillTool(skills);
    const result = await tool.execute({ name: "does-not-exist" }, { tenantId: "t", sessionId: "s" });
    expect(result.isError).toBe(true);
    expect(String(result.output)).toContain("does-not-exist");
  });
});
