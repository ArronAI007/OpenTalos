import { shallowMergeReducer, type GraphDefinition, type NodeFn } from "@opentalos/core-graph";
import type { ChatState } from "./state.js";

const plan: NodeFn<ChatState> = async function* plan() {
  // No yield: a plain synchronous planning step, included so the trace timeline shows a
  // node_enter/node_exit pair that isn't a tool call or a pause.
  return {};
};

const search: NodeFn<ChatState> = async function* search() {
  const resume = yield {
    type: "awaiting_tool",
    toolCall: { id: `lookup-${Date.now()}`, name: "lookup_exchange_rate", input: { pair: "USD/CNY" } },
  };
  const searchResult = resume?.type === "tool_result" ? String(resume.result.output) : "";
  return { searchResult };
};

const confirm: NodeFn<ChatState> = async function* confirm() {
  const resume = yield { type: "awaiting_approval", reason: "是否把这个查询结果发给用户？" };
  const approved = resume?.type === "approval" ? resume.approved : false;
  return { approved };
};

const respond: NodeFn<ChatState> = async function* respond(state) {
  const reply = state.approved ? `根据查询结果：${state.searchResult}` : "好的，我不会发送这条回复。";
  return { reply };
};

export function buildChatDemoAgentGraph(): GraphDefinition<ChatState> {
  return {
    id: "chat-demo-agent",
    entryNode: "plan",
    nodes: { plan, search, confirm, respond },
    edges: [
      { from: "plan", to: "search" },
      { from: "search", to: "confirm" },
      { from: "confirm", to: "respond" },
    ],
    reducer: shallowMergeReducer,
  };
}
