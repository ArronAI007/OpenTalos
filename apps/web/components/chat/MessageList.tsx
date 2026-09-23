"use client";

import { useLayoutEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { UiMessage } from "@/lib/chat-events";
import { isNearBottom, scrollToBottom } from "@/lib/scroll-stick";

function ToolBubble({ message }: { message: Extract<UiMessage, { kind: "tool" }> }) {
  const argsPreview = Object.entries(message.arguments)
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(", ");
  return (
    <details className="mx-auto w-full max-w-xl rounded-lg border border-border bg-sidebar px-3 py-2 text-xs text-text-secondary">
      <summary className="cursor-pointer select-none">
        🔧 {message.name}({argsPreview})
        {message.ok !== undefined && (message.ok ? " ✓" : " ✗")}
      </summary>
      {message.result !== undefined && (
        <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap break-all">{message.result}</pre>
      )}
    </details>
  );
}

// 消息行行壳：ol 已铺满内容区，列宽与内边距约束收回到行级（与原先 max-w-3xl + px-4 的几何等同）。
const rowCls = "mx-auto w-full max-w-3xl px-4";

export function MessageList({ messages }: { messages: UiMessage[] }) {
  const listRef = useRef<HTMLOListElement>(null);
  // 跟随滚动开关：初始 true（进入任务/历史加载后落在最新消息）；用户上翻超过阈值即停跟，回到底部恢复。
  const stickRef = useRef(true);
  const prevLenRef = useRef(0);

  // 绘制前纠位，避免流式 token 逐帧闪现错位。每条 delta 都产生新 messages 引用，在此统一兜底。
  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el) return;
    // 新出现的是用户消息 = 自己刚发送：无条件回到底部（即便之前在上翻阅读）。
    const appendedUser =
      messages.length > prevLenRef.current && messages[messages.length - 1]?.kind === "user";
    prevLenRef.current = messages.length;
    if (appendedUser) stickRef.current = true;
    if (stickRef.current) scrollToBottom(el);
  }, [messages]);

  return (
    <ol
      ref={listRef}
      onScroll={(e) => {
        stickRef.current = isNearBottom(e.currentTarget);
      }}
      className="flex flex-1 flex-col gap-3 overflow-y-auto py-6"
    >
      {messages.map((message) => {
        if (message.kind === "user") {
          return (
            <li key={message.id} className={rowCls}>
              <div className="ml-auto w-fit max-w-[75%] rounded-2xl bg-user-bubble px-4 py-2 text-sm text-white">
                {message.content}
              </div>
            </li>
          );
        }
        if (message.kind === "assistant") {
          return (
            <li key={message.id} className={rowCls}>
              <div className="max-w-[85%] text-sm leading-6">
                <div className="md">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                </div>
                {message.streaming && <span className="animate-pulse text-text-secondary">▍</span>}
              </div>
            </li>
          );
        }
        if (message.kind === "tool") {
          return <li key={message.id} className={rowCls}><ToolBubble message={message} /></li>;
        }
        return (
          <li key={message.id} className={rowCls}>
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
              出错了：{message.content}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
