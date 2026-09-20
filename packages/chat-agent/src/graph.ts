import { shallowMergeReducer, type GraphDefinition, type NodeContext, type NodeFn } from "@opentalos/core-graph";
import type { ModelProvider, ToolRegistry } from "@opentalos/core-types";
import { runModelWithTools } from "@opentalos/sdk";
import type { ChatState } from "./state.js";

const MAX_MEMORY_ENTRIES = 30;
const MAX_MEMORY_SUMMARY_CHARS = 3000;

/** 把该租户的记忆列表拼成一段紧凑摘要，追加进 system prompt。最多取 MAX_MEMORY_ENTRIES 条，且
 * 总长度超过 MAX_MEMORY_SUMMARY_CHARS 时从末尾截断——参考 Claude Code 的 MEMORY.md 200 行/25KB
 * 上限思路，按本仓库单租户记忆量小得多的实际情况按比例缩小。没有任何记忆时返回空字符串，不往
 * system prompt 里加空标题。 */
const MEMORY_DISCLAIMER = "\n（以上是历史对话中总结的信息，可能已过时；如与用户当前说法冲突，以当前对话为准）";

function buildMemorySummary(entries: { type: string; title: string }[]): string {
  if (entries.length === 0) return "";
  const lines = entries
    .slice(0, MAX_MEMORY_ENTRIES)
    .map((entry) => `- [${entry.type}] ${entry.title}`);
  // Truncate only the entry-list portion to a budget that reserves room for the disclaimer, then
  // always append the disclaimer afterward — so a run of long titles can never silently cut off
  // the "this may be stale" warning, which matters more than a bit of extra entry-list content.
  const header = "\n\n[已知用户信息]\n";
  const entryBudget = MAX_MEMORY_SUMMARY_CHARS - header.length - MEMORY_DISCLAIMER.length;
  let entryList = lines.join("\n");
  if (entryList.length > entryBudget) {
    entryList = entryList.slice(0, Math.max(0, entryBudget));
  }
  return header + entryList + MEMORY_DISCLAIMER;
}

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

export type ListMemoriesForSummary = (tenantId: string) => Promise<{ type: string; title: string }[]>;

function buildRespondNode(
  modelProvider: ModelProvider,
  toolRegistry: ToolRegistry,
  listMemories?: ListMemoriesForSummary,
): NodeFn<ChatState> {
  return async function* respond(state: ChatState, ctx: NodeContext) {
    // Memory is a nice-to-have layered on top of core chat functionality, not load-bearing (same
    // posture as apps/worker's onRunDone extraction and consolidation sweep, both of which also
    // swallow their own errors) — a transient failure loading the summary must never fail the
    // whole conversation turn, so this falls back to an empty summary rather than propagating.
    let memoryEntries: { type: string; title: string }[] = [];
    if (listMemories) {
      try {
        memoryEntries = await listMemories(ctx.tenant.tenantId);
      } catch (error) {
        console.error(
          `chat-agent: failed to load memory summary for tenant "${ctx.tenant.tenantId}": ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    }
    const systemPrompt = SYSTEM_PROMPT + buildMemorySummary(memoryEntries);
    const { finalText, messages, reasoningText } = yield* runModelWithTools(
      modelProvider,
      toolRegistry.list(),
      [
        { role: "system", content: systemPrompt },
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

export function buildChatAgentGraph(
  modelProvider: ModelProvider,
  toolRegistry: ToolRegistry,
  listMemories?: ListMemoriesForSummary,
): GraphDefinition<ChatState> {
  return {
    id: "chat-agent",
    entryNode: "respond",
    nodes: { respond: buildRespondNode(modelProvider, toolRegistry, listMemories), confirm, respondFinal },
    edges: [
      { from: "respond", to: "confirm", condition: (state) => !!state.requiresApproval },
      { from: "respond", to: "respondFinal", condition: (state) => !state.requiresApproval },
      { from: "confirm", to: "respondFinal" },
    ],
    reducer: shallowMergeReducer,
  };
}
