"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import {
  listAgentCatalog,
  type AgentPlatformAgent,
} from "@/lib/agent-platform-api";
import {
  listProviderAccounts,
  listRoutingGroups,
} from "@/lib/model-control-api";

export function AgentQuickStart() {
  const [providerCount, setProviderCount] = useState(0);
  const [groups, setGroups] = useState(0);
  const [agents, setAgents] = useState<AgentPlatformAgent[]>([]);

  useEffect(() => {
    Promise.allSettled([
      listProviderAccounts(),
      listAgentCatalog(),
      listRoutingGroups(),
    ]).then(([providers, catalog, routingGroups]) => {
      if (providers.status === "fulfilled") {
        setProviderCount(providers.value.filter((account) => account.enabled).length);
      }
      if (catalog.status === "fulfilled") {
        setAgents(catalog.value.filter((agent) => agent.installed));
      }
      if (routingGroups.status === "fulfilled") {
        setGroups(routingGroups.value.length);
      }
    });
  }, []);

  const completed = Number(providerCount > 0) + Number(agents.length > 0) + Number(groups > 0);
  const visibleAgents = agents.slice(0, 6);

  return (
    <div className="mb-6 rounded-lg border border-border bg-surface px-5 py-4">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-medium">快速上手</h2>
        <span className="text-xs text-text-secondary">已完成 {completed}/3</span>
      </div>
      <div className="mt-3 divide-y divide-border">
        <QuickStartStep
          number={1}
          title="添加模型来源"
          description="接入订阅账号、Provider 账号或 API Key。"
          complete={providerCount > 0}
          action={
            <Link
              href="/providers"
              className="inline-flex rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white"
            >
              {providerCount > 0 ? "管理供应商" : "添加供应商"}
            </Link>
          }
        />
        <QuickStartStep
          number={2}
          title="接入一个 Agent"
          description={
            agents.length
              ? `已发现 ${agents.length} 个本地 Agent。`
              : "扫描本机 Claude Code、Codex、Gemini CLI 等 Agent。"
          }
          complete={agents.length > 0}
          action={
            <div className="flex flex-wrap gap-1.5">
              {visibleAgents.map((agent) => (
                <Link
                  key={agent.id}
                  href="/agents"
                  className="rounded-full border border-border px-2.5 py-1 text-xs text-text-secondary hover:bg-sidebar"
                >
                  {agent.name}
                </Link>
              ))}
              {agents.length > visibleAgents.length && (
                <Link
                  href="/agents"
                  className="rounded-full border border-border px-2.5 py-1 text-xs text-text-secondary"
                >
                  还有 {agents.length - visibleAgents.length} 个
                </Link>
              )}
              {agents.length === 0 && (
                <span className="text-xs text-text-secondary">下方“外部 Agent 平台”可重新发现。</span>
              )}
            </div>
          }
        />
        <QuickStartStep
          number={3}
          title="设置路由（可选）"
          description="把请求分发给合适的模型，并在失败时自动切换。"
          complete={groups > 0}
          action={
            <Link
              href="/routing-groups"
              className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar"
            >
              {groups > 0 ? `管理 ${groups} 个路由组` : "创建路由组"}
            </Link>
          }
        />
      </div>
    </div>
  );
}

function QuickStartStep({
  number,
  title,
  description,
  complete,
  action,
}: {
  number: number;
  title: string;
  description: string;
  complete: boolean;
  action: ReactNode;
}) {
  return (
    <div className="grid gap-3 py-3 sm:grid-cols-[32px_minmax(0,1fr)_auto] sm:items-center">
      <span
        className={`flex h-6 w-6 items-center justify-center rounded-full border text-xs ${
          complete
            ? "border-emerald-500 bg-emerald-500 text-white"
            : "border-border text-text-secondary"
        }`}
      >
        {complete ? "✓" : number}
      </span>
      <div>
        <p className="text-sm font-medium">{title}</p>
        <p className="mt-0.5 text-xs text-text-secondary">{description}</p>
      </div>
      {action}
    </div>
  );
}
