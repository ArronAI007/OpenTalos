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
      .then((rows) => setMessages(rows.map(fromStored)))
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
