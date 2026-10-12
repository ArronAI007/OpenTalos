"use client";

import { useEffect, useRef, useState } from "react";
import type { ThinkingItem, UiMessage } from "@/lib/chat-events";
import { toolActionLabel, thinkingSummary } from "@/lib/humanize";

// 统一"思考过程"单元：只展示 agent 正在做什么（自然语言动作行），展示层不暴露原始思维链、
// 命令、参数或文件路径等系统内部信息（对齐豆包）。过程中展开实时显示动作，完成后收起成一行
// 摘要（"已联网搜索 · N 步"），点击可再展开。

function ToolActivity({ message }: { message: Extract<UiMessage, { kind: "tool" }> }) {
  const running = message.result === undefined;
  return (
    <div className="flex items-center gap-1.5 py-0.5 leading-5">
      <span aria-hidden className={running ? "animate-pulse" : undefined}>
        {running ? "⏳" : message.ok ? "✓" : "✗"}
      </span>
      <span className="text-text">
        {running ? "正在" : "已完成"}：{toolActionLabel(message.name)}
      </span>
    </div>
  );
}

export function ThinkingBubble({ items, streaming }: { items: ThinkingItem[]; streaming?: boolean }) {
  const [expanded, setExpanded] = useState(true);
  const touchedRef = useRef(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const tools = items.filter((m): m is Extract<UiMessage, { kind: "tool" }> => m.kind === "tool");

  // 过程中默认展开（实时看动作），完成后自动收起成一行摘要；用户手动开合过后尊重其选择。
  useEffect(() => {
    if (!streaming && !touchedRef.current) setExpanded(false);
  }, [streaming]);

  // 流式期间跟随最新动作：内容增长时把视图滚到底（仅展开态有意义）。
  useEffect(() => {
    if (streaming && expanded && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [items, streaming, expanded]);

  return (
    <div className="mb-2 overflow-hidden rounded-lg border border-border bg-sidebar text-xs text-text-secondary">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => {
          touchedRef.current = true;
          setExpanded((v) => !v);
        }}
        className="flex w-full cursor-pointer select-none items-center gap-1.5 px-3 py-1.5 text-left"
      >
        <span aria-hidden className={streaming ? "animate-pulse" : undefined}>
          💭
        </span>
        {streaming ? "正在思考…" : thinkingSummary(items)}
        <span aria-hidden className="ml-auto">
          {expanded ? "▾" : "▸"}
        </span>
      </button>
      {expanded && (
        <div ref={bodyRef} className="max-h-64 space-y-0.5 overflow-y-auto px-3 pb-2">
          {tools.length === 0 ? (
            <div className="leading-5">{streaming ? "正在思考…" : "本次没有调用工具。"}</div>
          ) : (
            tools.map((tool) => <ToolActivity key={tool.id} message={tool} />)
          )}
        </div>
      )}
    </div>
  );
}
