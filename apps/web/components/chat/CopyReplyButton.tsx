"use client";

import { useEffect, useRef, useState } from "react";
import { copyText } from "@/lib/clipboard";
import { CheckIcon, CopyIcon } from "@/components/ui/icons";
import { Tooltip } from "@/components/ui/Tooltip";

// 回复完成后的动作行：复制本轮回复的原始 Markdown（保留结构）。
// 状态机 idle → copied/failed →（1500ms）idle。
// 异步期间行可能被卸载（切换任务 key=taskId 整树重挂载）：cleanup 清遗留定时器 +
// mountedRef 挡住 await 返回后落状态（与 TaskListMenu 分享项同一 async-timer 范式）。
export function CopyReplyButton({ content }: { content: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      mountedRef.current = false;
    };
  }, []);

  const handleCopy = async () => {
    if (state === "copied") return; // 已复制展示期间忽略连点
    if (timerRef.current) clearTimeout(timerRef.current); // 复点重置反馈时长
    const ok = await copyText(content);
    if (!mountedRef.current) return; // await 期间已卸载：不落状态、不设新定时器
    setState(ok ? "copied" : "failed");
    timerRef.current = setTimeout(() => setState("idle"), 1500);
  };

  const label =
    state === "copied" ? "已复制" : state === "failed" ? "复制失败，点击重试" : "复制回复内容";

  return (
    <Tooltip label={label}>
      <button
        type="button"
        onClick={() => void handleCopy()}
        aria-label={label}
        className={`rounded p-1 transition-colors ${
          state === "copied"
            ? "text-green-600"
            : state === "failed"
              ? "text-red-600"
              : "text-text-secondary hover:bg-sidebar hover:text-text"
        }`}
      >
        {state === "copied" ? <CheckIcon /> : <CopyIcon />}
      </button>
    </Tooltip>
  );
}
