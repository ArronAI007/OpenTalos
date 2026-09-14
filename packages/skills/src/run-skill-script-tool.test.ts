import { resolve } from "node:path";
import { mkdirSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { describe, expect, it } from "vitest";
import { MAX_INPUT_TEXT_BYTES } from "@opentalos/sandbox";
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

  it(
    "rejects a symlink inside the skill dir that points outside it, without executing or " +
      "returning the linked-to file's content (real Docker bind-mount symlink-escape bypass)",
    async () => {
      // Distinctive secret content living OUTSIDE the skill directory entirely. If the guard's
      // lexical-only prefix check is bypassed, the sandbox's read-only bind mount follows the
      // symlink and this content would end up executed (and/or its text observable in output).
      const outsideSecretPath = resolve(FIXTURES_ROOT, "outside-secret.js");
      writeFileSync(outsideSecretPath, `console.log("PWNED-VIA-SYMLINK-ESCAPE");`);

      // The symlink lives INSIDE the skill's own directory — its name never contains "..", so a
      // purely lexical `path.resolve(skill.dir, name)` + string-prefix check sees it as textually
      // "inside" skill.dir and lets it straight through, even though it really points elsewhere.
      const symlinkPath = resolve(SKILL_DIR, "innocuous-link.js");
      symlinkSync(outsideSecretPath, symlinkPath);

      const tool = createRunSkillScriptTool(skills);
      const result = await tool.execute(
        { skillName: "greeter", scriptRelativePath: "innocuous-link.js", args: [] },
        { tenantId: "t", sessionId: "s" },
      );

      expect(result.isError).toBe(true);
      expect(String(result.output)).toMatch(/outside|traversal|invalid/i);
      expect(String(result.output)).not.toContain("PWNED-VIA-SYMLINK-ESCAPE");
    },
    30_000,
  );

  it("returns a clean isError result (never a raw exception) when the sandbox layer rejects oversized input", async () => {
    const tool = createRunSkillScriptTool(skills);
    const oversizedInput = "a".repeat(MAX_INPUT_TEXT_BYTES + 1);

    // execute() must never throw here — it should catch runSandboxedScript's rejection itself and
    // translate it into a clean tool result, independent of whatever generic catch-all the tool
    // registry that calls this tool also happens to have.
    const result = await tool.execute(
      { skillName: "greeter", scriptRelativePath: "greet.js", args: [], input: oversizedInput },
      { tenantId: "t", sessionId: "s" },
    );

    expect(result.isError).toBe(true);
    expect(String(result.output)).toMatch(/too large/i);
    // Must not leak the sandbox layer's low-level implementation details.
    expect(String(result.output)).not.toContain("/bin/sh");
    expect(String(result.output)).not.toMatch(/at runSandboxedScript|\.ts:\d+:\d+/);
  });
});
