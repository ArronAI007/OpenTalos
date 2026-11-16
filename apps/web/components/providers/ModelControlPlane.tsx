"use client";

import { useEffect, useState } from "react";
import {
  createProviderAccount,
  deleteControlPlaneProfile,
  deleteProviderAccount,
  discoverProviderModels,
  importLegacyProviderConfigs,
  listControlPlaneModels,
  listControlPlaneProfiles,
  listModelControlPresets,
  listProviderAccounts,
  modelControlPresetDefaults,
  saveControlPlaneProfile,
  updateProviderAccount,
  type ControlPlaneProfile,
  type ModelDescriptor,
  type ProviderAccount,
  type ProviderPreset,
} from "@/lib/model-control-api";
import { TrashIcon } from "@/components/ui/icons";

interface AccountForm {
  provider: string;
  name: string;
  backend: ProviderPreset["backend"];
  baseUrl: string;
  apiKey: string;
  proxyUrl: string;
}

const EMPTY_FORM: AccountForm = {
  provider: "",
  name: "",
  backend: "openai-compatible",
  baseUrl: "",
  apiKey: "",
  proxyUrl: "",
};

const GATEWAY_URL =
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://127.0.0.1:3425";

export function ModelControlPlane() {
  const [presets, setPresets] = useState<ProviderPreset[]>([]);
  const [accounts, setAccounts] = useState<ProviderAccount[]>([]);
  const [profiles, setProfiles] = useState<ControlPlaneProfile[]>([]);
  const [models, setModels] = useState<Record<string, ModelDescriptor[]>>({});
  const [form, setForm] = useState<AccountForm>(EMPTY_FORM);
  const [profileName, setProfileName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshAccounts = async () => {
    const next = await listProviderAccounts();
    setAccounts(next);
    const entries = await Promise.all(
      next.map(async (account) => [
        account.id,
        await listControlPlaneModels(account.id),
      ] as const)
    );
    setModels(Object.fromEntries(entries));
  };

  useEffect(() => {
    Promise.all([
      listModelControlPresets(),
      listProviderAccounts(),
      listControlPlaneProfiles(),
    ])
      .then(async ([nextPresets, nextAccounts, nextProfiles]) => {
        setPresets(nextPresets);
        setAccounts(nextAccounts);
        setProfiles(nextProfiles);
        const entries = await Promise.all(
          nextAccounts.map(async (account) => [
            account.id,
            await listControlPlaneModels(account.id),
          ] as const)
        );
        setModels(Object.fromEntries(entries));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"));
  }, []);

  const pickPreset = (providerId: string) => {
    const preset = presets.find((item) => item.id === providerId);
    if (!preset) return;
    const defaults = modelControlPresetDefaults(preset);
    setForm((current) => ({
      ...current,
      provider: preset.id,
      name: preset.label,
      backend: defaults.backend,
      baseUrl: defaults.baseUrl,
    }));
  };

  const handleCreate = async () => {
    if (!form.provider || !form.name.trim() || !form.apiKey.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await createProviderAccount({
        provider: form.provider,
        name: form.name.trim(),
        backend: form.backend,
        base_url: form.baseUrl.trim() || undefined,
        api_key: form.apiKey.trim(),
        proxy_url: form.proxyUrl.trim() || undefined,
      });
      setForm(EMPTY_FORM);
      await refreshAccounts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "添加账号失败");
    } finally {
      setBusy(false);
    }
  };

  const handleDiscover = async (accountId: string) => {
    setBusy(true);
    setError(null);
    try {
      const discovered = await discoverProviderModels(accountId);
      setModels((current) => ({ ...current, [accountId]: discovered }));
      await refreshAccounts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "刷新模型失败");
    } finally {
      setBusy(false);
    }
  };

  const handleToggle = async (account: ProviderAccount) => {
    const updated = await updateProviderAccount(account.id, {
      enabled: !account.enabled,
    });
    setAccounts((current) =>
      current.map((item) => (item.id === updated.id ? updated : item))
    );
  };

  const handleDelete = async (accountId: string) => {
    await deleteProviderAccount(accountId);
    setAccounts((current) => current.filter((item) => item.id !== accountId));
    setModels((current) => {
      const next = { ...current };
      delete next[accountId];
      return next;
    });
  };

  const handleLegacyImport = async () => {
    setBusy(true);
    setError(null);
    try {
      await importLegacyProviderConfigs();
      await refreshAccounts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入旧配置失败");
    } finally {
      setBusy(false);
    }
  };

  const handleSaveProfile = async () => {
    const name = profileName.trim();
    if (!name) return;
    const payload = {
      accounts: accounts.map((account) => ({
        id: account.id,
        provider: account.provider,
        name: account.name,
        enabled: account.enabled,
        models: (models[account.id] ?? []).map((model) => model.model_id),
      })),
    };
    try {
      const created = await saveControlPlaneProfile(name, payload);
      setProfiles((current) => [
        created,
        ...current.filter((profile) => profile.id !== created.id),
      ]);
      setProfileName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存快照失败");
    }
  };

  const handleDeleteProfile = async (profileId: string) => {
    await deleteControlPlaneProfile(profileId);
    setProfiles((current) => current.filter((profile) => profile.id !== profileId));
  };

  return (
    <section className="mb-8 border-b border-border pb-8">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold">模型控制面</h2>
          <p className="mt-1 text-xs text-text-secondary">
            管理多个 Provider 账号、模型目录和账号级代理。
          </p>
        </div>
        <button
          type="button"
          onClick={() => void handleLegacyImport()}
          disabled={busy}
          className="rounded-lg border border-border px-3 py-1.5 text-xs hover:bg-sidebar disabled:opacity-50"
        >
          导入旧配置
        </button>
      </div>

      <div className="mb-5 rounded-lg border border-border bg-sidebar px-3 py-2 font-mono text-xs">
        <div className="text-text-secondary">OpenAI-compatible gateway</div>
        <div className="mt-1 select-all text-text">{GATEWAY_URL}/v1</div>
      </div>

      <div className="mb-5 grid gap-2 sm:grid-cols-2">
        {presets.map((preset) => (
          <button
            key={preset.id}
            type="button"
            onClick={() => pickPreset(preset.id)}
            className={`rounded-lg border px-3 py-2 text-left text-sm ${
              form.provider === preset.id
                ? "border-text bg-sidebar"
                : "border-border hover:bg-sidebar"
            }`}
          >
            <span className="font-medium">{preset.label}</span>
            <span className="ml-2 text-xs text-text-secondary">{preset.backend}</span>
          </button>
        ))}
      </div>

      <div className="mb-5 grid gap-2 md:grid-cols-2">
        <input
          value={form.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
          placeholder="账号名称"
          className="rounded-lg border border-border px-3 py-1.5 text-sm"
        />
        <select
          value={form.provider}
          onChange={(event) => pickPreset(event.target.value)}
          className="rounded-lg border border-border px-3 py-1.5 text-sm"
        >
          <option value="">选择 Provider</option>
          {presets.map((preset) => (
            <option key={preset.id} value={preset.id}>
              {preset.label}
            </option>
          ))}
        </select>
        <input
          value={form.baseUrl}
          onChange={(event) => setForm({ ...form, baseUrl: event.target.value })}
          placeholder="Base URL"
          className="rounded-lg border border-border px-3 py-1.5 text-sm"
        />
        <input
          value={form.apiKey}
          onChange={(event) => setForm({ ...form, apiKey: event.target.value })}
          type="password"
          placeholder="API Key"
          className="rounded-lg border border-border px-3 py-1.5 text-sm"
        />
        <input
          value={form.proxyUrl}
          onChange={(event) => setForm({ ...form, proxyUrl: event.target.value })}
          placeholder="账号代理（可选，http:// 或 socks5://）"
          className="rounded-lg border border-border px-3 py-1.5 text-sm md:col-span-2"
        />
        <button
          type="button"
          disabled={busy || !form.provider || !form.name.trim() || !form.apiKey.trim()}
          onClick={() => void handleCreate()}
          className="rounded-lg bg-text px-4 py-2 text-sm font-medium text-white disabled:opacity-50 md:col-span-2"
        >
          {busy ? "处理中…" : "添加账号"}
        </button>
      </div>

      {error && <p className="mb-3 text-xs text-red-500">{error}</p>}

      <div className="space-y-2">
        {accounts.length === 0 ? (
          <p className="text-sm text-text-secondary">还没有控制面账号。</p>
        ) : (
          accounts.map((account) => (
            <div
              key={account.id}
              className="rounded-lg border border-border px-3 py-3 text-sm"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{account.name}</span>
                <span className="text-xs text-text-secondary">
                  {account.provider} · {account.api_key_masked} · {account.model_count} models
                </span>
                <span className={account.enabled ? "text-xs text-green-600" : "text-xs text-text-secondary"}>
                  {account.enabled ? "enabled" : "disabled"}
                </span>
                <span className="flex-1" />
                <button
                  type="button"
                  onClick={() => void handleDiscover(account.id)}
                  disabled={busy}
                  className="rounded-md border border-border px-2 py-1 text-xs hover:bg-sidebar disabled:opacity-50"
                >
                  刷新模型
                </button>
                <button
                  type="button"
                  onClick={() => void handleToggle(account)}
                  className="rounded-md border border-border px-2 py-1 text-xs hover:bg-sidebar"
                >
                  {account.enabled ? "停用" : "启用"}
                </button>
                <button
                  type="button"
                  onClick={() => void handleDelete(account.id)}
                  aria-label={`删除账号：${account.name}`}
                  className="text-text-secondary hover:text-red-500"
                >
                  <TrashIcon width={14} height={14} />
                </button>
              </div>
              {(account.base_url || account.proxy_url) && (
                <div className="mt-1 text-xs text-text-secondary">
                  {account.base_url ?? "default endpoint"}
                  {account.proxy_url ? ` · proxy ${account.proxy_url}` : ""}
                </div>
              )}
              {(models[account.id] ?? []).length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {(models[account.id] ?? []).slice(0, 12).map((model) => (
                    <span
                      key={model.id}
                      className="rounded bg-sidebar px-1.5 py-0.5 text-[11px] text-text-secondary"
                    >
                      {model.model_id}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      <div className="mt-6">
        <h3 className="mb-2 text-sm font-medium">控制面快照</h3>
        <div className="flex gap-2">
          <input
            value={profileName}
            onChange={(event) => setProfileName(event.target.value)}
            placeholder="快照名称"
            className="min-w-0 flex-1 rounded-lg border border-border px-3 py-1.5 text-sm"
          />
          <button
            type="button"
            onClick={() => void handleSaveProfile()}
            disabled={!profileName.trim()}
            className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar disabled:opacity-50"
          >
            保存
          </button>
        </div>
        {profiles.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {profiles.map((profile) => (
              <span
                key={profile.id}
                className="inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-xs"
              >
                {profile.name}
                <button
                  type="button"
                  aria-label={`删除快照：${profile.name}`}
                  onClick={() => void handleDeleteProfile(profile.id)}
                  className="text-text-secondary hover:text-red-500"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
