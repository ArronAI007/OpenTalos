export type ChatEvent =
  | { type: "delta"; text: string }
  | { type: "tool_call"; name: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; name: string; result: string; ok: boolean }
  | { type: "done"; reply: string }
  | { type: "error"; message: string };

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
  // 停止提示是纯本地 UI 行（不来自服务端、不入库）：kind 只携带语义，文案在渲染层（MessageList）。
  | { kind: "stopped"; id: string };

type AssistantMessage = { kind: "assistant"; id: string; content: string; streaming?: boolean };

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
  if (!prev.some((m) => m.kind === "assistant" && m.streaming)) return prev;
  return prev.map((m) =>
    m.kind === "assistant" && m.streaming ? { ...m, streaming: false, completedAt: now } : m,
  );
}

// 停止流式后追加提示行（幂等：已存在则返回原引用，防止双击停止叠加）
export function appendStoppedNotice(prev: UiMessage[]): UiMessage[] {
  if (prev.some((m) => m.kind === "stopped")) return prev;
  return [...prev, { id: nextUiId(prev), kind: "stopped" }];
}

// 下一条用户消息发出时清掉本会话内的提示（"发送消息以继续"已失去时效）；
// 仅清 live-N 行——row-N 停止行是服务端持久化的轮次痕迹（断连兜底落库），发送时应保留；
// 无提示时返回原引用，不触发多余渲染。
export function dropStoppedNotice(prev: UiMessage[]): UiMessage[] {
  if (!prev.some((m) => m.kind === "stopped" && m.id.startsWith("live-"))) return prev;
  return prev.filter((m) => m.kind !== "stopped" || !m.id.startsWith("live-"));
}

// now 仅用于 done/error 定稿时给 assistant 泡落 completedAt（默认 Date.now()，测试注入固定值）
export function reduceChatEvent(prev: UiMessage[], event: ChatEvent, now = Date.now()): UiMessage[] {
  switch (event.type) {
    case "delta": {
      const current = prev.find(
        (m): m is AssistantMessage => m.kind === "assistant" && m.streaming === true,
      );
      const rest = prev.filter((m) => m !== current);
      if (current) {
        return [...rest, { ...current, content: current.content + event.text, streaming: true }];
      }
      return [...rest, { id: nextUiId(rest), kind: "assistant", content: event.text, streaming: true }];
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
      const current = prev.find(
        (m): m is AssistantMessage => m.kind === "assistant" && m.streaming === true,
      );
      const rest = prev.filter((m) => m !== current);
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
  }
}
