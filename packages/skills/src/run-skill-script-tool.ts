import { isAbsolute, resolve, sep } from "node:path";
import type { Tool } from "@opentalos/core-types";
import { runSandboxedScript } from "@opentalos/sandbox";
import type { Skill } from "./discovery.js";

interface RunSkillScriptInput {
  skillName: string;
  scriptRelativePath: string;
  args?: string[];
  input?: string;
}

/**
 * Builds the `run_skill_script` tool over a fixed, already-discovered set of skills. Every
 * invocation is validated against the named skill's own directory before anything ever reaches
 * the sandbox: an unknown skill name, an absolute path, or any relative path that resolves
 * outside that skill's directory (including `..` segments that stay a textual prefix match
 * without actually landing inside the directory, e.g. a sibling `skill-evil` dir) is rejected
 * up front.
 */
export function createRunSkillScriptTool(skills: Skill[]): Tool {
  return {
    definition: {
      name: "run_skill_script",
      description:
        "Runs a helper script belonging to one of this agent's skills, inside an isolated sandbox " +
        "with no network access. Only use this after load_skill has told you the exact script path " +
        "and arguments to pass for that skill — never invent a script path.",
      inputSchema: {
        type: "object",
        properties: {
          skillName: { type: "string", description: "The exact skill name this script belongs to." },
          scriptRelativePath: {
            type: "string",
            description: "The script's path, relative to the skill's own directory, exactly as documented by that skill.",
          },
          args: { type: "array", items: { type: "string" }, description: "Command-line arguments for the script." },
          input: { type: "string", description: "Optional larger text payload the script reads from a fixed input file." },
        },
        required: ["skillName", "scriptRelativePath"],
      },
    },
    async execute(rawInput) {
      const { skillName, scriptRelativePath, args, input } = rawInput as RunSkillScriptInput;
      const skill = skills.find((s) => s.name === skillName);
      if (!skill) {
        return {
          id: "",
          output: `Unknown skill "${skillName}". Known skills: ${skills.map((s) => s.name).join(", ")}`,
          isError: true,
        };
      }

      if (isAbsolute(scriptRelativePath)) {
        return {
          id: "",
          output: `Invalid scriptRelativePath: absolute paths are not allowed for skill "${skillName}" (path traversal rejected).`,
          isError: true,
        };
      }

      const resolvedPath = resolve(skill.dir, scriptRelativePath);
      // Append a trailing separator before the prefix check so a sibling directory that merely
      // shares `skill.dir` as a textual prefix (e.g. resolving "greeter-evil" from "greeter")
      // cannot slip past a naive `startsWith(skill.dir)` check — that would accept
      // "/a/b/greeter-evil" as being "under" "/a/b/greeter" purely on string prefix, without ever
      // truly being inside its directory tree.
      const skillDirWithSep = skill.dir.endsWith(sep) ? skill.dir : skill.dir + sep;
      if (!resolvedPath.startsWith(skillDirWithSep)) {
        return {
          id: "",
          output: `Invalid scriptRelativePath: resolves outside skill "${skillName}"'s own directory (path traversal rejected).`,
          isError: true,
        };
      }

      const result = await runSandboxedScript({
        scriptHostPath: resolvedPath,
        args: args ?? [],
        inputText: input,
      });

      if (result.timedOut) {
        return { id: "", output: `Script "${scriptRelativePath}" for skill "${skillName}" timed out.`, isError: true };
      }
      if (result.exitCode !== 0) {
        return {
          id: "",
          output: `Script "${scriptRelativePath}" for skill "${skillName}" exited with code ${result.exitCode}. stderr: ${result.stderr}`,
          isError: true,
        };
      }
      return { id: "", output: result.stdout };
    },
  };
}
