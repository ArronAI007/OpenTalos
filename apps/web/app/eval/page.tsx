"use client";

import { useEffect, useState } from "react";
import {
  listEvalCases,
  createEvalCase,
  deleteEvalCase,
  runEval,
  listEvalRuns,
  deleteEvalRun,
  fetchConfig,
  type EvalCase,
  type EvalResult,
  type EvalRun,
} from "@/lib/api";
import { TrashIcon } from "@/components/ui/icons";

// 汇总：均分取三维度总均值，通过率＝均分 >=3.5 的用例占比
// （沿用参考资料里"数据生成质量评估"章节对 Pass Rate 阈值的约定）。不再按 agent 类型分组——
// 当前只有单一 ReActAgent，按类型对比无意义。
function summarizeResults(results: EvalResult[]) {
  const scored = results
    .filter((r) => r.score)
    .map((r) => (r.score!.correctness + r.score!.completeness + r.score!.clarity) / 3);
  const avg = scored.length ? scored.reduce((a, b) => a + b, 0) / scored.length : null;
  const passRate = scored.length ? scored.filter((s) => s >= 3.5).length / scored.length : null;
  return { avg, passRate, scored: scored.length, total: results.length };
}

function formatTimestamp(createdAt: string): string {
  return createdAt.replace("T", " ").slice(0, 19);
}

function formatLatency(latencyMs: number): string {
  return `${(latencyMs / 1000).toFixed(1)}s`;
}

// 工具列：列出用到的工具（去重），有失败次数时附注；未用工具显示“—”。
function formatTools(r: EvalResult): string {
  const tools = r.tools_used ?? [];
  if (tools.length === 0) return "—";
  const failures = r.tool_failures ? `（${r.tool_failures} 失败）` : "";
  return `${tools.join(", ")}${failures}`;
}

// Token 单元：真实用量 + （有价目时）成本。
function formatTokens(r: EvalResult): string {
  return r.cost ? `${r.tokens_used} · $${r.cost.toFixed(4)}` : `${r.tokens_used}`;
}

// 删除确认弹窗，沿用 DeleteTurnDialog 的模态范式（fixed 遮罩点关 + Esc 带 IME guard，
// 默认焦点落在「取消」）；这里单独写一份而不是复用 DeleteTurnDialog，因为文案是评估记录专属的。
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
        aria-labelledby="delete-eval-run-dialog-title"
        aria-describedby="delete-eval-run-dialog-desc"
        className="relative z-10 w-full max-w-sm rounded-2xl bg-white p-5 shadow-2xl"
      >
        <h2 id="delete-eval-run-dialog-title" className="text-sm font-semibold">
          删除这条评估记录？
        </h2>
        <p id="delete-eval-run-dialog-desc" className="mt-1.5 text-sm text-text-secondary">
          将删除这次评估的全部结果，此操作不可撤销。
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

function ReportView({ results }: { results: EvalResult[] }) {
  const summary = summarizeResults(results);
  return (
    <div>
      <p className="mb-4 rounded-lg bg-gray-50 px-3 py-2 text-sm">
        {summary.avg === null
          ? "无有效评分"
          : `均分 ${summary.avg.toFixed(1)} · 通过率 ${Math.round((summary.passRate ?? 0) * 100)}%（${summary.scored}/${summary.total} 条有评分）`}
      </p>
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border text-text-secondary">
            <th className="py-1.5 pr-2">用例</th>
            <th className="py-1.5 pr-2">工具</th>
            <th className="py-1.5 pr-2">正确性</th>
            <th className="py-1.5 pr-2">完整性</th>
            <th className="py-1.5 pr-2">清晰度</th>
            <th className="py-1.5 pr-2">点评</th>
            <th className="py-1.5 pr-2">耗时</th>
            <th className="py-1.5 pr-2">Token 数</th>
          </tr>
        </thead>
        <tbody>
          {results.map((r) => (
            <tr key={`${r.case_id}-${r.agent_type}`} className="border-b border-border align-top">
              <td className="py-1.5 pr-2">{r.case_name}</td>
              <td className="py-1.5 pr-2 text-text-secondary">{formatTools(r)}</td>
              {r.error ? (
                <td colSpan={4} className="py-1.5 pr-2 text-red-500">
                  {r.error}
                </td>
              ) : r.score ? (
                <>
                  <td className="py-1.5 pr-2">{r.score.correctness}</td>
                  <td className="py-1.5 pr-2">{r.score.completeness}</td>
                  <td className="py-1.5 pr-2">{r.score.clarity}</td>
                  <td className="py-1.5 pr-2">{r.score.comment}</td>
                </>
              ) : (
                <td colSpan={4} className="py-1.5 pr-2 text-text-secondary">
                  评分失败
                </td>
              )}
              <td className="py-1.5 pr-2">{formatLatency(r.latency_ms)}</td>
              <td className="py-1.5 pr-2">{formatTokens(r)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function EvalPage() {
  const [cases, setCases] = useState<EvalCase[] | null>(null);
  const [agentTypes, setAgentTypes] = useState<string[]>([]);
  const [selectedCaseIds, setSelectedCaseIds] = useState<Set<string>>(new Set());
  const [name, setName] = useState("");
  const [instruction, setInstruction] = useState("");
  const [expectedAnswer, setExpectedAnswer] = useState("");
  const [running, setRunning] = useState(false);
  const [runs, setRuns] = useState<EvalRun[] | null>(null);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null);
  const [pendingDeleteRunId, setPendingDeleteRunId] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listEvalCases().then((loaded) => {
      setCases(loaded);
      setSelectedCaseIds(new Set(loaded.map((c) => c.id)));
    });
    fetchConfig().then((config) => {
      setAgentTypes(config.agent_types);
    });
    listEvalRuns().then(setRuns);
  }, []);

  if (cases === null) return null;

  const handleAddCase = async () => {
    const trimmedInstruction = instruction.trim();
    if (!trimmedInstruction) return;
    const created = await createEvalCase(
      name.trim() || trimmedInstruction.slice(0, 20),
      trimmedInstruction,
      expectedAnswer.trim() || null
    );
    setName("");
    setInstruction("");
    setExpectedAnswer("");
    setCases((prev) => [...(prev ?? []), created]);
    setSelectedCaseIds((prev) => new Set(prev).add(created.id));
  };

  const handleDeleteCase = async (id: string) => {
    await deleteEvalCase(id);
    setCases((prev) => prev?.filter((c) => c.id !== id) ?? null);
    setSelectedCaseIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  };

  const toggleCase = (id: string) => {
    setSelectedCaseIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleDeleteRun = async (id: string) => {
    // deletingRunId 卡住按钮防止双击重复发请求：第二次点击此时已被 disabled 拦下，
    // 不会对同一条已删记录再发一次 DELETE 而 404。
    if (deletingRunId) return;
    setDeletingRunId(id);
    setHistoryError(null);
    try {
      await deleteEvalRun(id);
      setRuns((prev) => prev?.filter((r) => r.id !== id) ?? null);
      setExpandedRunId((prev) => (prev === id ? null : prev));
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeletingRunId(null);
    }
  };

  const handleRun = async () => {
    if (selectedCaseIds.size === 0 || agentTypes.length === 0) return;
    setRunning(true);
    setError(null);
    try {
      const run = await runEval([...selectedCaseIds], agentTypes);
      setRuns((prev) => [run, ...(prev ?? [])]);
      setExpandedRunId(run.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "评估失败");
    } finally {
      setRunning(false);
    }
  };

  return (
    <section className="p-6">
      <h1 className="mb-4 text-xl font-semibold">Agent 评估</h1>

      <div className="mb-6 rounded-xl border border-border bg-white p-4">
        <h2 className="mb-3 text-sm font-medium">测试用例</h2>
        <div className="mb-3 flex flex-col gap-2 sm:flex-row">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="名称（可选）"
            aria-label="用例名称"
            className="rounded-lg border border-border px-3 py-1.5 text-sm sm:w-40"
          />
          <input
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder="任务指令"
            aria-label="任务指令"
            className="flex-1 rounded-lg border border-border px-3 py-1.5 text-sm"
          />
          <input
            value={expectedAnswer}
            onChange={(e) => setExpectedAnswer(e.target.value)}
            placeholder="参考答案（可选）"
            aria-label="参考答案"
            className="rounded-lg border border-border px-3 py-1.5 text-sm sm:w-48"
          />
          <button
            type="button"
            onClick={() => void handleAddCase()}
            className="rounded-lg bg-text px-3 py-1.5 text-sm font-medium text-white"
          >
            添加
          </button>
        </div>

        {cases.length === 0 ? (
          <p className="text-sm text-text-secondary">还没有测试用例。</p>
        ) : (
          <ul className="space-y-1.5">
            {cases.map((c) => (
              <li key={c.id} className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm">
                <input
                  type="checkbox"
                  checked={selectedCaseIds.has(c.id)}
                  onChange={() => toggleCase(c.id)}
                  aria-label={`选择用例 ${c.name}`}
                />
                <span className="flex-1">
                  <span className="font-medium">{c.name}</span>
                  <span className="ml-2 text-text-secondary">{c.instruction}</span>
                  {c.expected_answer && (
                    <span className="ml-2 text-xs text-text-secondary">参考答案：{c.expected_answer}</span>
                  )}
                </span>
                <button
                  type="button"
                  aria-label={`删除 ${c.name}`}
                  onClick={() => void handleDeleteCase(c.id)}
                  className="text-text-secondary hover:text-red-500"
                >
                  <TrashIcon width={14} height={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="mb-6 rounded-xl border border-border bg-white p-4">
        <button
          type="button"
          onClick={() => void handleRun()}
          disabled={running || selectedCaseIds.size === 0 || agentTypes.length === 0}
          className="rounded-lg bg-text px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {running ? "评估中…" : "开始评估"}
        </button>
        <span className="ml-3 text-xs text-text-secondary">对选中的用例各跑一轮真实对话，再由 LLM 裁判打分</span>
        {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
      </div>

      <div className="rounded-xl border border-border bg-white p-4">
        <h2 className="mb-3 text-sm font-medium">历史评估记录</h2>
        {historyError && <p className="mb-3 text-xs text-red-500">{historyError}</p>}
        {!runs || runs.length === 0 ? (
          <p className="text-sm text-text-secondary">还没有评估记录，运行一次评估后会显示在这里。</p>
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
                        <span className="ml-2 text-text-secondary">共 {run.results.length} 条结果</span>
                      </span>
                      <span className="text-text-secondary">{expanded ? "收起" : "展开"}</span>
                    </button>
                    <button
                      type="button"
                      aria-label={`删除 ${formatTimestamp(run.created_at)} 的评估记录`}
                      onClick={() => setPendingDeleteRunId(run.id)}
                      disabled={deletingRunId === run.id}
                      className="text-text-secondary hover:text-red-500 disabled:opacity-50"
                    >
                      <TrashIcon width={14} height={14} />
                    </button>
                  </div>
                  {expanded && (
                    <div className="border-t border-border p-3">
                      <ReportView results={run.results} />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <ConfirmDeleteRunDialog
        open={pendingDeleteRunId !== null}
        busy={deletingRunId !== null}
        onCancel={() => setPendingDeleteRunId(null)}
        onConfirm={() => {
          const id = pendingDeleteRunId;
          setPendingDeleteRunId(null);
          if (id) void handleDeleteRun(id);
        }}
      />
    </section>
  );
}
