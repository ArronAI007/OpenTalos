"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { listTasks, type Task } from "@/lib/api";
import { filterTasksByTitle } from "@/lib/task-filter";
import { formatTaskTime, groupTasksByDate } from "@/lib/task-groups";
import { useCreateTask } from "@/components/sidebar/SidebarClient";
import { SearchIcon } from "@/components/ui/icons";

interface SearchModalProps {
  open: boolean;
  onClose: () => void;
}

export function SearchModal({ open, onClose }: SearchModalProps) {
  const router = useRouter();
  const { busy, error, create } = useCreateTask();
  const [query, setQuery] = useState("");
  const [tasks, setTasks] = useState<Task[]>([]);

  // 每次打开重置查询并重新拉取任务列表，保证列表最新。
  useEffect(() => {
    if (!open) return;
    // 打开即清空搜索词，避免旧会话的关键词/结果带到下次打开。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setQuery("");
    let cancelled = false;
    listTasks()
      .then((t) => {
        if (!cancelled) setTasks(t);
      })
      .catch(() => {
        if (!cancelled) setTasks([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  // Esc 关闭。
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing) return; // IME 候选窗激活时 Esc 仅消候选，不关闭弹窗
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const now = new Date();
  const filtered = filterTasksByTitle(tasks, query);
  const groups = groupTasksByDate(filtered, now);

  const handleCreate = async () => {
    const ok = await create();
    if (ok) onClose(); // 成功后 hook 已完成路由跳转，这里关闭弹窗。
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto px-4">
      {/* 半透明遮罩，点击关闭 */}
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true" />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="搜索任务"
        className="relative z-10 mt-[15vh] flex max-h-[75vh] w-full max-w-xl flex-col rounded-2xl bg-white p-3 shadow-2xl"
      >
        {/* 顶部搜索行 */}
        <div className="flex items-center gap-2 border-b border-border pb-2">
          <SearchIcon className="shrink-0 text-text-secondary" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索任务…"
            aria-label="搜索任务"
            autoFocus
            className="w-full bg-transparent text-sm outline-none placeholder:text-text-secondary"
          />
          <button
            type="button"
            aria-label="关闭"
            onClick={onClose}
            className="rounded-lg px-1.5 py-0.5 text-text-secondary hover:bg-gray-100 hover:text-text"
          >
            ✕
          </button>
        </div>

        {/* 新建任务动作行 */}
        <button
          type="button"
          aria-label="新建任务"
          onClick={() => void handleCreate()}
          disabled={busy}
          className="mt-1 w-full rounded-lg px-3 py-2 text-left text-sm font-medium hover:bg-gray-50 disabled:opacity-50"
        >
          ＋ 新建任务
        </button>
        {error && <p className="px-3 pb-1 text-xs text-red-500">{error}</p>}

        {/* 任务历史分组列表 */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {query.trim() !== "" && filtered.length === 0 ? (
            <p className="px-3 py-2 text-xs text-text-secondary">无匹配任务</p>
          ) : (
            groups.map((group) => (
              <div key={group.key}>
                <p className="px-3 pb-1 pt-2 text-xs text-text-secondary">{group.label}</p>
                <ul>
                  {group.tasks.map((task) => (
                    <li key={task.id}>
                      <button
                        type="button"
                        onClick={() => {
                          onClose();
                          router.push(`/t/${task.id}`);
                        }}
                        className="flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-gray-50"
                      >
                        <span className="truncate">{task.title || "（未命名任务）"}</span>
                        <span className="shrink-0 text-xs text-text-secondary">
                          {formatTaskTime(new Date(task.updated_at), now)}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
