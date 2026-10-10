import type { UsageInfo } from "./usage";

export type ChatEvent =
  | { type: "delta"; text: string }
  | { type: "reasoning"; text: string }
  | { type: "tool_call"; name: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; name: string; result: string; ok: boolean }
  | { type: "done"; reply: string; usage?: UsageInfo }
  | { type: "error"; message: string }
  // user 行落库后服务端回送：把 live-N user 泡换成 row-N 身份（删除轮次需要服务端 id）。
  | { type: "user_stored"; id: number; created_at: string }
  // 回复完成后服务端追加的跟进问题推荐（done 之后、流尾；仅出现在本会话，不落库）。
  | { type: "suggestions"; items: string[] }
  // 首条消息时并行生成的概括性标题（成功才发，失败/超时不发——保留已落库的截断版兜底）。
  // 不对应任何聊天气泡，use-chat 里单独转发给侧栏任务列表，这里只负责"原样放行"。
  | { type: "title"; title: string }
  // 副作用工具需要人工确认：SSE 下发（带工具名/参数），前端渲染确认卡片；
  // 用户决定经 POST /approvals/{id} 回传，结果由 approval_resolved 再回流。
  | { type: "approval_required"; approval_id: string; name: string; arguments: Record<string, unknown> }
  | { type: "approval_resolved"; approval_id: string; approved: boolean }
  // 服务端显式停止该轮（重连时才会收到；正在连接的客户端已 abort 不看）：终结流式并加提示行。
  | { type: "stopped" }
  // 生成被运行中注入的纠偏打断：前端丢弃当前流式 assistant/reasoning 泡（将被重新生成）。
  | { type: "steer_interrupt" };

export type UiMessage =
  // completedAt（epoch ms）：assistant 回复定稿时刻（done/停止/error 定稿）或历史行 created_at；
  // 渲染层动作行（复制 + 时间）据此显示回复时间。user 历史行同样带，live user 暂无需求不填。
  | {
      kind: "user" | "assistant";
      id: string;
      content: string;
      streaming?: boolean;
      completedAt?: number;
      usage?: UsageInfo;
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
  | { kind: "suggestions"; id: string; items: string[] }
  // 副作用工具的人工确认卡片：pending 时显示允许/拒绝，resolve 后转为结果文案。
  | {
      kind: "approval";
      id: string;
      approvalId: string;
      name: string;
      arguments: Record<string, unknown>;
      status: "pending" | "approved" | "denied";
    };

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

export interface SseFrame {
  id?: number;
  event: ChatEvent;
}

// 解析一个 SSE 帧：可能有 `id: <n>` 行（重连续传用）与 `data: <json>` 行。
// 没有 data 行（如 `: keep-alive` comment 帧）返回 null。
export function parseSseBlock(block: string): SseFrame | null {
  let id: number | undefined;
  let data: string | undefined;
  for (const raw of block.split("\n")) {
    const line = raw.trim();
    if (line.startsWith("id:")) {
      const parsed = Number(line.slice(3).trim());
      if (Number.isInteger(parsed) && parsed >= 0) id = parsed;
    } else if (line.startsWith("data:")) {
      data = line.slice(5).trim();
    }
  }
  if (data === undefined) return null;
  return { id, event: JSON.parse(data) as ChatEvent };
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
// 末行守卫：回复泡已落定（done 已处理）而流未关闭的窗口（服务端在同一条流上算
// suggestions，busy 仍为 true）不能再冒占位——带着品牌头出现会读作「第二轮思考」。
export function shouldShowThinkingHint(messages: UiMessage[], busy: boolean): boolean {
  if (!busy) return false;
  if (messages.some((m) => (m.kind === "assistant" || m.kind === "reasoning") && m.streaming)) return false;
  const last = messages[messages.length - 1];
  // 末尾是思考单元（思路/工具动作）：已可见"正在思考…"与活动，不再叠加占位
  if (last?.kind === "reasoning" || last?.kind === "tool" || last?.kind === "approval") return false;
  return last?.kind !== "assistant" && last?.kind !== "stopped";
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

// 停止/断连时本地把未决审批卡片标为已拒绝（服务端也会按拒绝处理，但回流事件可能已随流断开）。
// 无 pending 审批时返回原引用，不触发多余渲染。
export function denyPendingApprovals(prev: UiMessage[]): UiMessage[] {
  if (!prev.some((m) => m.kind === "approval" && m.status === "pending")) return prev;
  return prev.map((m) => (m.kind === "approval" && m.status === "pending" ? { ...m, status: "denied" } : m));
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

// 附着运行中的流时用：只保留到最近一条 user 为止，丢弃其后由历史派生的行
// （assistant/tool/reasoning/stopped）——本轮内容改由 SSE 事件重建，避免与历史重复。
// 无 user 行时返回原引用。
export function dropTrailingTurn(prev: UiMessage[]): UiMessage[] {
  for (let i = prev.length - 1; i >= 0; i--) {
    if (prev[i].kind === "user") return prev.slice(0, i + 1);
  }
  return prev;
}

// 定位"目标消息所属那一轮"的起始 user 消息（从目标向前数到最近的 user）——重新生成据此找到
// 要重放的提问。目标不存在、或其前没有任何 user 时返回 null。
export function turnUserMessage(
  messages: UiMessage[],
  messageId: string,
): { id: string; kind: "user"; content: string } | null {
  const idx = messages.findIndex((m) => m.id === messageId);
  if (idx === -1) return null;
  for (let i = idx; i >= 0; i--) {
    const message = messages[i];
    if (message.kind === "user") {
      return { id: message.id, kind: "user", content: message.content };
    }
  }
  return null;
}

// 虚拟列表用：哪些消息真正渲染成一行。被并入相邻块（非思考单元起始行、已并入回复块的思考单元）
// 或被停止提示吸收的行会被排除，避免它们成为 0 高度 item 造成估算到实测的滚动抖动。
export function visibleIndexes(messages: UiMessage[]): number[] {
  const indexes: number[] = [];
  for (let index = 0; index < messages.length; index++) {
    const message = messages[index];
    if (message.kind === "reasoning" || message.kind === "tool") {
      const prev = index > 0 ? messages[index - 1] : undefined;
      if (prev !== undefined && (prev.kind === "reasoning" || prev.kind === "tool")) continue; // 非单元起始行
      let end = index;
      while (end < messages.length && (messages[end].kind === "reasoning" || messages[end].kind === "tool")) end++;
      if (end < messages.length && messages[end].kind === "assistant") continue; // 已并入回复块
      indexes.push(index);
      continue;
    }
    if (message.kind === "stopped") {
      const prevKind = messages[index - 1]?.kind;
      if (prevKind === "assistant" || prevKind === "reasoning" || prevKind === "tool") continue; // 已并入回复块
      indexes.push(index);
      continue;
    }
    indexes.push(index);
  }
  return indexes;
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
        return [
          ...rest,
          { ...current, content: event.reply, streaming: false, completedAt: now, usage: event.usage },
        ];
      }
      return [
        ...rest,
        { id: nextUiId(rest), kind: "assistant", content: event.reply, streaming: false, completedAt: now, usage: event.usage },
      ];
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
    case "title":
      // 不改变本页消息列表——侧栏任务列表的更新由 use-chat 的事件回调单独转发。
      return prev;
    case "approval_required":
      return [
        ...prev,
        {
          id: nextUiId(prev),
          kind: "approval",
          approvalId: event.approval_id,
          name: event.name,
          arguments: event.arguments,
          status: "pending",
        },
      ];
    case "approval_resolved": {
      const at = prev.findIndex((m) => m.kind === "approval" && m.approvalId === event.approval_id);
      if (at === -1) return prev;
      const message = prev[at];
      if (message.kind !== "approval") return prev;
      return [
        ...prev.slice(0, at),
        { ...message, status: event.approved ? "approved" : "denied" },
        ...prev.slice(at + 1),
      ];
    }
    case "stopped":
      // 服务端显式停止：终结流式泡并加"已停止"提示行（重连场景才会经过这里）。
      return appendStoppedNotice(finalizeStreaming(prev, now));
    case "steer_interrupt":
      // 生成被纠偏打断：丢弃当前流式 assistant/reasoning 泡（重跑时会重新生成）。
      return prev.filter((m) => !((m.kind === "assistant" || m.kind === "reasoning") && m.streaming));
  }
}
