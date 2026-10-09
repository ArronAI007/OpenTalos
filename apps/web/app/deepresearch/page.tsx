"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  createDeepResearchRun,
  listDeepResearchRuns,
  getDeepResearchRun,
  deleteDeepResearchRun,
  type DeepResearchRun,
} from "@/lib/deepresearch-api";
import { TrashIcon } from "@/components/ui/icons";

function formatTimestamp(createdAt: string): string {
  return createdAt.replace("T", " ").slice(0, 19);
}

const STATUS_LABEL: Record<string, string> = {
  pending: "等待中",
  running: "搜索中",
  completed: "已完成",
  failed: "失败",
};

function ConfirmDeleteRunDialog({
  open,
  onCancel,
  onConfirm,
}: {
  open: boolean;
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
      <div role="alertdialog" aria-modal="true" className="relative z-10 w-full max-w-sm rounded-2xl bg-white p-5 shadow-2xl">
        <h2 className="text-sm font-semibold">删除这条研究记录？</h2>
        <p className="mt-1.5 text-sm text-text-secondary">此操作不可撤销。</p>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" autoFocus onClick={onCancel} className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar">
            取消
          </button>
          <button type="button" onClick={onConfirm} className="rounded-lg bg-red-500 px-3 py-1.5 text-sm text-white hover:bg-red-600">
            删除
          </button>
        </div>
      </div>
    </div>
  );
}

export default function DeepResearchPage() {
  const [topic, setTopic] = useState("");
  const [runs, setRuns] = useState<DeepResearchRun[] | null>(null);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [expandedTodoId, setExpandedTodoId] = useState<number | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    listDeepResearchRuns().then(setRuns);
  }, []);

  useEffect(() => {
    const hasRunning = runs?.some((r) => r.status === "running") ?? false;
    if (!hasRunning) {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }
    pollRef.current = setInterval(async () => {
      const current = runs ?? [];
      const updated = await Promise.all(
        current.map((r) => (r.status === "running" ? getDeepResearchRun(r.id) : Promise.resolve(r)))
      );
      setRuns(updated);
    }, 2500);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [runs]);

  const handleStart = async () => {
    const trimmed = topic.trim();
    if (!trimmed) return;
    setError(null);
    try {
      const run = await createDeepResearchRun(trimmed);
      setRuns((prev) => [run, ...(prev ?? [])]);
      setExpandedRunId(run.id);
      setTopic("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "启动失败");
    }
  };

  const handleDelete = async (id: string) => {
    await deleteDeepResearchRun(id);
    setRuns((prev) => prev?.filter((r) => r.id !== id) ?? null);
    setExpandedRunId((prev) => (prev === id ? null : prev));
  };

  if (runs === null) return null;

  return (
    <section className="p-6">
      <h1 className="mb-4 text-xl font-semibold">DeepResearch</h1>
      <p className="mb-4 text-sm text-text-secondary">
        输入一个研究主题，自动拆解成若干子任务并行搜索、总结，最后合成一份带来源引用的报告。
      </p>

      <div className="mb-6 rounded-xl border border-border bg-white p-4">
        <h2 className="mb-3 text-sm font-medium">研究主题</h2>
        <div className="flex gap-2">
          <input
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="例如：量子计算的基本原理和应用场景"
            className="flex-1 rounded-lg border border-border px-3 py-1.5 text-sm"
          />
          <button type="button" onClick={() => void handleStart()} className="rounded-lg bg-text px-4 py-2 text-sm font-medium text-white">
            开始研究
          </button>
        </div>
        {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
      </div>

      <div className="rounded-xl border border-border bg-white p-4">
        <h2 className="mb-3 text-sm font-medium">研究记录</h2>
        {runs.length === 0 ? (
          <p className="text-sm text-text-secondary">还没有研究记录。</p>
        ) : (
          <ul className="space-y-2">
            {runs.map((run) => {
              const expanded = expandedRunId === run.id;
              return (
                <li key={run.id} className="rounded-lg border border-border">
                  <div className="flex items-center gap-2 px-3 py-2 text-sm">
                    <button
                      type="button"
                      onClick={() => setExpandedRunId(expanded ? null : run.id)}
                      className="flex flex-1 items-center justify-between text-left"
                    >
                      <span>
                        <span className="font-medium">{run.topic}</span>
                        <span className="ml-2 text-text-secondary">
                          {formatTimestamp(run.created_at)} · {run.status}
                        </span>
                      </span>
                      <span className="text-text-secondary">{expanded ? "收起" : "展开"}</span>
                    </button>
                    <button
                      type="button"
                      aria-label={`删除研究记录：${run.topic}`}
                      onClick={() => setPendingDeleteId(run.id)}
                      className="text-text-secondary hover:text-red-500"
                    >
                      <TrashIcon width={14} height={14} />
                    </button>
                  </div>
                  {expanded && (
                    <div className="space-y-4 border-t border-border p-3">
                      {run.error && <p className="text-sm text-red-500">{run.error}</p>}
                      {run.todos.length > 0 && (
                        <ul className="space-y-1.5">
                          {run.todos.map((todo) => {
                            const todoExpanded = expandedTodoId === todo.id;
                            return (
                              <li key={todo.id} className="rounded-lg border border-border px-3 py-2 text-sm">
                                <button
                                  type="button"
                                  onClick={() => setExpandedTodoId(todoExpanded ? null : todo.id)}
                                  className="flex w-full items-center justify-between text-left"
                                  disabled={todo.status === "pending" || todo.status === "running"}
                                >
                                  <span>{todo.query}</span>
                                  <span className="text-xs text-text-secondary">{STATUS_LABEL[todo.status]}</span>
                                </button>
                                {todoExpanded && todo.summary && (
                                  <div className="mt-2 space-y-1.5 text-text-secondary">
                                    <p>{todo.summary}</p>
                                    {todo.sources.length > 0 && (
                                      <ul className="list-disc pl-4">
                                        {todo.sources.map((s) => (
                                          <li key={s.url}>
                                            <a href={s.url} target="_blank" rel="noopener noreferrer" className="underline">
                                              {s.title}
                                            </a>
                                          </li>
                                        ))}
                                      </ul>
                                    )}
                                  </div>
                                )}
                              </li>
                            );
                          })}
                        </ul>
                      )}
                      {run.report && (
                        <div className="md">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{run.report}</ReactMarkdown>
                        </div>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <ConfirmDeleteRunDialog
        open={pendingDeleteId !== null}
        onCancel={() => setPendingDeleteId(null)}
        onConfirm={() => {
          const id = pendingDeleteId;
          setPendingDeleteId(null);
          if (id) void handleDelete(id);
        }}
      />
    </section>
  );
}
