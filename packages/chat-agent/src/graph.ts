import { shallowMergeReducer, type GraphDefinition, type NodeFn } from "@opentalos/core-graph";
import type { ModelProvider, ToolRegistry } from "@opentalos/core-types";
import { runModelWithTools } from "@opentalos/sdk";
import type { ChatState } from "./state.js";

const SYSTEM_PROMPT =
  "你是 OpenTalos 的聊天助手。如果用户询问汇率相关问题，使用 lookup_exchange_rate 工具查询后再回答；否则直接自然地回复。";

function buildRespondNode(modelProvider: ModelProvider, toolRegistry: ToolRegistry): NodeFn<ChatState> {
  return async function* respond(state) {
    const { finalText, messages } = yield* runModelWithTools(modelProvider, toolRegistry.list(), [
      { role: "system", content: SYSTEM_PROMPT },
      { role: "user", content: state.message },
    ]);
    // Only turns that actually called a tool (e.g. looked up an exchange rate) go through human
    // approval before their result is sent — plain conversational replies skip the HITL pause
    // entirely, so an ordinary "你好" doesn't stop and wait for a click every time.
    const usedTool = messages.some((message) => message.role === "tool");
    return { searchResult: finalText, usedTool };
  };
}

const confirm: NodeFn<ChatState> = async function* confirm() {
  const resume = yield { type: "awaiting_approval", reason: "是否把这个查询结果发给用户？" };
  const approved = resume?.type === "approval" ? resume.approved : false;
  return { approved };
};

const respondFinal: NodeFn<ChatState> = async function* respondFinal(state) {
  const reply = state.usedTool
    ? state.approved
      ? state.searchResult ?? ""
      : "好的，我不会发送这条回复。"
    : state.searchResult ?? "";
  return { reply };
};

export function buildChatAgentGraph(modelProvider: ModelProvider, toolRegistry: ToolRegistry): GraphDefinition<ChatState> {
  return {
    id: "chat-agent",
    entryNode: "respond",
    nodes: { respond: buildRespondNode(modelProvider, toolRegistry), confirm, respondFinal },
    edges: [
      { from: "respond", to: "confirm", condition: (state) => !!state.usedTool },
      { from: "respond", to: "respondFinal", condition: (state) => !state.usedTool },
      { from: "confirm", to: "respondFinal" },
    ],
    reducer: shallowMergeReducer,
  };
}
