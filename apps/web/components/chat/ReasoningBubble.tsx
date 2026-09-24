"use client";

import { useEffect, useRef, useState } from "react";

// 思维链折叠块：流式期间默认展开（等待反馈正是它的意义），定稿后自动收起；
// 用户一旦手动开合过，定稿时尊重用户选择不再动它（touched 记录）。
export function ReasoningBubble({ content, streaming }: { content: string; streaming?: boolean }) {
  const [expanded, setExpanded] = useState(true);
  const touchedRef = useRef(false);

  useEffect(() => {
    if (!streaming && !touchedRef.current) setExpanded(false);
  }, [streaming]);

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
        {streaming ? "正在思考…" : `思维链（${content.length} 字）`}
        <span aria-hidden className="ml-auto">
          {expanded ? "▾" : "▸"}
        </span>
      </button>
      {expanded && (
        <div className="max-h-64 overflow-y-auto px-3 pb-2 leading-5 break-words whitespace-pre-wrap">
          {content}
        </div>
      )}
    </div>
  );
}
