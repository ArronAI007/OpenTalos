"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listRuns, reportUrl, type RunSummary } from "@/lib/runs-api";
import { PageSkeleton } from "@/components/ui/PageSkeleton";

export function statusLabel(status: string): string {
  if (status === "completed") return "✓";
  if (status === "failed") return "✗";
  if (status === "running") return "进行中";
  if (status === "cancelled") return "已取消";
  return status;
}

export function formatDuration(run: Pick<RunSummary, "status" | "duration_seconds">): string {
  if (run.status === "running") return "进行中";
  return `${run.duration_seconds.toFixed(1)}s`;
}

export default function RunsPage() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listRuns()
      .then(setRuns)
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"));
  }, []);

  if (error) {
    return (
      <section className="p-6">
        <h1 className="mb-4 text-xl font-semibold">运行记录</h1>
        <p className="text-sm text-red-500">{error}</p>
      </section>
    );
  }

  if (runs === null) return <PageSkeleton />;

  return (
    <section className="p-6">
      <h1 className="mb-4 text-xl font-semibold">运行记录</h1>
      <p className="mb-4 text-sm text-text-secondary">
        最近的 Agent 运行轨迹，点击"查看报告"打开该次运行已生成的详细报告。
      </p>

      <div className="rounded-xl border border-border bg-surface p-4">
        {runs.length === 0 ? (
          <p className="text-sm text-text-secondary">还没有运行记录。</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-secondary">
                <th className="py-2 pr-4 font-medium">状态</th>
                <th className="py-2 pr-4 font-medium">Agent</th>
                <th className="py-2 pr-4 font-medium">任务</th>
                <th className="py-2 pr-4 font-medium">耗时</th>
                <th className="py-2 pr-4 font-medium">Token</th>
                <th className="py-2 font-medium">报告</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.session_id} className="border-b border-border last:border-0">
                  <td className="py-2 pr-4">
                    <span className={run.status === "failed" ? "text-red-500" : ""}>
                      {statusLabel(run.status)}
                    </span>
                  </td>
                  <td className="py-2 pr-4">{run.agent_name ?? "—"}</td>
                  <td className="py-2 pr-4">
                    {run.task_id ? (
                      run.task_title ? (
                        <Link href={`/t/${run.task_id}`} className="hover:underline">
                          {run.task_title}
                        </Link>
                      ) : (
                        <span className="text-text-secondary">（任务已删除）</span>
                      )
                    ) : (
                      <span className="text-text-secondary">（无关联任务）</span>
                    )}
                  </td>
                  <td className="py-2 pr-4">{formatDuration(run)}</td>
                  <td className="py-2 pr-4">
                    {run.total_tokens}
                    {run.total_cost > 0 && (
                      <span className="ml-1 text-xs text-text-secondary">
                        (${run.total_cost.toFixed(4)})
                      </span>
                    )}
                  </td>
                  <td className="py-2">
                    <a
                      href={reportUrl(run.session_id)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-accent hover:underline"
                    >
                      查看报告 →
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
