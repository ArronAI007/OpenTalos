import { InMemoryToolRegistry } from "@opentalos/tool-registry";
import { lookupExchangeRateTool } from "./tools.js";

/** A fresh, independent tool registry per call — callers (apps/worker, apps/api) each get their
 * own instance rather than sharing one across processes or across GraphRegistry registrations. */
export function createChatAgentToolRegistry(): InMemoryToolRegistry {
  const registry = new InMemoryToolRegistry();
  registry.register(lookupExchangeRateTool);
  return registry;
}
