"use client";

import { useEffect, useMemo, useState } from "react";
import {
  createGatewayKey,
  createSearchKey,
  deletePlugin,
  deletePrivacyRule,
  deleteSearchKey,
  discoverPlugins,
  discoverSubscriptions,
  generateImage,
  getPrivacySettings,
  getSharingConfig,
  installPlugin,
  listGatewayKeys,
  listMediaJobs,
  listPlugins,
  listPrivacyAudit,
  listPrivacyRules,
  listSearchKeys,
  listSubscriptions,
  m7Endpoint,
  refreshSubscription,
  revokeGatewayKey,
  rotateGatewayKey,
  savePrivacyRule,
  scheduleSubscriptionWarmup,
  setPluginEnabled,
  setSearchKeyEnabled,
  startVideo,
  testPrivacy,
  updatePrivacySettings,
  updateSharingConfig,
  verifyPlugin,
  type GatewayKey,
  type DiscoveredPlugin,
  type MediaJob,
  type PluginRecord,
  type PrivacyAuditEntry,
  type PrivacyRule,
  type PrivacySettings,
  type SearchKey,
  type SharingConfig,
  type SubscriptionAccount,
} from "@/lib/m7-api";
import { CheckIcon, CopyIcon, ExternalLinkIcon, TrashIcon } from "@/components/ui/icons";
import { copyText } from "@/lib/clipboard";

export type SecurityTab =
  | "privacy"
  | "sharing"
  | "subscriptions"
  | "tools"
  | "plugins"
  | "media";
const TABS: Array<{ id: SecurityTab; label: string }> = [
  { id: "privacy", label: "隐私" },
  { id: "sharing", label: "共享" },
  { id: "subscriptions", label: "订阅" },
  { id: "tools", label: "工具" },
  { id: "plugins", label: "插件" },
  { id: "media", label: "媒体" },
];

export function SecurityCenter({
  initialTab = "privacy",
  visibleTabs,
  title = "安全与共享",
  description = "隐私脱敏、Gateway 访问、订阅账号与工具运行时。",
  embedded = false,
}: {
  initialTab?: SecurityTab;
  visibleTabs?: SecurityTab[];
  title?: string;
  description?: string;
  embedded?: boolean;
}) {
  const [tab, setTab] = useState<SecurityTab>(initialTab);
  const [privacy, setPrivacy] = useState<PrivacySettings | null>(null);
  const [rules, setRules] = useState<PrivacyRule[]>([]);
  const [audit, setAudit] = useState<PrivacyAuditEntry[]>([]);
  const [sharing, setSharing] = useState<SharingConfig | null>(null);
  const [gatewayKeys, setGatewayKeys] = useState<GatewayKey[]>([]);
  const [subscriptions, setSubscriptions] = useState<SubscriptionAccount[]>([]);
  const [searchKeys, setSearchKeys] = useState<SearchKey[]>([]);
  const [plugins, setPlugins] = useState<PluginRecord[]>([]);
  const [mediaJobs, setMediaJobs] = useState<MediaJob[]>([]);
  const [newPlaintextKey, setNewPlaintextKey] = useState<string | null>(null);
  const [privacyText, setPrivacyText] = useState("alice@example.com");
  const [privacyResult, setPrivacyResult] = useState<string | null>(null);
  const [ruleDraft, setRuleDraft] = useState({
    id: "",
    title: "",
    pattern: "",
    action: "mask" as "mask" | "warn" | "block",
  });
  const [keyDraft, setKeyDraft] = useState({
    name: "",
    scopes: "chat.read",
    models: "",
    daily: "",
  });
  const [searchDraft, setSearchDraft] = useState({ name: "", key: "" });
  const [pluginPath, setPluginPath] = useState("");
  const [pluginRepository, setPluginRepository] = useState("");
  const [discoveredPlugins, setDiscoveredPlugins] = useState<DiscoveredPlugin[]>([]);
  const [imagePrompt, setImagePrompt] = useState("");
  const [videoPrompt, setVideoPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      getPrivacySettings(),
      listPrivacyRules(),
      listPrivacyAudit(),
      getSharingConfig(),
      listGatewayKeys(),
      listSubscriptions(),
      listSearchKeys(),
      listPlugins(),
      listMediaJobs(),
    ])
      .then(
        ([
          nextPrivacy,
          nextRules,
          nextAudit,
          nextSharing,
          nextKeys,
          nextSubscriptions,
          nextSearch,
          nextPlugins,
          nextJobs,
        ]) => {
          setPrivacy(nextPrivacy);
          setRules(nextRules);
          setAudit(nextAudit);
          setSharing(nextSharing);
          setGatewayKeys(nextKeys);
          setSubscriptions(nextSubscriptions);
          setSearchKeys(nextSearch);
          setPlugins(nextPlugins);
          setMediaJobs(nextJobs);
        }
      )
      .catch((err) => setError(messageOf(err, "无法加载安全中心")));
  }, []);

  const sortedRules = useMemo(
    () => [...rules].sort((a, b) => Number(a.builtin) - Number(b.builtin)),
    [rules]
  );

  const run = async (action: () => Promise<void>, success?: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      if (success) setNotice(success);
    } catch (err) {
      setError(messageOf(err, "操作失败"));
    } finally {
      setBusy(false);
    }
  };

  const shownTabs = visibleTabs
    ? TABS.filter((item) => visibleTabs.includes(item.id))
    : TABS;

  return (
    <section className={embedded ? "" : "p-6"}>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className={embedded ? "text-base font-semibold" : "text-xl font-semibold"}>
            {title}
          </h1>
          <p className="mt-1 text-sm text-text-secondary">{description}</p>
        </div>
      </div>

      {shownTabs.length > 1 && (
        <div className="mb-5 flex flex-wrap gap-1 border-b border-border pb-2">
        {shownTabs.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            className={`rounded-lg px-3 py-1.5 text-sm ${
              tab === item.id ? "bg-text text-white" : "text-text-secondary hover:bg-sidebar"
            }`}
          >
            {item.label}
          </button>
        ))}
        </div>
      )}

      {error && <p className="mb-3 text-sm text-red-500">{error}</p>}
      {notice && <p className="mb-3 text-sm text-emerald-600">{notice}</p>}

      {tab === "privacy" && privacy && (
        <div className="space-y-8">
          <div className="grid gap-3 sm:grid-cols-3">
            <Toggle
              label="启用隐私脱敏"
              checked={privacy.enabled}
              onChange={(enabled) =>
                void run(async () => setPrivacy(await updatePrivacySettings({ enabled })))
              }
            />
            <Toggle
              label="失败时阻断"
              checked={privacy.fail_closed}
              onChange={(fail_closed) =>
                void run(async () => {
                  setPrivacy(await updatePrivacySettings({ fail_closed }));
                })
              }
            />
            <label className="flex items-center gap-2 text-sm">
              占位符有效期
              <input
                type="number"
                min={1}
                value={privacy.placeholder_ttl_seconds}
                onChange={(event) =>
                  setPrivacy({
                    ...privacy,
                    placeholder_ttl_seconds: Number(event.target.value),
                  })
                }
                onBlur={() =>
                  void run(async () => {
                    setPrivacy(
                      await updatePrivacySettings({
                        placeholder_ttl_seconds: privacy.placeholder_ttl_seconds,
                      })
                    );
                  })
                }
                className="w-28 rounded-lg border border-border px-2 py-1.5"
              />
              秒
            </label>
          </div>

          <div>
            <h2 className="mb-2 text-sm font-medium">规则</h2>
            <div className="space-y-1">
              {sortedRules.map((rule) => (
                <div
                  key={rule.id}
                  className="grid gap-2 border-b border-border py-2 text-sm sm:grid-cols-[1fr_1.3fr_80px_auto]"
                >
                  <span>{rule.title}</span>
                  <code className="truncate text-xs text-text-secondary">{rule.pattern}</code>
                  <span className="text-xs text-text-secondary">
                    {rule.builtin ? "内置" : rule.action}
                  </span>
                  {rule.builtin ? (
                    <span />
                  ) : (
                    <button
                      type="button"
                      aria-label={`删除规则 ${rule.title}`}
                      onClick={() =>
                        void run(async () => {
                          await deletePrivacyRule(rule.id);
                          setRules((current) =>
                            current.filter((item) => item.id !== rule.id)
                          );
                        }, "隐私规则已删除")
                      }
                      className="p-1 text-text-secondary hover:text-red-500"
                    >
                      <TrashIcon width={14} height={14} />
                    </button>
                  )}
                </div>
              ))}
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-[130px_180px_1fr_100px_auto]">
              <input
                value={ruleDraft.id}
                onChange={(event) => setRuleDraft({ ...ruleDraft, id: event.target.value })}
                placeholder="规则 ID"
                className="rounded-lg border border-border px-3 py-1.5 text-sm"
              />
              <input
                value={ruleDraft.title}
                onChange={(event) => setRuleDraft({ ...ruleDraft, title: event.target.value })}
                placeholder="名称"
                className="rounded-lg border border-border px-3 py-1.5 text-sm"
              />
              <input
                value={ruleDraft.pattern}
                onChange={(event) => setRuleDraft({ ...ruleDraft, pattern: event.target.value })}
                placeholder="正则表达式"
                className="min-w-0 rounded-lg border border-border px-3 py-1.5 font-mono text-sm"
              />
              <select
                value={ruleDraft.action}
                onChange={(event) =>
                  setRuleDraft({
                    ...ruleDraft,
                    action: event.target.value as typeof ruleDraft.action,
                  })
                }
                className="rounded-lg border border-border px-2 py-1.5 text-sm"
              >
                <option value="mask">mask</option>
                <option value="warn">warn</option>
                <option value="block">block</option>
              </select>
              <button
                type="button"
                onClick={() =>
                  void run(async () => {
                    const rule = await savePrivacyRule(ruleDraft);
                    setRules((current) => [
                      ...current.filter((item) => item.id !== rule.id),
                      rule,
                    ]);
                    setRuleDraft({ id: "", title: "", pattern: "", action: "mask" });
                  }, "隐私规则已保存")
                }
                disabled={busy || !ruleDraft.id || !ruleDraft.title || !ruleDraft.pattern}
                className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar disabled:opacity-40"
              >
                添加
              </button>
            </div>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <div>
              <h2 className="mb-2 text-sm font-medium">脱敏测试</h2>
              <textarea
                value={privacyText}
                onChange={(event) => setPrivacyText(event.target.value)}
                className="min-h-28 w-full rounded-lg border border-border p-3 font-mono text-sm"
              />
              <button
                type="button"
                onClick={() =>
                  void run(async () => {
                    setPrivacyResult((await testPrivacy(privacyText)).text);
                  })
                }
                className="mt-2 rounded-lg bg-text px-3 py-1.5 text-sm text-white"
              >
                运行
              </button>
              {privacyResult && (
                <pre className="mt-2 whitespace-pre-wrap rounded-lg bg-sidebar p-3 text-sm">
                  {privacyResult}
                </pre>
              )}
            </div>
            <div>
              <h2 className="mb-2 text-sm font-medium">最近审计</h2>
              <div className="max-h-64 overflow-y-auto">
                {audit.slice(0, 20).map((item) => (
                  <div key={item.id} className="border-b border-border py-2 text-xs">
                    <span className="font-medium">{item.rule_id}</span>
                    <span className="ml-2 text-text-secondary">{item.action}</span>
                    <span className="ml-2 text-text-secondary">{item.created_at}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === "sharing" && sharing && (
        <div className="space-y-8">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Toggle
              label="允许 Gateway 共享"
              checked={sharing.enabled}
              onChange={(enabled) =>
                void run(async () => {
                  setSharing(await updateSharingConfig({ enabled }));
                })
              }
            />
            <label className="text-sm">
              绑定地址
              <input
                value={sharing.bind_host}
                onChange={(event) =>
                  setSharing({ ...sharing, bind_host: event.target.value })
                }
                onBlur={() =>
                  void run(async () => {
                    setSharing(await updateSharingConfig({
                      enabled: sharing.enabled,
                      bind_host: sharing.bind_host,
                      exposure_warning_acknowledged:
                        sharing.exposure_warning_acknowledged,
                    }));
                  })
                }
                className="mt-1 w-full rounded-lg border border-border px-3 py-1.5 font-mono"
              />
            </label>
            <label className="text-sm">
              端口
              <input
                type="number"
                value={sharing.port}
                onChange={(event) =>
                  setSharing({ ...sharing, port: Number(event.target.value) })
                }
                className="mt-1 w-full rounded-lg border border-border px-3 py-1.5"
              />
            </label>
            <label className="text-sm">
              TLS
              <select
                value={sharing.tls_mode}
                onChange={(event) =>
                  setSharing({
                    ...sharing,
                    tls_mode: event.target.value as SharingConfig["tls_mode"],
                  })
                }
                className="mt-1 w-full rounded-lg border border-border px-3 py-1.5"
              >
                <option value="off">off</option>
                <option value="custom">custom</option>
                <option value="mtls">mTLS</option>
              </select>
            </label>
          </div>
          <div className="flex flex-wrap items-start justify-between gap-3 border-y border-border py-3">
            <p className="text-sm text-text-secondary">{sharing.warning}</p>
            <label className="flex shrink-0 items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={sharing.exposure_warning_acknowledged}
                onChange={(event) =>
                  setSharing({
                    ...sharing,
                    exposure_warning_acknowledged: event.target.checked,
                  })
                }
              />
              已确认网络暴露风险
            </label>
          </div>
          <button
            type="button"
            onClick={() =>
              void run(async () => {
                setSharing(
                  await updateSharingConfig({
                    enabled: sharing.enabled,
                    bind_host: sharing.bind_host,
                    port: sharing.port,
                    exposure_warning_acknowledged:
                      sharing.exposure_warning_acknowledged,
                    tls_mode: sharing.tls_mode,
                    require_client_cert: sharing.require_client_cert,
                  })
                );
              }, "共享配置已保存")
            }
            className="rounded-lg bg-text px-3 py-1.5 text-sm text-white"
          >
            保存共享配置
          </button>

          <div>
            <h2 className="mb-2 text-sm font-medium">Gateway Keys</h2>
            {newPlaintextKey && (
              <div className="mb-3 flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3">
                <code className="min-w-0 flex-1 truncate text-xs">{newPlaintextKey}</code>
                <button
                  type="button"
                  aria-label="复制 Gateway Key"
                  onClick={() => void copyText(newPlaintextKey)}
                  className="p-1 text-text-secondary"
                >
                  <CopyIcon />
                </button>
              </div>
            )}
            <div className="space-y-1">
              {gatewayKeys.map((key) => (
                <div
                  key={key.id}
                  className="flex flex-wrap items-center gap-2 border-b border-border py-2 text-sm"
                >
                  <span className="font-medium">{key.name}</span>
                  <code className="text-xs text-text-secondary">{key.key_prefix}…</code>
                  <span className="text-xs text-text-secondary">{key.scopes.join(", ")}</span>
                  <span className="flex-1" />
                  <button
                    type="button"
                    onClick={() =>
                      void run(async () => {
                        const rotated = await rotateGatewayKey(key.id);
                        setGatewayKeys((current) =>
                          current.map((item) => (item.id === key.id ? rotated : item))
                        );
                        setNewPlaintextKey(rotated.key);
                      }, "Gateway Key 已轮换")
                    }
                    className="rounded-lg border border-border px-2 py-1 text-xs"
                  >
                    轮换
                  </button>
                  <button
                    type="button"
                    aria-label={`撤销 ${key.name}`}
                    onClick={() =>
                      void run(async () => {
                        await revokeGatewayKey(key.id);
                        setGatewayKeys((current) =>
                          current.filter((item) => item.id !== key.id)
                        );
                      }, "Gateway Key 已撤销")
                    }
                    className="p-1 text-text-secondary hover:text-red-500"
                  >
                    <TrashIcon width={14} height={14} />
                  </button>
                </div>
              ))}
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-[180px_180px_1fr_120px_auto]">
              <input
                value={keyDraft.name}
                onChange={(event) => setKeyDraft({ ...keyDraft, name: event.target.value })}
                placeholder="Key 名称"
                className="rounded-lg border border-border px-3 py-1.5 text-sm"
              />
              <input
                value={keyDraft.scopes}
                onChange={(event) => setKeyDraft({ ...keyDraft, scopes: event.target.value })}
                placeholder="scopes"
                className="rounded-lg border border-border px-3 py-1.5 text-sm"
              />
              <input
                value={keyDraft.models}
                onChange={(event) => setKeyDraft({ ...keyDraft, models: event.target.value })}
                placeholder="允许模型，逗号分隔"
                className="min-w-0 rounded-lg border border-border px-3 py-1.5 text-sm"
              />
              <input
                value={keyDraft.daily}
                onChange={(event) => setKeyDraft({ ...keyDraft, daily: event.target.value })}
                placeholder="每日请求"
                type="number"
                className="rounded-lg border border-border px-3 py-1.5 text-sm"
              />
              <button
                type="button"
                onClick={() =>
                  void run(async () => {
                    const created = await createGatewayKey({
                      name: keyDraft.name,
                      scopes: keyDraft.scopes
                        .split(",")
                        .map((item) => item.trim())
                        .filter(Boolean),
                      allowed_models: keyDraft.models
                        .split(",")
                        .map((item) => item.trim())
                        .filter(Boolean),
                      daily_requests: keyDraft.daily ? Number(keyDraft.daily) : null,
                    });
                    setGatewayKeys((current) => [created, ...current]);
                    setNewPlaintextKey(created.key);
                    setKeyDraft({ name: "", scopes: "chat.read", models: "", daily: "" });
                  }, "Gateway Key 已创建")
                }
                disabled={busy || !keyDraft.name}
                className="rounded-lg bg-text px-3 py-1.5 text-sm text-white disabled:opacity-40"
              >
                创建
              </button>
            </div>
          </div>
        </div>
      )}

      {tab === "subscriptions" && (
        <div>
          <div className="mb-3 flex justify-end">
            <button
              type="button"
              onClick={() =>
                void run(async () => {
                  setSubscriptions(await discoverSubscriptions());
                }, "订阅账号扫描完成")
              }
              className="rounded-lg bg-text px-3 py-1.5 text-sm text-white"
            >
              扫描账号
            </button>
          </div>
          <div className="space-y-2">
            {subscriptions.map((account) => (
              <div
                key={account.id}
                className="grid gap-2 border-b border-border py-3 sm:grid-cols-[1fr_auto_auto]"
              >
                <div>
                  <p className="text-sm font-medium">{account.name}</p>
                  <p className="text-xs text-text-secondary">
                    {account.provider} · {account.signed_in ? "已登录" : "未登录"} ·{" "}
                    {account.models.join(", ")}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    void run(async () => {
                      const updated = await refreshSubscription(account.id);
                      setSubscriptions((current) =>
                        current.map((item) => (item.id === account.id ? updated : item))
                      );
                    }, "订阅状态已刷新")
                  }
                  className="rounded-lg border border-border px-3 py-1.5 text-sm"
                >
                  刷新
                </button>
                <button
                  type="button"
                  onClick={() =>
                    void run(async () => {
                      await scheduleSubscriptionWarmup({
                        account_id: account.id,
                        mode: "daily",
                        at_time: "08:00",
                      });
                    }, "Warm-up 计划已保存")
                  }
                  className="rounded-lg border border-border px-3 py-1.5 text-sm"
                >
                  每日 08:00
                </button>
              </div>
            ))}
            {subscriptions.length === 0 && (
              <p className="py-10 text-sm text-text-secondary">未发现已登录订阅。</p>
            )}
          </div>
        </div>
      )}

      {tab === "tools" && (
        <div className="space-y-5">
          <h2 className="text-sm font-medium">搜索 Key</h2>
          <div className="space-y-1">
            {searchKeys.map((key) => (
              <div
                key={key.id}
                className="flex flex-wrap items-center gap-2 border-b border-border py-2 text-sm"
              >
                <span className="font-medium">{key.name}</span>
                <code className="text-xs text-text-secondary">{key.api_key_masked}</code>
                <span className="text-xs text-text-secondary">
                  {key.successes} 成功 · {key.refusals} 拒绝
                </span>
                <span className="flex-1" />
                <button
                  type="button"
                  onClick={() =>
                    void run(async () => {
                      const updated = await setSearchKeyEnabled(key.id, !key.enabled);
                      setSearchKeys((current) =>
                        current.map((item) => (item.id === key.id ? updated : item))
                      );
                    })
                  }
                  className="rounded-lg border border-border px-2 py-1 text-xs"
                >
                  {key.enabled ? "停用" : "启用"}
                </button>
                <button
                  type="button"
                  aria-label={`删除搜索 Key ${key.name}`}
                  onClick={() =>
                    void run(async () => {
                      await deleteSearchKey(key.id);
                      setSearchKeys((current) =>
                        current.filter((item) => item.id !== key.id)
                      );
                    }, "搜索 Key 已删除")
                  }
                  className="p-1 text-text-secondary hover:text-red-500"
                >
                  <TrashIcon width={14} height={14} />
                </button>
              </div>
            ))}
          </div>
          <div className="grid gap-2 sm:grid-cols-[180px_1fr_auto]">
            <input
              value={searchDraft.name}
              onChange={(event) =>
                setSearchDraft({ ...searchDraft, name: event.target.value })
              }
              placeholder="Key 名称"
              className="rounded-lg border border-border px-3 py-1.5 text-sm"
            />
            <input
              value={searchDraft.key}
              onChange={(event) =>
                setSearchDraft({ ...searchDraft, key: event.target.value })
              }
              placeholder="Tavily API Key"
              type="password"
              className="min-w-0 rounded-lg border border-border px-3 py-1.5 text-sm"
            />
            <button
              type="button"
              onClick={() =>
                void run(async () => {
                  const created = await createSearchKey({
                    provider: "tavily",
                    name: searchDraft.name,
                    api_key: searchDraft.key,
                  });
                  setSearchKeys((current) => [created, ...current]);
                  setSearchDraft({ name: "", key: "" });
                }, "搜索 Key 已保存")
              }
              disabled={busy || !searchDraft.name || !searchDraft.key}
              className="rounded-lg bg-text px-3 py-1.5 text-sm text-white disabled:opacity-40"
            >
              添加
            </button>
          </div>
        </div>
      )}

      {tab === "plugins" && (
        <div className="space-y-5">
          <div className="flex gap-2">
            <input
              value={pluginRepository}
              onChange={(event) => setPluginRepository(event.target.value)}
              placeholder="插件仓库目录"
              className="min-w-0 flex-1 rounded-lg border border-border px-3 py-1.5 font-mono text-sm"
            />
            <button
              type="button"
              onClick={() =>
                void run(async () => {
                  setDiscoveredPlugins(await discoverPlugins(pluginRepository));
                }, "插件目录已扫描")
              }
              disabled={busy || !pluginRepository}
              className="rounded-lg border border-border px-3 py-1.5 text-sm disabled:opacity-40"
            >
              发现
            </button>
          </div>
          {discoveredPlugins.length > 0 && (
            <div className="overflow-hidden rounded-lg border border-border bg-surface">
              {discoveredPlugins.map((plugin, index) => (
                <div
                  key={plugin.id}
                  className={`flex flex-wrap items-center gap-2 px-4 py-3 ${
                    index ? "border-t border-border" : ""
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{plugin.name}</p>
                    <p className="mt-0.5 truncate text-xs text-text-secondary">
                      {plugin.version} · {plugin.type} · {plugin.description}
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={busy || plugin.installed}
                    onClick={() =>
                      void run(async () => {
                        const installed = await installPlugin(plugin.path, true);
                        setPlugins((current) => [
                          installed,
                          ...current.filter((item) => item.id !== installed.id),
                        ]);
                        setDiscoveredPlugins((current) =>
                          current.map((item) =>
                            item.id === plugin.id ? { ...item, installed: true } : item
                          )
                        );
                      }, "插件已安装")
                    }
                    className="rounded-lg border border-border px-2 py-1 text-xs disabled:opacity-40"
                  >
                    {plugin.installed ? "已安装" : "安装"}
                  </button>
                </div>
              ))}
            </div>
          )}
          <div className="flex gap-2">
            <input
              value={pluginPath}
              onChange={(event) => setPluginPath(event.target.value)}
              placeholder="本地插件目录"
              className="min-w-0 flex-1 rounded-lg border border-border px-3 py-1.5 font-mono text-sm"
            />
            <button
              type="button"
              onClick={() =>
                void run(async () => {
                  const plugin = await installPlugin(pluginPath);
                  setPlugins((current) => [
                    plugin,
                    ...current.filter((item) => item.id !== plugin.id),
                  ]);
                  setPluginPath("");
                }, "插件已安装")
              }
              disabled={busy || !pluginPath}
              className="rounded-lg bg-text px-3 py-1.5 text-sm text-white disabled:opacity-40"
            >
              安装
            </button>
          </div>
          <div className="space-y-2">
            {plugins.map((plugin) => (
              <div key={plugin.id} className="border-b border-border py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{plugin.name}</span>
                  <span className="text-xs text-text-secondary">
                    {plugin.version} · {plugin.type} · {plugin.runtime}
                  </span>
                  {plugin.enabled && (
                    <CheckIcon width={14} height={14} className="text-emerald-600" />
                  )}
                  <span className="flex-1" />
                  <button
                    type="button"
                    onClick={() =>
                      void run(async () => {
                        const updated = await setPluginEnabled(plugin.id, !plugin.enabled);
                        setPlugins((current) =>
                          current.map((item) => (item.id === plugin.id ? updated : item))
                        );
                      })
                    }
                    className="rounded-lg border border-border px-2 py-1 text-xs"
                  >
                    {plugin.enabled ? "停用" : "启用"}
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      void run(async () => {
                        const result = await verifyPlugin(plugin.id);
                        if (!result.ok) throw new Error("插件完整性校验失败");
                      }, "插件完整性校验通过")
                    }
                    className="rounded-lg border border-border px-2 py-1 text-xs"
                  >
                    校验
                  </button>
                  <button
                    type="button"
                    aria-label={`卸载插件 ${plugin.name}`}
                    onClick={() =>
                      void run(async () => {
                        await deletePlugin(plugin.id);
                        setPlugins((current) =>
                          current.filter((item) => item.id !== plugin.id)
                        );
                      }, "插件已卸载")
                    }
                    className="p-1 text-text-secondary hover:text-red-500"
                  >
                    <TrashIcon width={14} height={14} />
                  </button>
                </div>
                <p className="mt-1 text-xs text-text-secondary">
                  {plugin.capabilities?.join(", ")}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === "media" && (
        <div className="space-y-5">
          <div className="flex gap-2">
            <input
              value={imagePrompt}
              onChange={(event) => setImagePrompt(event.target.value)}
              placeholder="图片描述"
              className="min-w-0 flex-1 rounded-lg border border-border px-3 py-1.5 text-sm"
            />
            <button
              type="button"
              onClick={() =>
                void run(async () => {
                  const job = await generateImage(imagePrompt);
                  setMediaJobs((current) => [job, ...current]);
                  setImagePrompt("");
                }, "图片已生成")
              }
              disabled={busy || !imagePrompt.trim()}
              className="rounded-lg bg-text px-3 py-1.5 text-sm text-white disabled:opacity-40"
            >
              生成图片
            </button>
          </div>
          <div className="flex gap-2">
            <input
              value={videoPrompt}
              onChange={(event) => setVideoPrompt(event.target.value)}
              placeholder="视频描述"
              className="min-w-0 flex-1 rounded-lg border border-border px-3 py-1.5 text-sm"
            />
            <button
              type="button"
              onClick={() =>
                void run(async () => {
                  const job = await startVideo(videoPrompt);
                  setMediaJobs((current) => [job, ...current]);
                  setVideoPrompt("");
                }, "视频任务已创建")
              }
              disabled={busy || !videoPrompt.trim()}
              className="rounded-lg border border-border px-3 py-1.5 text-sm disabled:opacity-40"
            >
              创建视频任务
            </button>
          </div>
          <div className="space-y-2">
            {mediaJobs.map((job) => (
              <div key={job.id} className="border-b border-border py-2 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{job.kind}</span>
                  <span className="text-text-secondary">{job.status}</span>
                  <span className="flex-1" />
                  {job.path && (
                    <a
                      href={m7Endpoint(`media/files/${job.id}`)}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-accent"
                    >
                      打开
                      <ExternalLinkIcon width={12} height={12} />
                    </a>
                  )}
                </div>
                <p className="mt-1 truncate text-xs text-text-secondary">{job.prompt}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative h-5 w-9 rounded-full transition-colors ${
          checked ? "bg-emerald-500" : "bg-border"
        }`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
            checked ? "translate-x-4" : "translate-x-0.5"
          }`}
        />
      </button>
      {label}
    </label>
  );
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}
