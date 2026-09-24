"use client";

import { useEffect } from "react";

export interface DeleteTurnDialogProps {
  open: boolean;
  busy: boolean; // 流式进行中禁止删除（与 ⋯ 菜单项同约束，双保险）
  onCancel: () => void;
  onConfirm: () => void;
}

// 删除整轮问答的轻量确认弹窗（对齐 SearchModal 的模态范式：fixed 遮罩点关 + Esc 带 IME guard）。
// 默认焦点落在「取消」：确认删除是不可撤销操作，误按 Enter 不该直接触发。
export function DeleteTurnDialog({ open, busy, onCancel, onConfirm }: DeleteTurnDialogProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing) return; // IME 候选窗激活时 Esc 仅消候选，不关闭弹窗
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      {/* 半透明遮罩，点击取消 */}
      <div className="absolute inset-0 bg-black/50" onClick={onCancel} aria-hidden="true" />
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="delete-turn-dialog-title"
        aria-describedby="delete-turn-dialog-desc"
        className="relative z-10 w-full max-w-sm rounded-2xl bg-white p-5 shadow-2xl"
      >
        <h2 id="delete-turn-dialog-title" className="text-sm font-semibold">
          删除这轮问答？
        </h2>
        <p id="delete-turn-dialog-desc" className="mt-1.5 text-sm text-text-secondary">
          将删除这条提问及其回答，此操作不可撤销。
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            autoFocus
            onClick={onCancel}
            className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="rounded-lg bg-red-500 px-3 py-1.5 text-sm text-white hover:bg-red-600 disabled:opacity-40"
          >
            删除
          </button>
        </div>
      </div>
    </div>
  );
}
