import { shallowMergeReducer, type GraphDefinition, type NodeContext, type NodeFn } from "@opentalos/core-graph";
import type { ModelProvider, ToolRegistry } from "@opentalos/core-types";
import { runModelWithTools } from "@opentalos/sdk";
import type { ChatState } from "./state.js";

// Deliberately tool-agnostic: which tool (if any) fits a given message is decided by the model
// reading each tool's own `description`/`inputSchema` (passed in via toolRegistry.list(), see
// below) — not by naming tools here. Adding a new tool should never require editing this prompt;
// only genuinely global policy (tone, when to prefer a tool over guessing) belongs here.
const SYSTEM_PROMPT =
  "你是 OpenTalos 的聊天助手。如果现有工具能帮助更好地回答用户的问题，请调用相应工具；否则直接自然地回复。" +
  "无论用户使用什么语言提问，你的思考过程（reasoning）和最终回复都必须全程使用中文，禁止使用英文或其他语言思考。";

// The system prompt alone doesn't reliably hold: a reasoning model's thinking trace is known to
// follow instructions less strictly than its final answer (it's an internal scratchpad, not the
// user-facing output the model is most optimized to get "right"), and reasoning models in general
// weight instructions closer to the end of the context more heavily than a distant system prompt —
// confirmed empirically against the real Kimi K3 model: the exact same Chinese input sometimes
// produced English reasoning with only the system-prompt instruction in place. Repeating the
// instruction right next to the user's own message (not replacing the system prompt, which still
// matters for every later message and any earlier turns) measurably raises the odds it's honored,
// even though — per Kimi K3's own docs, which fix temperature/top_p and don't expose a way to force
// this deterministically — no prompting-only approach can guarantee it 100%.
const REASONING_LANGUAGE_REMINDER = "\n\n（提醒：你接下来的思考过程和回复都必须全程使用中文。）";

function buildRespondNode(modelProvider: ModelProvider, toolRegistry: ToolRegistry): NodeFn<ChatState> {
  return async function* respond(state: ChatState, ctx: NodeContext) {
    const { finalText, messages, reasoningText } = yield* runModelWithTools(
      modelProvider,
      toolRegistry.list(),
      [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: state.message + REASONING_LANGUAGE_REMINDER, images: state.images },
      ],
      undefined,
      ctx.signal,
      ctx.steer,
    );
    // Only turns that called a tool explicitly marked `dangerous` in its own ToolDefinition (see
    // core-types.ts) go through human approval before their result is sent — an ordinary read-only
    // lookup or computation (load_skill, run_skill_script, $web_search, ...) skips the HITL pause
    // entirely, so using one of those doesn't stop and wait for a click every time. Collected from
    // every assistant turn's toolCalls (not merely "does a tool message exist") so this is driven
    // by which specific tool(s) were actually called.
    const calledToolNames = messages.flatMap((message) => message.toolCalls?.map((call) => call.name) ?? []);
    const requiresApproval = calledToolNames.some((name) => toolRegistry.get(name)?.definition.dangerous);
    return { searchResult: finalText, requiresApproval, reasoningText };
  };
}

const confirm: NodeFn<ChatState> = async function* confirm() {
  const resume = yield { type: "awaiting_approval", reason: "是否把这个查询结果发给用户？" };
  const approved = resume?.type === "approval" ? resume.approved : false;
  return { approved };
};

const respondFinal: NodeFn<ChatState> = async function* respondFinal(state) {
  const reply = state.requiresApproval
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
      { from: "respond", to: "confirm", condition: (state) => !!state.requiresApproval },
      { from: "respond", to: "respondFinal", condition: (state) => !state.requiresApproval },
      { from: "confirm", to: "respondFinal" },
    ],
    reducer: shallowMergeReducer,
  };
}
