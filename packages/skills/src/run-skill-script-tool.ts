import { realpathSync } from "node:fs";
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

      // The lexical check above is purely textual (`path.resolve` never touches the filesystem or
      // follows symlinks), so it is NOT sufficient on its own: a symlink placed *inside* skill.dir
      // (whose name contains no ".." at all) can still point anywhere on disk, pass the check
      // above, and then have its real target followed and mounted by the sandbox's read-only bind
      // mount. Resolve BOTH sides through the real filesystem (following symlinks) and re-check the
      // prefix against those real paths, so a symlink escape is caught even though the textual path
      // never left skill.dir.
      let realSkillDir: string;
      let realResolvedPath: string;
      try {
        realSkillDir = realpathSync(skill.dir);
        realResolvedPath = realpathSync(resolvedPath);
      } catch (error) {
        return {
          id: "",
          output: `Invalid scriptRelativePath: "${scriptRelativePath}" does not resolve to a real file for skill "${skillName}" (${error instanceof Error ? error.message : String(error)}).`,
          isError: true,
        };
      }
      const realSkillDirWithSep = realSkillDir.endsWith(sep) ? realSkillDir : realSkillDir + sep;
      if (!realResolvedPath.startsWith(realSkillDirWithSep)) {
        return {
          id: "",
          output: `Invalid scriptRelativePath: "${scriptRelativePath}" resolves (after following symlinks) outside skill "${skillName}"'s own directory (path traversal rejected).`,
          isError: true,
        };
      }

      // Use the already symlink-resolved real path for the mount itself (rather than the lexical
      // `resolvedPath`, or re-resolving later) so there is no TOCTOU window between this check and
      // what actually gets bind-mounted into the sandbox.
      //
      // `runSandboxedScript` can throw (e.g. oversized `inputText` rejected up front, or an
      // unexpected sandbox-layer failure such as a Docker/container error). This tool's own
      // contract is to never let a raw internal exception escape its `execute()` — regardless of
      // whatever generic catch-all a caller (like the tool registry) also happens to have — so we
      // catch here and translate into a clean, actionable `isError` result rather than relying on
      // an outer layer to paper over an internal detail leaking through (e.g. `/bin/sh`, a stack
      // trace).
      let result;
      try {
        result = await runSandboxedScript({
          scriptHostPath: realResolvedPath,
          args: args ?? [],
          inputText: input,
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        // Both of these are known, actionable failures the caller (the model, or a developer
        // reading logs) can actually fix — shrink the input, or use a supported script extension —
        // so surface them verbatim instead of flattening them into the generic "unexpected
        // internal error" message below, which is reserved for truly unexpected sandbox-layer
        // failures.
        const isInputTooLarge = /input.*too large/i.test(message);
        const isUnsupportedScriptType = /unsupported script type/i.test(message);
        return {
          id: "",
          output:
            isInputTooLarge || isUnsupportedScriptType
              ? `Script "${scriptRelativePath}" for skill "${skillName}" could not run: ${message}`
              : `Script "${scriptRelativePath}" for skill "${skillName}" failed to run in the sandbox due to an unexpected internal error.`,
          isError: true,
        };
      }

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
