import { shallowMergeReducer, type GraphDefinition, type NodeFn } from "@opentalos/core-graph";
import type { ModelProvider, ToolRegistry } from "@opentalos/core-types";
import { runModelWithTools } from "@opentalos/sdk";
import type { ChatState } from "./state.js";

const SYSTEM_PROMPT =
  "你是 OpenTalos 的聊天助手。如果用户询问汇率相关问题，使用 lookup_exchange_rate 工具查询后再回答；否则直接自然地回复。";

function buildRespondNode(modelProvider: ModelProvider, toolRegistry: ToolRegistry): NodeFn<ChatState> {
  return async function* respond(state) {
    const { finalText } = yield* runModelWithTools(modelProvider, toolRegistry.list(), [
      { role: "system", content: SYSTEM_PROMPT },
      { role: "user", content: state.message },
    ]);
    return { searchResult: finalText };
  };
}

const confirm: NodeFn<ChatState> = async function* confirm() {
  const resume = yield { type: "awaiting_approval", reason: "是否把这个查询结果发给用户？" };
  const approved = resume?.type === "approval" ? resume.approved : false;
  return { approved };
};

const respondFinal: NodeFn<ChatState> = async function* respondFinal(state) {
  const reply = state.approved ? state.searchResult ?? "" : "好的，我不会发送这条回复。";
  return { reply };
};

export function buildChatAgentGraph(modelProvider: ModelProvider, toolRegistry: ToolRegistry): GraphDefinition<ChatState> {
  return {
    id: "chat-agent",
    entryNode: "respond",
    nodes: { respond: buildRespondNode(modelProvider, toolRegistry), confirm, respondFinal },
    edges: [
      { from: "respond", to: "confirm" },
      { from: "confirm", to: "respondFinal" },
    ],
    reducer: shallowMergeReducer,
  };
}
