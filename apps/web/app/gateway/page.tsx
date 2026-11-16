"use client";

import { useEffect, useState } from "react";

import { SecurityCenter } from "@/components/security/SecurityCenter";
import {
  ManagementPageHeader,
  MetricCard,
} from "@/components/ui/ManagementPage";
import {
  fetchGatewayHealth,
  fetchGatewayUsage,
  GATEWAY_URL,
  listGatewayRequests,
  type GatewayRequest,
  type GatewayUsageSummary,
} from "@/lib/gateway-api";

export default function GatewayPage() {
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [usage, setUsage] = useState<GatewayUsageSummary | null>(null);
  const [requests, setRequests] = useState<GatewayRequest[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetchGatewayHealth(),
      fetchGatewayUsage(),
      listGatewayRequests(20),
    ])
      .then(([, nextUsage, nextRequests]) => {
        setHealthy(true);
        setUsage(nextUsage);
        setRequests(nextRequests);
      })
      .catch((reason) => {
        setHealthy(false);
        setError(reason instanceof Error ? reason.message : "无法连接 Gateway");
      });
  }, []);

  return (
    <section className="p-6">
      <ManagementPageHeader
        title="网关"
        description="本机 OpenAI-compatible Gateway、客户端密钥和最近请求。"
        actions={
          <a
            href={`${GATEWAY_URL}/health`}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar"
          >
            打开健康检查
          </a>
        }
      />

      <div className="mb-5 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="状态"
          value={healthy ? "运行中" : healthy === false ? "离线" : "检测中"}
          detail={GATEWAY_URL.replace(/^https?:\/\//, "")}
        />
        <MetricCard label="请求" value={usage?.requests ?? 0} detail="已记录 Gateway 调用" />
        <MetricCard
          label="Token"
          value={formatNumber(usage?.total_tokens ?? 0)}
          detail={`${formatNumber(usage?.input_tokens ?? 0)} 输入`}
        />
        <MetricCard
          label="输出 Token"
          value={formatNumber(usage?.output_tokens ?? 0)}
          detail={`${usage?.accounts.length ?? 0} 个账号`}
        />
      </div>

      {error && (
        <p className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm text-amber-700">
          {error}。共享配置仍可通过下方控制面管理。
        </p>
      )}

      <div className="mb-6 overflow-hidden rounded-lg border border-border bg-surface">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-medium">最近请求</h2>
        </div>
        {requests.length === 0 ? (
          <p className="px-4 py-8 text-sm text-text-secondary">
            Gateway 还没有请求记录。
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-text-secondary">
                  <th className="px-4 py-2 font-medium">时间</th>
                  <th className="px-3 py-2 font-medium">模型</th>
                  <th className="px-3 py-2 font-medium">账号</th>
                  <th className="px-3 py-2 font-medium">状态</th>
                  <th className="px-3 py-2 font-medium">耗时</th>
                  <th className="px-4 py-2 font-medium">Token</th>
                </tr>
              </thead>
              <tbody>
                {requests.map((request) => (
                  <tr key={request.id} className="border-b border-border last:border-0">
                    <td className="px-4 py-2 text-xs text-text-secondary">
                      {formatDate(request.created_at)}
                    </td>
                    <td className="max-w-52 truncate px-3 py-2 font-mono text-xs">
                      {request.model_requested}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {request.provider && request.account_name
                        ? `${request.provider}/${request.account_name}`
                        : "—"}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`text-xs ${
                          request.status === "error" ? "text-red-500" : "text-emerald-600"
                        }`}
                      >
                        {request.status}
                        {request.http_status ? ` ${request.http_status}` : ""}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs text-text-secondary">
                      {request.duration_ms === null ? "—" : `${request.duration_ms}ms`}
                    </td>
                    <td className="px-4 py-2 text-xs tabular-nums">
                      {formatNumber(request.total_tokens)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="border-t border-border pt-6">
        <SecurityCenter
          initialTab="sharing"
          visibleTabs={["sharing"]}
          title="网关共享与访问"
          description="控制网络暴露、命名 Key、预算和访问范围。"
          embedded
        />
      </div>
    </section>
  );
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("zh-CN", { notation: "compact" }).format(value);
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
