"use client";

import { useEffect, useRef, useState } from "react";
import type { ThinkingItem, UiMessage } from "@/lib/chat-events";
import { humanizeReasoning, toolActionLabel, thinkingSummary } from "@/lib/humanize";

// 统一"思考过程"单元（对齐豆包）：把模型自然语言化的推理文本与工具动作收进同一折叠容器。
// 过程中展开实时显示，完成后收起成一行摘要，点击可再展开。展示层不暴露命令/参数/文件路径等
// 系统内部信息。

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
  const reasoning = humanizeReasoning(
    items
      .filter((m): m is Extract<UiMessage, { kind: "reasoning" }> => m.kind === "reasoning")
      .map((m) => m.content)
      .join("\n\n"),
  );

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
          {reasoning && <div className="whitespace-pre-wrap break-words leading-5">{reasoning}</div>}
          {tools.map((tool) => (
            <ToolActivity key={tool.id} message={tool} />
          ))}
          {!reasoning && tools.length === 0 && (
            <div className="leading-5">{streaming ? "正在思考…" : "本次没有可展示的思考内容。"}</div>
          )}
        </div>
      )}
    </div>
  );
}
