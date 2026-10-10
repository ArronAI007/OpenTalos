"use client";

import { useEffect, useRef, useState } from "react";
import {
  createAgentRLRun,
  listAgentRLRuns,
  getAgentRLRun,
  deleteAgentRLRun,
  type AgentRLRun,
} from "@/lib/agentrl-api";
import { TrashIcon } from "@/components/ui/icons";
import { PageSkeleton } from "@/components/ui/PageSkeleton";

const DEFAULTS = { sft_samples: 10, sft_steps: 5, grpo_samples: 10, grpo_steps: 5 };
const MAX_VALUE = 50;

function formatTimestamp(createdAt: string): string {
  return createdAt.replace("T", " ").slice(0, 19);
}

function Sparkline({ points, color }: { points: number[]; color: string }) {
  if (points.length === 0) return <p className="text-xs text-text-secondary">暂无数据</p>;
  const width = 240;
  const height = 60;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const coords = points
    .map((p, i) => {
      const x = (i / Math.max(1, points.length - 1)) * width;
      const y = height - ((p - min) / range) * height;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg width={width} height={height} className="rounded bg-gray-50">
      <polyline points={coords} fill="none" stroke={color} strokeWidth={2} />
    </svg>
  );
}

function ConfirmDeleteRunDialog({
  open,
  busy,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  busy: boolean;
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
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="delete-agentrl-run-dialog-title"
        className="relative z-10 w-full max-w-sm rounded-2xl bg-surface p-5 shadow-2xl"
      >
        <h2 id="delete-agentrl-run-dialog-title" className="text-sm font-semibold">
          删除这条训练记录？
        </h2>
        <p className="mt-1.5 text-sm text-text-secondary">此操作不可撤销。</p>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" autoFocus onClick={onCancel} className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar">
            取消
          </button>
          <button type="button" onClick={onConfirm} disabled={busy} className="rounded-lg bg-red-500 px-3 py-1.5 text-sm text-white hover:bg-red-600 disabled:opacity-40">
            删除
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AgentRLPage() {
  const [config, setConfig] = useState(DEFAULTS);
  const [runs, setRuns] = useState<AgentRLRun[] | null>(null);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    listAgentRLRuns().then(setRuns);
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
        current.map((r) => (r.status === "running" ? getAgentRLRun(r.id) : Promise.resolve(r)))
      );
      setRuns(updated);
    }, 2500);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [runs]);

  const setField = (key: keyof typeof DEFAULTS, value: number) => {
    setConfig((prev) => ({ ...prev, [key]: Math.min(MAX_VALUE, Math.max(1, value)) }));
  };

  const handleStart = async () => {
    setError(null);
    try {
      const run = await createAgentRLRun(config);
      setRuns((prev) => [run, ...(prev ?? [])]);
      setExpandedRunId(run.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "启动失败");
    }
  };

  const handleDelete = async (id: string) => {
    await deleteAgentRLRun(id);
    setRuns((prev) => prev?.filter((r) => r.id !== id) ?? null);
    setExpandedRunId((prev) => (prev === id ? null : prev));
  };

  if (runs === null) return <PageSkeleton />;

  return (
    <section className="p-6">
      <h1 className="mb-4 text-xl font-semibold">AgentRL</h1>
      <p className="mb-4 text-sm text-text-secondary">
        在 Qwen3-0.6B 上跑一次真实的 SFT→GRPO 训练演示（CPU，分钟级，规模很小——仅用于展示流程）。
      </p>

      <div className="mb-6 rounded-xl border border-border bg-surface p-4">
        <h2 className="mb-3 text-sm font-medium">训练配置</h2>
        <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {(Object.keys(DEFAULTS) as (keyof typeof DEFAULTS)[]).map((key) => (
            <label key={key} className="text-sm">
              {key}
              <input
                type="number"
                min={1}
                max={MAX_VALUE}
                value={config[key]}
                onChange={(e) => setField(key, Number(e.target.value))}
                className="mt-1 w-full rounded-lg border border-border px-2 py-1"
              />
            </label>
          ))}
        </div>
        <button type="button" onClick={() => void handleStart()} className="rounded-lg bg-text px-4 py-2 text-sm font-medium text-white">
          开始训练
        </button>
        {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <h2 className="mb-3 text-sm font-medium">训练记录</h2>
        {runs.length === 0 ? (
          <p className="text-sm text-text-secondary">还没有训练记录。</p>
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
                        <span className="font-medium">{formatTimestamp(run.created_at)}</span>
                        <span className="ml-2 text-text-secondary">{run.status}</span>
                      </span>
                      <span className="text-text-secondary">{expanded ? "收起" : "展开"}</span>
                    </button>
                    <button
                      type="button"
                      aria-label={`删除 ${formatTimestamp(run.created_at)} 的训练记录`}
                      onClick={() => setPendingDeleteId(run.id)}
                      className="text-text-secondary hover:text-red-500"
                    >
                      <TrashIcon width={14} height={14} />
                    </button>
                  </div>
                  {expanded && (
                    <div className="space-y-4 border-t border-border p-3">
                      {run.error && <p className="text-sm text-red-500">{run.error}</p>}
                      <div className="flex flex-wrap gap-4">
                        <div>
                          <p className="mb-1 text-xs text-text-secondary">SFT loss</p>
                          <Sparkline points={run.metrics.sft_loss} color="#ef4444" />
                        </div>
                        <div>
                          <p className="mb-1 text-xs text-text-secondary">GRPO reward</p>
                          <Sparkline points={run.metrics.grpo_reward} color="#10b981" />
                        </div>
                      </div>
                      {run.result && run.result.length > 0 && (
                        <table className="w-full text-left text-sm">
                          <thead>
                            <tr className="border-b border-border text-text-secondary">
                              <th className="py-1.5 pr-2">题目</th>
                              <th className="py-1.5 pr-2">训练前</th>
                              <th className="py-1.5 pr-2">训练后</th>
                              <th className="py-1.5 pr-2">标准答案</th>
                            </tr>
                          </thead>
                          <tbody>
                            {run.result.map((item, i) => (
                              <tr key={i} className="border-b border-border align-top">
                                <td className="py-1.5 pr-2">{item.question}</td>
                                <td className="py-1.5 pr-2">{item.before}</td>
                                <td className="py-1.5 pr-2">{item.after}</td>
                                <td className="py-1.5 pr-2">{item.expected}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
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
        busy={false}
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
