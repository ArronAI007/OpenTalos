import type { Tool } from "@opentalos/core-types";
import type { Skill } from "./discovery.js";

/**
 * Builds the `load_skill` tool over a fixed, already-discovered set of skills. The tool
 * description enumerates every known skill by name and one-line description so the model can
 * decide which one to load without a separate "list skills" round trip.
 */
export function createLoadSkillTool(skills: Skill[]): Tool {
  const skillList = skills.map((s) => `- ${s.name}: ${s.description}`).join("\n");
  return {
    definition: {
      name: "load_skill",
      description:
        `Loads the full instructions for one of this agent's available skills, by exact name. ` +
        `Currently available skills:\n${skillList}`,
      inputSchema: {
        type: "object",
        properties: { name: { type: "string", description: "The exact skill name to load." } },
        required: ["name"],
      },
    },
    async execute(input) {
      const { name } = input as { name: string };
      const skill = skills.find((s) => s.name === name);
      if (!skill) {
        return {
          id: "",
          output: `Unknown skill "${name}". Known skills: ${skills.map((s) => s.name).join(", ")}`,
          isError: true,
        };
      }
      return { id: "", output: skill.content };
    },
  };
}
