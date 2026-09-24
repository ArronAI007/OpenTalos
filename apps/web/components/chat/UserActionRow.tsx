"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { copyText } from "@/lib/clipboard";
import { formatRelativeDay } from "@/lib/format-time";
import {
  CheckIcon,
  CopyIcon,
  CornerUpRightIcon,
  EllipsisIcon,
  PencilSquareIcon,
  TrashIcon,
} from "@/components/ui/icons";

interface CopyStateButtonProps {
  getText: () => string;
  idleLabel: string;
  children: ReactNode;
}

const iconBtnCls = (tone: "idle" | "copied" | "failed") =>
  `rounded p-1 transition-colors ${
    tone === "copied"
      ? "text-green-600"
      : tone === "failed"
        ? "text-red-600"
        : "text-text-secondary hover:bg-sidebar hover:text-text"
  }`;

// 复制类按钮的状态机 idle → copied/failed →（1500ms）idle，复制内容/分享链接两个实例复用。
// async-timer 范式与 CopyReplyButton 一致：cleanup 清遗留定时器 + mountedRef 挡 await 后落状态。
function CopyStateButton({ getText, idleLabel, children }: CopyStateButtonProps) {
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
    if (timerRef.current) clearTimeout(timerRef.current);
    const ok = await copyText(getText()); // 点击时才取值：分享链接需 window.location，渲染期（SSR）不可得
    if (!mountedRef.current) return;
    setState(ok ? "copied" : "failed");
    timerRef.current = setTimeout(() => setState("idle"), 1500);
  };

  const label = state === "copied" ? "已复制" : state === "failed" ? "复制失败，点击重试" : idleLabel;

  return (
    <button
      type="button"
      onClick={() => void handleCopy()}
      aria-label={label}
      title={label}
      className={iconBtnCls(state)}
    >
      {state === "copied" ? <CheckIcon /> : children}
    </button>
  );
}

export interface UserActionRowProps {
  content: string;
  completedAt?: number;
  taskId: string;
  busy: boolean; // 流式进行中禁用删除（服务端对活动流不设防，前端先行约束）
  onEdit: () => void;
  onDelete: () => void;
}

// Manus 式用户消息操作行：相对时间 + 复制内容 / 分享会话链接 / 编辑回填 / ⋯（删除整轮）。
export function UserActionRow({ content, completedAt, taskId, busy, onEdit, onDelete }: UserActionRowProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // 打开期间点击菜单外或 Esc 关闭（与侧栏 TaskListMenu 同款交互，菜单小、就地管理）
  useEffect(() => {
    if (!menuOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen]);

  return (
    <div className="mt-1 flex items-center justify-end gap-0.5">
      {completedAt !== undefined && (
        <time className="mr-1.5 text-xs text-text-secondary">{formatRelativeDay(completedAt)}</time>
      )}
      <CopyStateButton getText={() => content} idleLabel="复制提问内容">
        <CopyIcon />
      </CopyStateButton>
      {/* 分享 = 复制会话链接（与侧栏任务分享同语义：origin/t/<taskId>） */}
      <CopyStateButton getText={() => `${window.location.origin}/t/${taskId}`} idleLabel="分享会话链接">
        <CornerUpRightIcon />
      </CopyStateButton>
      <button
        type="button"
        onClick={onEdit}
        aria-label="编辑：回填到输入框"
        title="编辑：回填到输入框"
        className={iconBtnCls("idle")}
      >
        <PencilSquareIcon />
      </button>
      <div className="relative" ref={menuRef}>
        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          aria-label="更多操作"
          title="更多操作"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          className={iconBtnCls("idle")}
        >
          <EllipsisIcon />
        </button>
        {menuOpen && (
          <div
            role="menu"
            aria-label="提问操作"
            className="absolute right-0 top-full z-10 mt-1 w-32 rounded-lg border border-border bg-white p-1 shadow-lg"
          >
            <button
              type="button"
              role="menuitem"
              disabled={busy}
              onClick={() => {
                setMenuOpen(false);
                onDelete();
              }}
              className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-red-500 hover:bg-sidebar disabled:opacity-40"
            >
              <TrashIcon />
              删除
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
