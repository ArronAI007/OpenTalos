"use client";

import { useEffect, useRef, useState } from "react";
import type { UiMessage } from "@/lib/chat-events";
import { humanizeReasoning, humanizeToolCall } from "@/lib/humanize";

// 统一"思考过程"单元：把一段连续的自然语言思维链与其中的工具动作收进同一个折叠容器，
// 而不是各占一个盒子（对齐 Codex / 豆包：一轮思考是一个面板，面板内既有思路也有动作）。
export type ThinkingItem = Extract<UiMessage, { kind: "reasoning" | "tool" }>;

function ToolActivity({ message }: { message: Extract<UiMessage, { kind: "tool" }> }) {
  const { label, detail } = humanizeToolCall(message.name, message.arguments);
  const running = message.result === undefined;
  const argsPreview = Object.entries(message.arguments)
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(", ");
  const raw = `${argsPreview}${message.result !== undefined ? `\n\n${message.result}` : ""}`;
  return (
    <div className="mt-1.5 border-t border-border pt-1.5">
      {/* 自然语言动作行（Codex 风）：原始细节收进折叠区 */}
      <div className="flex items-baseline gap-1.5">
        <span aria-hidden className={running ? "animate-pulse" : undefined}>
          {running ? "⏳" : message.ok ? "✓" : "✗"}
        </span>
        <span className="shrink-0 text-text">{running ? "正在使用" : "已使用"}「{label}」</span>
        {detail && <span className="truncate">：{detail}</span>}
      </div>
      <details className="mt-1">
        <summary className="cursor-pointer select-none">查看原始细节</summary>
        <pre className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap break-all">{raw}</pre>
      </details>
    </div>
  );
}

export function ThinkingBubble({ items, streaming }: { items: ThinkingItem[]; streaming?: boolean }) {
  const [expanded, setExpanded] = useState(true);
  const touchedRef = useRef(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const reasoning = humanizeReasoning(
    items
      .filter((m): m is Extract<UiMessage, { kind: "reasoning" }> => m.kind === "reasoning")
      .map((m) => m.content)
      .join("\n\n"),
  );
  const tools = items.filter((m): m is Extract<UiMessage, { kind: "tool" }> => m.kind === "tool");

  // 流式期间默认展开（等待反馈正是它的意义），定稿后自动收起；用户一旦手动开合过，
  // 定稿时尊重用户选择不再动它（touched 记录）。
  useEffect(() => {
    if (!streaming && !touchedRef.current) setExpanded(false);
  }, [streaming]);

  // 流式期间跟随最新思路/动作：内容增长时把视图滚到底（仅展开态有意义）。
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
        {streaming ? "正在思考…" : "思考过程"}
        <span aria-hidden className="ml-auto">
          {expanded ? "▾" : "▸"}
        </span>
      </button>
      {expanded && (
        <div ref={bodyRef} className="max-h-64 overflow-y-auto px-3 pb-2">
          {(reasoning || tools.length === 0) && (
            <div className="leading-5 break-words whitespace-pre-wrap">
              {reasoning || (streaming ? "正在整理思路…" : "（本次思考没有可读的自然语言内容）")}
            </div>
          )}
          {tools.map((tool) => (
            <ToolActivity key={tool.id} message={tool} />
          ))}
        </div>
      )}
    </div>
  );
}
