"use client";

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
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
import { DeleteTurnDialog } from "./DeleteTurnDialog";

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
  // 删除二次确认：菜单项只负责开弹窗，确认按钮才真正触发 onDelete
  const [confirmOpen, setConfirmOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  // 菜单本体 + 翻转态：默认向下展开；最末轮提问贴近可滚动区（ol）下沿时向下会被
  // overflow-y-auto 垂直裁断——渲染后测量，越界即向上翻转（TaskListMenu 同款范式）。
  const panelRef = useRef<HTMLDivElement>(null);
  const [flipUp, setFlipUp] = useState(false);

  useLayoutEffect(() => {
    if (!menuOpen) return;
    const trigger = menuRef.current;
    const panel = panelRef.current;
    const list = trigger?.closest("ol"); // 最近滚动容器（MessageList 的消息列表）
    if (!trigger || !panel || !list) return;
    // 用触发器底沿 + 面板高度推算向下展开的落点，与面板当前摆放（flipUp 残留值）无关——
    // 若量面板自身 rect，上次残留的 flip 会让重开先渲染在上方、误判没越界、回落下方再被裁。
    setFlipUp(trigger.getBoundingClientRect().bottom + panel.offsetHeight > list.getBoundingClientRect().bottom);
  }, [menuOpen]);

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
    <>
    {/* 行级显隐：li.group 上 hover / focus-within 时才显现（invisible 保留占位不抖动） */}
    <div className="mt-1 flex items-center justify-end gap-0.5 invisible opacity-0 transition-opacity group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100">
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
            ref={panelRef}
            role="menu"
            aria-label="提问操作"
            className={`absolute right-0 z-10 w-32 rounded-lg border border-border bg-white p-1 shadow-lg ${flipUp ? "bottom-full mb-1" : "top-full mt-1"}`}
          >
            <button
              type="button"
              role="menuitem"
              disabled={busy}
              onClick={() => {
                setMenuOpen(false);
                setConfirmOpen(true);
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
    <DeleteTurnDialog
      open={confirmOpen}
      busy={busy}
      onCancel={() => setConfirmOpen(false)}
      onConfirm={() => {
        setConfirmOpen(false);
        onDelete();
      }}
    />
    </>
  );
}
