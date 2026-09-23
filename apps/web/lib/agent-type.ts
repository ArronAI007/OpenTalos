export const AGENT_TYPE_KEY = "opentalos.agentType";
export const DEFAULT_AGENT_TYPE = "react";

// 与后端 packages/agents/builder.py 的 AGENT_TYPES 保持一致；非法值（如被手动篡改的
// localStorage）回退默认类型，避免把坏值直接发给 createTask。
const KNOWN_AGENT_TYPES = ["toolcall", "react", "reflection", "plan_execute"] as const;

export function readAgentType(): string {
  const stored = localStorage.getItem(AGENT_TYPE_KEY);
  return stored !== null && (KNOWN_AGENT_TYPES as readonly string[]).includes(stored)
    ? stored
    : DEFAULT_AGENT_TYPE;
}
