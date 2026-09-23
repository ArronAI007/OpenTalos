"use client";

import { useCallback, useEffect, useState } from "react";
import { API_URL, listMessages, type StoredMessage } from "./api";
import { nextUiId, reduceChatEvent, type UiMessage } from "./chat-events";
import { postSse } from "./sse";

function fromStored(row: StoredMessage): UiMessage {
  if (row.kind === "tool") {
    const parsed = JSON.parse(row.content) as { name: string; arguments: Record<string, unknown>; result: string; ok: boolean };
    return { id: `row-${row.id}`, kind: "tool", ...parsed };
  }
  if (row.kind === "user" || row.kind === "assistant") {
    return { id: `row-${row.id}`, kind: row.kind, content: row.content };
  }
  return { id: `row-${row.id}`, kind: "error", content: `未知消息类型: ${row.kind}` };
}

export function useChat(taskId: string) {
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void listMessages(taskId)
      .then((rows) =>
        // 历史 GET 与自动发送 effect 同在挂载时触发：若发送先于历史返回产生乐观用户泡，
        // 历史返回（新任务为空数组）会覆盖掉乐观泡。此时若已有任何 live 消息，说明更可能
        // 属于同任务新对话，丢弃该历史快照；空历史场景 prev 本就为空，不受影响。
        // 对称的另一面：打开旧任务后、历史返回前秒发消息时，本守卫会让本次挂载暂看不到
        // 历史（仅视图层缺失，服务端数据仍在，刷新即恢复）；改用 id 合并会在 StrictMode
        // effect 双跑下重复历史行、需额外去重，当前写法幂等，故按 YAGNI 保持现状。
        setMessages((prev) => (prev.length > 0 ? prev : rows.map(fromStored))),
      )
      .catch(() => setMessages([{ id: nextUiId([]), kind: "error", content: "历史消息加载失败，请刷新重试" }]));
  }, [taskId]);

  const send = useCallback(
    async (text: string) => {
      const content = text.trim();
      if (!content) return;
      setMessages((prev) => [...prev, { id: nextUiId(prev), kind: "user", content }]);
      setBusy(true);
      try {
        await postSse(
          `${API_URL}/api/tasks/${taskId}/messages`,
          { content },
          (event) => setMessages((prev) => reduceChatEvent(prev, event)),
        );
      } catch (error) {
        setMessages((prev) => [...prev, { id: nextUiId(prev), kind: "error", content: String(error) }]);
      } finally {
        setBusy(false);
      }
    },
    [taskId],
  );

  return { messages, busy, send };
}
