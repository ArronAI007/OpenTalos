export type ChatEvent =
  | { type: "delta"; text: string }
  | { type: "tool_call"; name: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; name: string; result: string; ok: boolean }
  | { type: "done"; reply: string }
  | { type: "error"; message: string };

export type UiMessage =
  | { kind: "user" | "assistant"; id: string; content: string; streaming?: boolean }
  | { kind: "tool"; id: string; name: string; arguments: Record<string, unknown>; result?: string; ok?: boolean }
  | { kind: "error"; id: string; content: string };

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

export function reduceChatEvent(prev: UiMessage[], event: ChatEvent): UiMessage[] {
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
        return [...rest, { ...current, content: event.reply, streaming: false }];
      }
      return [...rest, { id: nextUiId(rest), kind: "assistant", content: event.reply, streaming: false }];
    }
    case "error": {
      // 终结所有 streaming 泡：error 与 done 互斥，不终结的话残留泡会把下一轮回复合流进去。
      const finalized = prev.map((m) =>
        m.kind === "assistant" && m.streaming ? { ...m, streaming: false } : m,
      );
      return [...finalized, { id: nextUiId(finalized), kind: "error", content: event.message }];
    }
  }
}
