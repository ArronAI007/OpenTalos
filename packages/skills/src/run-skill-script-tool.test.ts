import { resolve } from "node:path";
import { mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { describe, expect, it } from "vitest";
import { createRunSkillScriptTool } from "./run-skill-script-tool.js";
import type { Skill } from "./discovery.js";

const FIXTURES_ROOT = resolve(tmpdir(), `run-skill-script-tool-test-${Date.now()}`);
const SKILL_DIR = resolve(FIXTURES_ROOT, "greeter");
mkdirSync(SKILL_DIR, { recursive: true });
writeFileSync(
  resolve(SKILL_DIR, "greet.js"),
  `console.log("hello, " + process.argv[2]);`,
);

const skills: Skill[] = [
  { name: "greeter", description: "Greets someone.", content: "# greeter", dir: SKILL_DIR },
];

describe("createRunSkillScriptTool", () => {
  it(
    "runs the named skill's script in the sandbox and returns its stdout",
    async () => {
      const tool = createRunSkillScriptTool(skills);
      const result = await tool.execute(
        { skillName: "greeter", scriptRelativePath: "greet.js", args: ["world"] },
        { tenantId: "t", sessionId: "s" },
      );
      expect(result.isError).toBeFalsy();
      expect(String(result.output).trim()).toBe("hello, world");
    },
    30_000,
  );

  it("returns a clear error for an unknown skill name, without touching the sandbox", async () => {
    const tool = createRunSkillScriptTool(skills);
    const result = await tool.execute(
      { skillName: "does-not-exist", scriptRelativePath: "greet.js", args: [] },
      { tenantId: "t", sessionId: "s" },
    );
    expect(result.isError).toBe(true);
    expect(String(result.output)).toContain("does-not-exist");
  });

  it("rejects a path-traversal attempt without touching the sandbox", async () => {
    const tool = createRunSkillScriptTool(skills);
    const result = await tool.execute(
      { skillName: "greeter", scriptRelativePath: "../../../etc/passwd", args: [] },
      { tenantId: "t", sessionId: "s" },
    );
    expect(result.isError).toBe(true);
    expect(String(result.output)).toMatch(/outside|traversal|invalid/i);
  });

  it("rejects an absolute path passed as scriptRelativePath, without touching the sandbox", async () => {
    const tool = createRunSkillScriptTool(skills);
    const result = await tool.execute(
      { skillName: "greeter", scriptRelativePath: "/etc/passwd", args: [] },
      { tenantId: "t", sessionId: "s" },
    );
    expect(result.isError).toBe(true);
    expect(String(result.output)).toMatch(/outside|traversal|invalid/i);
  });

  it(
    "rejects a sibling-directory traversal that textually shares the skill dir as a prefix " +
      "but does not actually resolve under it (e.g. '../greeter-evil/x' from 'greeter')",
    async () => {
      // Create a sibling directory "greeter-evil" next to "greeter" so that a naive
      // non-separator-aware prefix check (resolvedPath.startsWith(skill.dir)) would
      // incorrectly accept this path, since "/.../greeter-evil" textually starts with
      // "/.../greeter".
      const evilDir = resolve(FIXTURES_ROOT, "greeter-evil");
      mkdirSync(evilDir, { recursive: true });
      writeFileSync(resolve(evilDir, "x.js"), `console.log("should not run");`);

      const tool = createRunSkillScriptTool(skills);
      const result = await tool.execute(
        { skillName: "greeter", scriptRelativePath: "../greeter-evil/x.js", args: [] },
        { tenantId: "t", sessionId: "s" },
      );
      expect(result.isError).toBe(true);
      expect(String(result.output)).toMatch(/outside|traversal|invalid/i);
    },
  );
});
