import { shallowMergeReducer, type GraphDefinition, type NodeFn } from "@opentalos/core-graph";
import type { ModelProvider, ToolRegistry } from "@opentalos/core-types";
import { runModelWithTools } from "@opentalos/sdk";
import { buildSupervisorGraph } from "@opentalos/multi-agent";
import type { ResearchState } from "./state.js";

function buildResearcherNode(modelProvider: ModelProvider, toolRegistry: ToolRegistry): NodeFn<ResearchState> {
  return async function* researcher(state) {
    const { finalText } = yield* runModelWithTools(modelProvider, toolRegistry.list(), [
      { role: "system", content: "你是一名研究员。使用 search 工具收集关于研究主题的资料，收集完毕后用一段话总结发现。" },
      { role: "user", content: state.topic },
    ]);
    return { findings: [...state.findings, finalText], nextAgent: "writer" };
  };
}

function buildWriterNode(modelProvider: ModelProvider): NodeFn<ResearchState> {
  return async function* writer(state) {
    const { finalText } = yield* runModelWithTools(modelProvider, [], [
      { role: "system", content: "你是一名撰稿人。根据研究发现撰写一份简短的报告草稿。" },
      { role: "user", content: `主题：${state.topic}\n发现：${state.findings.join("; ")}` },
    ]);
    const resume = yield { type: "awaiting_approval", reason: "Please approve the draft before publishing" };
    if (resume?.type === "approval" && resume.approved) {
      return { draft: finalText, approved: true, nextAgent: "DONE" };
    }
    return { nextAgent: "researcher" };
  };
}

export function buildResearchAgentGraph(modelProvider: ModelProvider, toolRegistry: ToolRegistry): GraphDefinition<ResearchState> {
  return buildSupervisorGraph<ResearchState>({
    id: "research-agent",
    agents: { researcher: buildResearcherNode(modelProvider, toolRegistry), writer: buildWriterNode(modelProvider) },
    route: (state) => state.nextAgent,
    reducer: shallowMergeReducer,
  });
}
