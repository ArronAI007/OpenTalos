export type ChatEvent =
  | { type: "delta"; text: string }
  | { type: "reasoning"; text: string }
  | { type: "tool_call"; name: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; name: string; result: string; ok: boolean }
  | { type: "done"; reply: string }
  | { type: "error"; message: string }
  // user 行落库后服务端回送：把 live-N user 泡换成 row-N 身份（删除轮次需要服务端 id）。
  | { type: "user_stored"; id: number; created_at: string }
  // 回复完成后服务端追加的跟进问题推荐（done 之后、流尾；仅出现在本会话，不落库）。
  | { type: "suggestions"; items: string[] };

export type UiMessage =
  // completedAt（epoch ms）：assistant 回复定稿时刻（done/停止/error 定稿）或历史行 created_at；
  // 渲染层动作行（复制 + 时间）据此显示回复时间。user 历史行同样带，live user 暂无需求不填。
  | {
      kind: "user" | "assistant";
      id: string;
      content: string;
      streaming?: boolean;
      completedAt?: number;
    }
  | { kind: "tool"; id: string; name: string; arguments: Record<string, unknown>; result?: string; ok?: boolean }
  | { kind: "error"; id: string; content: string }
  // 思维链（kimi-k3 等推理模型的 reasoning_content 增量）：session-only 反馈行，不落库；
  // 首个正文 delta（或 done/停止）到达即定稿，渲染层把它并入同轮 assistant 块——品牌头一轮一个。
  | { kind: "reasoning"; id: string; content: string; streaming?: boolean }
  // 停止提示是纯本地 UI 行（不来自服务端、不入库）：kind 只携带语义，文案在渲染层（MessageList）。
  | { kind: "stopped"; id: string }
  // 跟进问题推荐：本会话 UI 行（服务端 done 后追加；不落库、不进历史）。
  // 下一条用户消息发出即过时清除（dropSuggestions），点击条目直接发送。
  | { kind: "suggestions"; id: string; items: string[] };

type AssistantMessage = { kind: "assistant"; id: string; content: string; streaming?: boolean };
type ReasoningMessage = { kind: "reasoning"; id: string; content: string; streaming?: boolean };

// 本会话新产生的消息用 live-N 命名空间；历史行在 fromStored 用 row-N，互不碰撞。
export function nextUiId(prev: UiMessage[]): string {
  const maxLive = Math.max(
    0,
    ...prev
      .map((m) => /^live-(\d+)$/.exec(m.id)?.[1])
      .filter((n): n is string => n !== undefined)
      .map(Number),
  );
  return `live-${maxLive + 1}`;
}

export function parseSseBlock(block: string): ChatEvent | null {
  const line = block.trim();
  if (!line.startsWith("data:")) return null;
  return JSON.parse(line.slice(5).trim()) as ChatEvent;
}

// 把所有 streaming 助理泡定稿（内容保留、摘掉 streaming 标记、补 completedAt 时间戳），
// 用户主动停止（AbortError）与 error 事件共用。无 streaming 泡时原样返回引用，
// 让 setMessages 走 React bail-out 快路径（不触发多余渲染）。
// now 默认 Date.now()，测试注入固定值保持确定性。
export function finalizeStreaming(prev: UiMessage[], now = Date.now()): UiMessage[] {
  const isStreaming = (m: UiMessage) => (m.kind === "assistant" || m.kind === "reasoning") && m.streaming;
  if (!prev.some(isStreaming)) return prev;
  return prev.map((m) => {
    if (!isStreaming(m)) return m;
    return m.kind === "assistant" ? { ...m, streaming: false, completedAt: now } : { ...m, streaming: false };
  });
}

// 流式思维链定稿：首个正文 delta / done 到达即落地（streaming→false）。
// 无流式思维链时返回原引用——后续 delta 不会重复制造 map 开销，也不触发多余渲染。
function settleReasoning(prev: UiMessage[]): UiMessage[] {
  if (!prev.some((m) => m.kind === "reasoning" && m.streaming)) return prev;
  return prev.map((m) => (m.kind === "reasoning" && m.streaming ? { ...m, streaming: false } : m));
}

// 「正在思考…」占位的显示条件：本轮已发出（busy）但还没有任何流式气泡（思维链或正文）。
// 覆盖的是请求→首个 SSE chunk 之间的空白；一旦思维链开始滚动即让位。
export function shouldShowThinkingHint(messages: UiMessage[], busy: boolean): boolean {
  if (!busy) return false;
  return !messages.some((m) => (m.kind === "assistant" || m.kind === "reasoning") && m.streaming);
}

// 停止流式后追加提示行（幂等：本会话已有 live 提示则返回原引用，防止双击停止叠加）。
// 幂等只查 live-N，与 dropStoppedNotice 同口径：row-N 停止行是历史轮次痕迹，
// 它的存在不代表本轮已提示——若查任意 stopped，历史行会把本轮提示短路掉。
export function appendStoppedNotice(prev: UiMessage[]): UiMessage[] {
  if (prev.some((m) => m.kind === "stopped" && m.id.startsWith("live-"))) return prev;
  return [...prev, { id: nextUiId(prev), kind: "stopped" }];
}

// 下一条用户消息发出时清掉本会话内的提示（"发送消息以继续"已失去时效）；
// 仅清 live-N 行——row-N 停止行是服务端持久化的轮次痕迹（断连兜底落库），发送时应保留；
// 无提示时返回原引用，不触发多余渲染。
export function dropStoppedNotice(prev: UiMessage[]): UiMessage[] {
  if (!prev.some((m) => m.kind === "stopped" && m.id.startsWith("live-"))) return prev;
  return prev.filter((m) => m.kind !== "stopped" || !m.id.startsWith("live-"));
}

// 发送新消息时清掉上一轮的跟进问题推荐（新一轮会有新推荐，旧建议已过时）；
// 建议行全部 live（不落库），整类清除；无建议时返回原引用。
export function dropSuggestions(prev: UiMessage[]): UiMessage[] {
  if (!prev.some((m) => m.kind === "suggestions")) return prev;
  return prev.filter((m) => m.kind !== "suggestions");
}

// 删除整轮问答：目标 user 行 + 其后直到下一条 user 行之前的所有行（assistant/tool/stopped）。
// 无目标或目标不是 user 行时返回原引用（不触发多余渲染）。
export function dropTurn(prev: UiMessage[], messageId: string): UiMessage[] {
  const start = prev.findIndex((m) => m.id === messageId);
  if (start === -1 || prev[start].kind !== "user") return prev;
  let end = prev.length;
  for (let i = start + 1; i < prev.length; i++) {
    if (prev[i].kind === "user") { end = i; break; }
  }
  return [...prev.slice(0, start), ...prev.slice(end)];
}

// now 仅用于 done/error 定稿时给 assistant 泡落 completedAt（默认 Date.now()，测试注入固定值）
export function reduceChatEvent(prev: UiMessage[], event: ChatEvent, now = Date.now()): UiMessage[] {
  switch (event.type) {
    case "user_stored": {
      // user 落库回执：替换本会话最后一条 live-N user 泡（row-N 身份 + 服务端写入时间校准）。
      // 从尾部找——同一连接上只有刚发出的那条泡可能是 live user（重放/历史行都是 row-N）。
      let at = -1;
      for (let i = prev.length - 1; i >= 0; i--) {
        if (prev[i].kind === "user" && prev[i].id.startsWith("live-")) { at = i; break; }
      }
      if (at === -1) return prev;
      const message = prev[at];
      if (message.kind !== "user") return prev; // 索引访问不保留循环内 narrowing，这里收窄 + 防御
      return [
        ...prev.slice(0, at),
        { ...message, id: `row-${event.id}`, completedAt: Date.parse(event.created_at) },
        ...prev.slice(at + 1),
      ];
    }
    case "delta": {
      const calmed = settleReasoning(prev);
      const current = calmed.find(
        (m): m is AssistantMessage => m.kind === "assistant" && m.streaming === true,
      );
      const rest = calmed.filter((m) => m !== current);
      if (current) {
        return [...rest, { ...current, content: current.content + event.text, streaming: true }];
      }
      return [...rest, { id: nextUiId(rest), kind: "assistant", content: event.text, streaming: true }];
    }
    case "reasoning": {
      const current = prev.find(
        (m): m is ReasoningMessage => m.kind === "reasoning" && m.streaming === true,
      );
      const rest = prev.filter((m) => m !== current);
      if (current) {
        return [...rest, { ...current, content: current.content + event.text, streaming: true }];
      }
      return [...rest, { id: nextUiId(rest), kind: "reasoning", content: event.text, streaming: true }];
    }
    case "tool_call":
      return [...prev, { id: nextUiId(prev), kind: "tool", name: event.name, arguments: event.arguments, result: undefined }];
    case "tool_result": {
      const at = prev.findIndex(
        (m) => m.kind === "tool" && m.name === event.name && m.result === undefined,
      );
      if (at === -1) return prev;
      const message = prev[at];
      if (message.kind !== "tool") return prev;
      return [...prev.slice(0, at), { ...message, result: event.result, ok: event.ok }, ...prev.slice(at + 1)];
    }
    case "done": {
      const calmed = settleReasoning(prev);
      const current = calmed.find(
        (m): m is AssistantMessage => m.kind === "assistant" && m.streaming === true,
      );
      const rest = calmed.filter((m) => m !== current);
      if (current) {
        return [...rest, { ...current, content: event.reply, streaming: false, completedAt: now }];
      }
      return [...rest, { id: nextUiId(rest), kind: "assistant", content: event.reply, streaming: false, completedAt: now }];
    }
    case "error": {
      // 终结所有 streaming 泡：error 与 done 互斥，不终结的话残留泡会把下一轮回复合流进去。
      const finalized = finalizeStreaming(prev, now);
      return [...finalized, { id: nextUiId(finalized), kind: "error", content: event.message }];
    }
    case "suggestions": {
      // 一轮至多一次；防御性替换旧建议行而非叠加
      const rest = prev.filter((m) => m.kind !== "suggestions");
      return [...rest, { id: nextUiId(rest), kind: "suggestions", items: event.items }];
    }
  }
}
