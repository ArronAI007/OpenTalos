"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  fetchUsageSummary,
  listControlPlaneModels,
  listProviderAccounts,
  listQuotaSnapshots,
  listRoutingGroups,
  type ModelDescriptor,
  type ProviderAccount,
  type QuotaSnapshot,
  type RoutingGroup,
  type UsageSummary,
} from "@/lib/model-control-api";
import {
  listGatewayRequests,
  type GatewayRequest,
} from "@/lib/gateway-api";
import {
  EmptyState,
  ManagementPageHeader,
  MetricCard,
} from "@/components/ui/ManagementPage";
import { CopyIcon, RouteIcon, SearchIcon } from "@/components/ui/icons";
import { PageSkeleton } from "@/components/ui/PageSkeleton";
import { copyText } from "@/lib/clipboard";

export default function RoutingPage() {
  const [accounts, setAccounts] = useState<ProviderAccount[] | null>(null);
  const [models, setModels] = useState<ModelDescriptor[]>([]);
  const [groups, setGroups] = useState<RoutingGroup[]>([]);
  const [quotas, setQuotas] = useState<QuotaSnapshot[]>([]);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [traces, setTraces] = useState<GatewayRequest[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      listProviderAccounts(),
      listControlPlaneModels(),
      listRoutingGroups(),
      listQuotaSnapshots(),
      fetchUsageSummary(),
      listGatewayRequests(30).catch(() => []),
    ])
      .then(([nextAccounts, nextModels, nextGroups, nextQuotas, nextUsage, nextTraces]) => {
        setAccounts(nextAccounts);
        setModels(nextModels);
        setGroups(nextGroups);
        setQuotas(nextQuotas);
        setUsage(nextUsage);
        setTraces(nextTraces);
      })
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : "无法加载路由")
      );
  }, []);

  const needle = query.trim().toLowerCase();
  const filteredModels = useMemo(
    () =>
      models.filter(
        (model) =>
          !needle ||
          `${model.provider} ${model.account_name} ${model.model_id} ${model.display_name}`
            .toLowerCase()
            .includes(needle)
      ),
    [models, needle]
  );
  const grouped = useMemo(() => {
    const map = new Map<string, ModelDescriptor[]>();
    for (const model of filteredModels) {
      const key = `${model.provider}/${model.account_name}`;
      map.set(key, [...(map.get(key) ?? []), model]);
    }
    return [...map.entries()].sort(([left], [right]) => left.localeCompare(right));
  }, [filteredModels]);

  if (accounts === null) return <PageSkeleton />;

  const enabledAccounts = accounts.filter((account) => account.enabled);
  const exhausted = quotas.filter((quota) => quota.remaining <= 0);
  const usageByAccount = new Map(
    (usage?.accounts ?? []).map((item) => [
      `${item.provider}/${item.account_name}`,
      item.total_tokens,
    ])
  );

  return (
    <section className="p-6">
      <ManagementPageHeader
        title="路由"
        description="查看 Gateway 当前可路由的 Provider、账号和模型。"
        actions={
          <>
            <Link
              href="/providers"
              className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar"
            >
              添加供应商
            </Link>
            <Link
              href="/routing-groups"
              className="rounded-lg bg-text px-3 py-1.5 text-sm text-white"
            >
              管理路由组
            </Link>
          </>
        }
      />

      <div className="mb-5 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="可用账号"
          value={`${enabledAccounts.length}/${accounts.length}`}
          detail="Provider 账号"
        />
        <MetricCard label="模型路由" value={models.length} detail="可请求模型" />
        <MetricCard label="路由组" value={groups.length} detail="故障转移与选择策略" />
        <MetricCard
          label="用量"
          value={formatNumber(usage?.total_tokens ?? 0)}
          detail={`${usage?.requests ?? 0} 次请求`}
        />
      </div>

      {exhausted.length > 0 && (
        <p className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm text-amber-700">
          {exhausted.length} 个账号配额已耗尽，Gateway 会自动跳过。
        </p>
      )}
      {error && <p className="mb-3 text-sm text-red-500">{error}</p>}

      <label className="mb-4 flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2">
        <SearchIcon className="shrink-0 text-text-secondary" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索 Provider、账号或模型"
          className="min-w-0 flex-1 bg-transparent text-sm outline-none"
        />
      </label>

      {grouped.length === 0 ? (
        <EmptyState
          title="没有可路由模型"
          description="先在供应商页面添加账号并发现模型。"
          action={
            <Link
              href="/providers"
              className="rounded-lg bg-text px-3 py-1.5 text-sm text-white"
            >
              添加供应商
            </Link>
          }
        />
      ) : (
        <div className="space-y-4">
          {grouped.map(([accountLabel, accountModels]) => {
            const account = accounts.find(
              (item) =>
                `${item.provider}/${item.name}` === accountLabel
            );
            return (
              <div key={accountLabel} className="rounded-lg border border-border bg-surface">
                <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
                  <RouteIcon className="text-text-secondary" />
                  <span className="text-sm font-medium">{accountLabel}</span>
                  <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-text-secondary">
                    {account?.enabled ? "enabled" : "disabled"}
                  </span>
                  <span className="flex-1" />
                  <span className="text-xs text-text-secondary">
                    {accountModels.length} models ·{" "}
                    {formatNumber(usageByAccount.get(accountLabel) ?? 0)} tokens
                  </span>
                </div>
                <div className="divide-y divide-border">
                  {accountModels.map((model) => {
                    const routeId = `${model.provider}/${model.model_id}`;
                    const exactId = `${model.provider}/${model.account_name}/${model.model_id}`;
                    return (
                      <div
                        key={model.id}
                        className="grid gap-2 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_140px_100px_auto] sm:items-center"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">{model.display_name}</p>
                          <code className="mt-0.5 block truncate text-xs text-text-secondary">
                            {exactId}
                          </code>
                        </div>
                        <span className="text-xs text-text-secondary">{model.protocol}</span>
                        <span className="text-xs text-text-secondary">
                          {model.context_window
                            ? `${formatNumber(model.context_window)} ctx`
                            : "ctx unknown"}
                        </span>
                        <button
                          type="button"
                          aria-label={`复制模型路由 ${routeId}`}
                          title="复制模型路由"
                          onClick={() => void copyText(routeId)}
                          className="justify-self-start rounded-lg p-1.5 text-text-secondary hover:bg-sidebar hover:text-text"
                        >
                          <CopyIcon width={14} height={14} />
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-8">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-medium">最近路由决策</h2>
          <Link href="/gateway" className="text-xs text-accent hover:underline">
            全部 Gateway 请求
          </Link>
        </div>
        <div className="overflow-hidden rounded-lg border border-border bg-surface">
          {traces.length === 0 ? (
            <p className="px-4 py-8 text-sm text-text-secondary">
              Gateway 还没有路由轨迹。
            </p>
          ) : (
            traces.map((trace, index) => {
              const routing = trace.routing_trace ?? {};
              const attempts = Array.isArray(routing.attempts)
                ? routing.attempts
                : [];
              const selected = routing.selected_account;
              const filtered = routing.filtered_quota;
              return (
                <div
                  key={trace.id}
                  className={`grid gap-2 px-4 py-3 text-sm sm:grid-cols-[minmax(0,1fr)_150px_100px_90px] sm:items-center ${
                    index ? "border-t border-border" : ""
                  }`}
                >
                  <div className="min-w-0">
                    <p className="truncate font-mono text-xs">{trace.model_requested}</p>
                    <p className="mt-0.5 truncate text-xs text-text-secondary">
                      {trace.provider && trace.account_name
                        ? `${trace.provider}/${trace.account_name}`
                        : "未解析账号"}
                    </p>
                  </div>
                  <span className="text-xs text-text-secondary">
                    选中 {typeof selected === "string" ? selected : "—"}
                  </span>
                  <span className="text-xs text-text-secondary">
                    {attempts.length} 次尝试
                  </span>
                  <span className="text-xs text-text-secondary">
                    过滤 {typeof filtered === "number" ? filtered : 0}
                  </span>
                </div>
              );
            })
          )}
        </div>
      </div>
    </section>
  );
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("zh-CN", { notation: "compact" }).format(value);
}
