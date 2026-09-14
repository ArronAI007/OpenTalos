import { InMemoryToolRegistry } from "@opentalos/tool-registry";
import { createLoadSkillTool, createRunSkillScriptTool, type Skill } from "@opentalos/skills";
import { lookupExchangeRateTool, webSearchTool } from "./tools.js";

export interface ChatAgentToolRegistryOptions {
  /** The active MODEL_PROVIDER (e.g. process.env.MODEL_PROVIDER). Only "kimi" gets $web_search
   * registered — it's a Moonshot-hosted builtin tool (see tools.ts), so declaring it against any
   * other provider would just be sending a tool type that provider doesn't understand. */
  modelProvider?: string;
  /** Discovered skills (see @opentalos/skills's loadSkills) to expose via load_skill/
   * run_skill_script. Omitted or empty means neither tool is registered at all — no point
   * offering "load a skill" when there are none to load. */
  skills?: Skill[];
}

/** A fresh, independent tool registry per call — callers (apps/worker, apps/api) each get their
 * own instance rather than sharing one across processes or across GraphRegistry registrations. */
export function createChatAgentToolRegistry(options: ChatAgentToolRegistryOptions = {}): InMemoryToolRegistry {
  const registry = new InMemoryToolRegistry();
  registry.register(lookupExchangeRateTool);
  if (options.modelProvider === "kimi") {
    registry.register(webSearchTool);
  }
  if (options.skills && options.skills.length > 0) {
    registry.register(createLoadSkillTool(options.skills));
    registry.register(createRunSkillScriptTool(options.skills));
  }
  return registry;
}
