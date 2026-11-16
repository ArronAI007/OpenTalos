"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ThemeToggle } from "@/components/ThemeToggle";
import {
  ManagementPageHeader,
  MetricCard,
} from "@/components/ui/ManagementPage";
import {
  ActivityIcon,
  BeakerIcon,
  BrainIcon,
  ChartBarIcon,
  ChevronRightIcon,
  ServerIcon,
  ShieldIcon,
  TelescopeIcon,
} from "@/components/ui/icons";
import {
  fetchConfig,
  listCustomAgents,
  type AppConfig,
} from "@/lib/api";
import {
  listProviderAccounts,
  type ProviderAccount,
} from "@/lib/model-control-api";
import { fetchGatewayHealth, GATEWAY_URL } from "@/lib/gateway-api";
import { LEGACY_NAV_ITEMS } from "@/lib/navigation";
import {
  checkForUpdate,
  downloadUpdate,
  fetchReleaseInfo,
  installStagedUpdate,
  type ReleaseInfo,
  type UpdateCheckResult,
} from "@/lib/release-api";

const LEGACY_ICONS = {
  "/skills": ChartBarIcon,
  "/mcp": ServerIcon,
  "/memory": BrainIcon,
  "/runs": ActivityIcon,
  "/eval": ChartBarIcon,
  "/agentrl": BeakerIcon,
  "/deepresearch": TelescopeIcon,
} as const;

export default function SettingsPage() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [accounts, setAccounts] = useState<ProviderAccount[]>([]);
  const [agentCount, setAgentCount] = useState(0);
  const [gatewayHealthy, setGatewayHealthy] = useState<boolean | null>(null);
  const [release, setRelease] = useState<ReleaseInfo | null>(null);
  const [update, setUpdate] = useState<UpdateCheckResult | null>(null);
  const [updateBusy, setUpdateBusy] = useState(false);
  const [updateMessage, setUpdateMessage] = useState<string | null>(null);

  useEffect(() => {
    Promise.allSettled([
      fetchConfig(),
      listProviderAccounts(),
      listCustomAgents(),
      fetchGatewayHealth(),
      fetchReleaseInfo(),
    ]).then(([configResult, accountResult, agentResult, gatewayResult, releaseResult]) => {
      if (configResult.status === "fulfilled") setConfig(configResult.value);
      if (accountResult.status === "fulfilled") setAccounts(accountResult.value);
      if (agentResult.status === "fulfilled") setAgentCount(agentResult.value.length);
      setGatewayHealthy(gatewayResult.status === "fulfilled");
      if (releaseResult.status === "fulfilled") setRelease(releaseResult.value);
    });
  }, []);

  async function handleUpdateCheck() {
    setUpdateBusy(true);
    setUpdateMessage(null);
    try {
      const result = await checkForUpdate();
      setUpdate(result);
      setUpdateMessage(
        result.available
          ? `发现新版本 ${result.manifest.version}`
          : `当前已是最新版本 ${result.current_version}`,
      );
    } catch (error) {
      setUpdateMessage(error instanceof Error ? error.message : "检查更新失败");
    } finally {
      setUpdateBusy(false);
    }
  }

  async function handleUpdateDownload() {
    setUpdateBusy(true);
    setUpdateMessage(null);
    try {
      const pending = await downloadUpdate();
      setRelease((current) => (current ? { ...current, pending } : current));
      setUpdateMessage(`版本 ${pending.version} 已下载并校验`);
    } catch (error) {
      setUpdateMessage(error instanceof Error ? error.message : "下载更新失败");
    } finally {
      setUpdateBusy(false);
    }
  }

  async function handleUpdateInstall() {
    setUpdateBusy(true);
    setUpdateMessage(null);
    try {
      await installStagedUpdate();
      setUpdateMessage("正在重启并安装更新…");
    } catch (error) {
      setUpdateBusy(false);
      setUpdateMessage(error instanceof Error ? error.message : "启动安装失败");
    }
  }

  return (
    <section className="p-6">
      <ManagementPageHeader
        title="设置"
        description="桌面运行状态、外观和高级功能入口。"
      />

      <div className="mb-6 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="API"
          value={config ? "运行中" : "检测中"}
          detail={config?.model_name ?? "模型配置待检测"}
        />
        <MetricCard
          label="Gateway"
          value={
            gatewayHealthy ? "运行中" : gatewayHealthy === false ? "离线" : "检测中"
          }
          detail={GATEWAY_URL.replace(/^https?:\/\//, "")}
        />
        <MetricCard
          label="Provider 账号"
          value={accounts.length}
          detail={`${accounts.filter((account) => account.enabled).length} 个已启用`}
        />
        <MetricCard label="自建 Agent" value={agentCount} detail="OpenTalos ReAct Agent" />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-lg border border-border bg-surface p-4">
          <h2 className="text-sm font-medium">运行环境</h2>
          <dl className="mt-3 space-y-2 text-sm">
            <SettingRow label="模型" value={config?.model_name ?? "未配置"} />
            <SettingRow
              label="技能目录"
              value={
                config?.skills_reachable === null
                  ? "检测中"
                  : config?.skills_reachable
                    ? "可用"
                    : "不可用"
              }
            />
            <SettingRow label="桌面外壳" value="pywebview + pystray" />
            <SettingRow label="网关地址" value={GATEWAY_URL.replace(/^https?:\/\//, "")} />
          </dl>
        </section>

        <section className="rounded-lg border border-border bg-surface p-4">
          <h2 className="text-sm font-medium">外观</h2>
          <div className="mt-3 flex items-center justify-between gap-3">
            <div>
              <p className="text-sm">主题</p>
              <p className="mt-0.5 text-xs text-text-secondary">
                在浅色和深色界面之间切换。
              </p>
            </div>
            <ThemeToggle />
          </div>
        </section>
      </div>

      <section className="mt-6 rounded-lg border border-border bg-surface p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-medium">应用更新</h2>
            <p className="mt-1 text-xs text-text-secondary">
              {release
                ? `OpenTalos ${release.version} · ${release.platform}/${release.arch}`
                : "正在读取客户端版本"}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleUpdateCheck}
              disabled={updateBusy || !release?.configured}
              className="rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-sidebar disabled:cursor-not-allowed disabled:opacity-50"
            >
              检查更新
            </button>
            {update?.available && (
              <button
                type="button"
                onClick={handleUpdateDownload}
                disabled={updateBusy}
                className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                下载更新
              </button>
            )}
            {release?.pending && (
              <button
                type="button"
                onClick={handleUpdateInstall}
                disabled={updateBusy}
                className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                重启并安装
              </button>
            )}
          </div>
        </div>
        {release && !release.configured && (
          <p className="mt-3 text-xs text-text-secondary">
            当前构建未配置签名更新清单。
          </p>
        )}
        {release?.pending && (
          <p className="mt-3 text-xs text-text-secondary">
            已暂存版本 {release.pending.version}，重启后由系统安装器完成切换。
          </p>
        )}
        {updateMessage && (
          <p className="mt-3 text-xs text-text-secondary">{updateMessage}</p>
        )}
      </section>

      <section className="mt-6 rounded-lg border border-border bg-surface">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-medium">高级功能</h2>
        </div>
        <div className="divide-y divide-border">
          {LEGACY_NAV_ITEMS.map((item) => {
            const Icon =
              LEGACY_ICONS[item.href as keyof typeof LEGACY_ICONS] ?? ActivityIcon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className="flex items-center gap-3 px-4 py-3 text-sm hover:bg-sidebar"
              >
                <Icon className="text-text-secondary" />
                <span className="min-w-0 flex-1">{item.label}</span>
                <ChevronRightIcon className="text-text-secondary" />
              </Link>
            );
          })}
          <Link
            href="/security"
            className="flex items-center gap-3 px-4 py-3 text-sm hover:bg-sidebar"
          >
            <ShieldIcon className="text-text-secondary" />
            <span className="min-w-0 flex-1">安全与共享控制面</span>
            <ChevronRightIcon className="text-text-secondary" />
          </Link>
        </div>
      </section>

      <p className="mt-6 text-xs text-text-secondary">
        OpenTalos Desktop · Python + Next.js · 本地优先
      </p>
    </section>
  );
}

function SettingRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-text-secondary">{label}</dt>
      <dd className="max-w-[65%] truncate font-mono text-xs">{value}</dd>
    </div>
  );
}
