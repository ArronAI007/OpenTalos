import { shallowMergeReducer, type NodeFn } from "@opentalos/core-graph";
import { buildSupervisorGraph } from "@opentalos/multi-agent";
import type { ResearchState } from "./state.js";

export const researcherNode: NodeFn<ResearchState> = async function* researcher(state) {
  const resume = yield {
    type: "awaiting_tool",
    toolCall: { id: `search-${Date.now()}`, name: "search", input: { query: state.topic } },
  };
  const output = resume?.type === "tool_result" ? resume.result.output : [];
  const findings = Array.isArray(output) ? (output as string[]) : [String(output)];
  return { findings, nextAgent: "writer" };
};

export const writerNode: NodeFn<ResearchState> = async function* writer(state) {
  const draft = `Report on ${state.topic}: ${state.findings.join("; ")}`;
  const resume = yield { type: "awaiting_approval", reason: "Please approve the draft before publishing" };
  if (resume?.type === "approval" && resume.approved) {
    return { draft, approved: true, nextAgent: "DONE" };
  }
  return { nextAgent: "researcher" };
};

export const researchAgentGraph = buildSupervisorGraph<ResearchState>({
  id: "research-agent",
  agents: { researcher: researcherNode, writer: writerNode },
  route: (state) => state.nextAgent,
  reducer: shallowMergeReducer,
});
