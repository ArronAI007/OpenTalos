"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  fetchUsageSummary,
  type UsageSummary,
} from "@/lib/model-control-api";
import {
  fetchGatewayUsage,
  type GatewayUsageSummary,
} from "@/lib/gateway-api";
import {
  listRuns,
  reportUrl,
  type RunSummary,
} from "@/lib/runs-api";
import {
  EmptyState,
  ManagementPageHeader,
  MetricCard,
} from "@/components/ui/ManagementPage";

export default function UsagePage() {
  const [controlUsage, setControlUsage] = useState<UsageSummary | null>(null);
  const [gatewayUsage, setGatewayUsage] = useState<GatewayUsageSummary | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.allSettled([
      fetchUsageSummary(),
      fetchGatewayUsage(),
      listRuns(50),
    ]).then(([control, gateway, runResult]) => {
      if (control.status === "fulfilled") setControlUsage(control.value);
      if (gateway.status === "fulfilled") setGatewayUsage(gateway.value);
      if (runResult.status === "fulfilled") setRuns(runResult.value);
      if (
        control.status === "rejected" &&
        gateway.status === "rejected" &&
        runResult.status === "rejected"
      ) {
        setError("无法加载用量数据");
      }
    });
  }, []);

  const agents = useMemo(() => {
    const map = new Map<string, { runs: number; tokens: number; cost: number }>();
    for (const run of runs) {
      const key = run.agent_name ?? run.agent_type ?? "unknown";
      const current = map.get(key) ?? { runs: 0, tokens: 0, cost: 0 };
      map.set(key, {
        runs: current.runs + 1,
        tokens: current.tokens + run.total_tokens,
        cost: current.cost + run.total_cost,
      });
    }
    return [...map.entries()].sort((left, right) => right[1].tokens - left[1].tokens);
  }, [runs]);

  const totalRunTokens = runs.reduce((sum, run) => sum + run.total_tokens, 0);
  const totalCost = runs.reduce((sum, run) => sum + run.total_cost, 0);

  return (
    <section className="p-6">
      <ManagementPageHeader
        title="用量"
        description="查看 Gateway、Provider 账号和 Agent 运行产生的 Token 与成本。"
        actions={
          <Link
            href="/runs"
            className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar"
          >
            全部运行记录
          </Link>
        }
      />

      <div className="mb-5 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Gateway 请求"
          value={gatewayUsage?.requests ?? 0}
          detail={`${controlUsage?.requests ?? 0} 个控制面请求`}
        />
        <MetricCard
          label="Gateway Token"
          value={formatNumber(gatewayUsage?.total_tokens ?? 0)}
          detail={`${formatNumber(controlUsage?.total_tokens ?? 0)} 控制面 Token`}
        />
        <MetricCard
          label="Agent Token"
          value={formatNumber(totalRunTokens)}
          detail={`${runs.length} 次运行`}
        />
        <MetricCard
          label="估算成本"
          value={`$${totalCost.toFixed(4)}`}
          detail="基于已记录运行"
        />
      </div>

      {error && <p className="mb-3 text-sm text-red-500">{error}</p>}

      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <h2 className="mb-2 text-sm font-medium">Provider 账号</h2>
          <div className="overflow-hidden rounded-lg border border-border bg-surface">
            {(controlUsage?.accounts.length ?? 0) === 0 ? (
              <p className="px-4 py-8 text-sm text-text-secondary">还没有账号用量。</p>
            ) : (
              controlUsage?.accounts.map((account, index) => (
                <div
                  key={`${account.provider}/${account.account_name}`}
                  className={`grid grid-cols-[minmax(0,1fr)_auto_auto] gap-3 px-4 py-3 text-sm ${
                    index ? "border-t border-border" : ""
                  }`}
                >
                  <span className="truncate">
                    {account.provider}/{account.account_name}
                  </span>
                  <span className="text-xs text-text-secondary">
                    {account.requests} req
                  </span>
                  <span className="tabular-nums">
                    {formatNumber(account.total_tokens)}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

        <div>
          <h2 className="mb-2 text-sm font-medium">Agent</h2>
          <div className="overflow-hidden rounded-lg border border-border bg-surface">
            {agents.length === 0 ? (
              <p className="px-4 py-8 text-sm text-text-secondary">还没有 Agent 运行。</p>
            ) : (
              agents.map(([agent, usage], index) => (
                <div
                  key={agent}
                  className={`grid grid-cols-[minmax(0,1fr)_auto_auto] gap-3 px-4 py-3 text-sm ${
                    index ? "border-t border-border" : ""
                  }`}
                >
                  <span className="truncate">{agent}</span>
                  <span className="text-xs text-text-secondary">{usage.runs} runs</span>
                  <span className="tabular-nums">{formatNumber(usage.tokens)}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      <div className="mt-6">
        <h2 className="mb-2 text-sm font-medium">最近运行</h2>
        {runs.length === 0 ? (
          <EmptyState title="还没有运行记录" />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border bg-surface">
            <table className="w-full min-w-[680px] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-text-secondary">
                  <th className="px-4 py-2 font-medium">Agent</th>
                  <th className="px-3 py-2 font-medium">任务</th>
                  <th className="px-3 py-2 font-medium">状态</th>
                  <th className="px-3 py-2 font-medium">Token</th>
                  <th className="px-3 py-2 font-medium">成本</th>
                  <th className="px-4 py-2 font-medium">报告</th>
                </tr>
              </thead>
              <tbody>
                {runs.slice(0, 20).map((run) => (
                  <tr key={run.session_id} className="border-b border-border last:border-0">
                    <td className="px-4 py-2">{run.agent_name ?? run.agent_type}</td>
                    <td className="max-w-60 truncate px-3 py-2 text-text-secondary">
                      {run.task_title ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-xs">{run.status}</td>
                    <td className="px-3 py-2 tabular-nums">
                      {formatNumber(run.total_tokens)}
                    </td>
                    <td className="px-3 py-2 tabular-nums">
                      ${run.total_cost.toFixed(4)}
                    </td>
                    <td className="px-4 py-2">
                      <a
                        href={reportUrl(run.session_id)}
                        target="_blank"
                        rel="noreferrer"
                        className="text-accent hover:underline"
                      >
                        查看
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("zh-CN", { notation: "compact" }).format(value);
}
