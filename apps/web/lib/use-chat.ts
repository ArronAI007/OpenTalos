"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, listMessages, type StoredMessage } from "./api";
import {
  appendStoppedNotice,
  dropStoppedNotice,
  finalizeStreaming,
  nextUiId,
  reduceChatEvent,
  type UiMessage,
} from "./chat-events";
import { postSse } from "./sse";

function fromStored(row: StoredMessage): UiMessage {
  // 服务端断连兜底落的 stopped 标记行 → 渲染为"已停止 — 发送消息以继续"提示
  if (row.kind === "stopped") {
    return { id: `row-${row.id}`, kind: "stopped" };
  }
  if (row.kind === "tool") {
    const parsed = JSON.parse(row.content) as { name: string; arguments: Record<string, unknown>; result: string; ok: boolean };
    return { id: `row-${row.id}`, kind: "tool", ...parsed };
  }
  if (row.kind === "user" || row.kind === "assistant") {
    // 服务端 created_at 为无时区后缀的本地 ISO：Date.parse 按本地时区解析，与后端同机一致
    return { id: `row-${row.id}`, kind: row.kind, content: row.content, completedAt: Date.parse(row.created_at) };
  }
  return { id: `row-${row.id}`, kind: "error", content: `未知消息类型: ${row.kind}` };
}

export function useChat(taskId: string) {
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [busy, setBusy] = useState(false);
  // 当前流式请求的开关：stop() 通过它中断 fetch 读取循环
  const abortRef = useRef<AbortController | null>(null);

  // 仅清自己那次 send 建的控制器（busy 互斥已防并发，双保险不误清）
  const stop = useCallback(() => {
    // 先通知服务端置位停止信号（消费循环 ≤1s 响应、partial+stopped 标记落库），
    // 再 abort 本地读取。落库发生在服务端，与此后本地连接是否已断无关；
    // 单发即可，失败（如网络已断）也无妨——断连路径由同一个服务端兜底覆盖。
    void fetch(`${API_URL}/api/tasks/${taskId}/stop`, { method: "POST" }).catch(() => {});
    abortRef.current?.abort();
  }, [taskId]);

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
      // 新一轮发送同时清掉上一轮的"已停止"提示行
      setMessages((prev) => [...dropStoppedNotice(prev), { id: nextUiId(prev), kind: "user", content }]);
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setBusy(true);
      try {
        await postSse(
          `${API_URL}/api/tasks/${taskId}/messages`,
          { content },
          (event) => setMessages((prev) => reduceChatEvent(prev, event)),
          ctrl.signal,
        );
      } catch (error) {
        // 用户点停止 → fetch 抛 AbortError：定稿已流出的部分内容（保留在流中），
        // 不追加错误泡；其余错误维持原有的错误泡行为。
        if (error instanceof Error && error.name === "AbortError") {
          // 定稿部分内容 + 追加"已停止，发送消息以继续"提示行
          setMessages((prev) => appendStoppedNotice(finalizeStreaming(prev)));
        } else {
          setMessages((prev) => [...prev, { id: nextUiId(prev), kind: "error", content: String(error) }]);
        }
      } finally {
        if (abortRef.current === ctrl) abortRef.current = null;
        setBusy(false);
      }
    },
    [taskId],
  );

  return { messages, busy, send, stop };
}
