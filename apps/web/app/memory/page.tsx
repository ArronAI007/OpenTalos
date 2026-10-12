"use client";

import { useEffect, useState } from "react";
import {
  consolidateMemories,
  deleteMemory,
  forgetMemories,
  listMemories,
  type ForgetMemoriesInput,
  type Memory,
} from "@/lib/memory-api";
import { TrashIcon } from "@/components/ui/icons";
import { PageSkeleton } from "@/components/ui/PageSkeleton";

function ConfirmDialog({
  open,
  title,
  description,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  title: string;
  description: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing) return;
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <div className="absolute inset-0 bg-black/50" onClick={onCancel} aria-hidden="true" />
      <div role="alertdialog" aria-modal="true" className="relative z-10 w-full max-w-sm rounded-2xl bg-surface p-5 shadow-2xl">
        <h2 className="text-sm font-semibold">{title}</h2>
        <p className="mt-1.5 text-sm text-text-secondary">{description}</p>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" autoFocus onClick={onCancel} className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar">
            取消
          </button>
          <button type="button" onClick={onConfirm} className="rounded-lg bg-red-500 px-3 py-1.5 text-sm text-white hover:bg-red-600">
            确认
          </button>
        </div>
      </div>
    </div>
  );
}

const FORGET_STRATEGIES: { strategy: ForgetMemoriesInput["strategy"]; label: string; description: string }[] = [
  { strategy: "importance_based", label: "按重要性遗忘", description: "删除重要性低于 0.3 的记忆。" },
  { strategy: "time_based", label: "按时间遗忘", description: "删除超过 30 天未更新的记忆。" },
  { strategy: "capacity_based", label: "按容量遗忘", description: "只保留重要性最高的 1000 条记忆。" },
];

export default function MemoryPage() {
  const [memories, setMemories] = useState<Memory[] | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [pendingForget, setPendingForget] = useState<ForgetMemoriesInput | null>(null);
  const [pendingConsolidate, setPendingConsolidate] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    void listMemories().then(setMemories).catch(() => setMemories([]));
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleDelete = async (id: number) => {
    await deleteMemory(id);
    refresh();
  };

  const handleForget = async (input: ForgetMemoriesInput) => {
    setBusy(true);
    setError(null);
    try {
      await forgetMemories(input);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "遗忘失败");
    } finally {
      setBusy(false);
    }
  };

  const handleConsolidate = async () => {
    setBusy(true);
    setError(null);
    try {
      await consolidateMemories();
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "整合失败");
    } finally {
      setBusy(false);
    }
  };

  if (memories === null) return <PageSkeleton />;

  return (
    <section className="p-6">
      <h1 className="mb-4 text-xl font-semibold">记忆</h1>
      <p className="mb-4 text-sm text-text-secondary">
        查看和管理跨会话记住的用户信息：手动删除单条记忆，或者按策略批量遗忘/整合。
      </p>

      <div className="mb-6 rounded-xl border border-border bg-surface p-4">
        <h2 className="mb-3 text-sm font-medium">记忆管理</h2>
        <div className="flex flex-wrap gap-2">
          {FORGET_STRATEGIES.map((item) => (
            <button
              key={item.strategy}
              type="button"
              disabled={busy}
              onClick={() => setPendingForget({ strategy: item.strategy })}
              className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar disabled:opacity-50"
              title={item.description}
            >
              {item.label}
            </button>
          ))}
          <button
            type="button"
            disabled={busy}
            onClick={() => setPendingConsolidate(true)}
            className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar disabled:opacity-50"
            title="把语义高度相似的记忆合并成一条"
          >
            整合相似记忆
          </button>
        </div>
        {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <h2 className="mb-3 text-sm font-medium">已记住的内容</h2>
        {memories.length === 0 ? (
          <p className="text-sm text-text-secondary">还没有记住任何内容。</p>
        ) : (
          <ul className="space-y-2">
            {memories.map((memory) => (
              <li key={memory.id} className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm">
                <span className="flex-1">
                  <span>{memory.content}</span>
                  <span className="ml-2 text-xs text-text-secondary">
                    重要性 {Math.round(memory.importance * 100)}%
                  </span>
                </span>
                <button
                  type="button"
                  aria-label={`删除记忆：${memory.content}`}
                  onClick={() => setPendingDeleteId(memory.id)}
                  className="text-text-secondary hover:text-red-500"
                >
                  <TrashIcon width={14} height={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <ConfirmDialog
        open={pendingDeleteId !== null}
        title="删除这条记忆？"
        description="此操作不可撤销。"
        onCancel={() => setPendingDeleteId(null)}
        onConfirm={() => {
          const id = pendingDeleteId;
          setPendingDeleteId(null);
          if (id !== null) void handleDelete(id);
        }}
      />
      <ConfirmDialog
        open={pendingForget !== null}
        title="确认执行遗忘？"
        description={FORGET_STRATEGIES.find((s) => s.strategy === pendingForget?.strategy)?.description ?? ""}
        onCancel={() => setPendingForget(null)}
        onConfirm={() => {
          const input = pendingForget;
          setPendingForget(null);
          if (input) void handleForget(input);
        }}
      />
      <ConfirmDialog
        open={pendingConsolidate}
        title="确认整合相似记忆？"
        description="会用模型把语义高度相似的记忆合并成更简洁的一条，原记录会被删除。"
        onCancel={() => setPendingConsolidate(false)}
        onConfirm={() => {
          setPendingConsolidate(false);
          void handleConsolidate();
        }}
      />
    </section>
  );
}
