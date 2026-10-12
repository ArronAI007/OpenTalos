"use client";

import { useEffect, useRef, useState } from "react";
import type { ThinkingItem, UiMessage } from "@/lib/chat-events";
import { toolActionLabel } from "@/lib/humanize";

// 统一"思考过程"单元：只展示 agent 正在做什么（自然语言动作行），展示层不暴露原始思维链、
// 命令、参数或文件路径等系统内部信息（对齐 Codex / 豆包的做法）。

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

  // 流式期间默认展开（等待反馈正是它的意义），定稿后自动收起；用户一旦手动开合过，
  // 定稿时尊重用户选择不再动它（touched 记录）。
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
        {streaming ? "正在思考…" : "思考过程"}
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
