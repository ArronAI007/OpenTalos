"use client";

import { useEffect, useState } from "react";
import {
  createProviderConfig,
  listProviderConfigs,
  activateProviderConfig,
  deleteProviderConfig,
  type ProviderConfig,
} from "@/lib/providers-api";
import { TrashIcon } from "@/components/ui/icons";
import { PageSkeleton } from "@/components/ui/PageSkeleton";

interface ChatProviderPreset {
  key: string;
  label: string;
  backend: "anthropic" | "openai-compatible";
  baseUrl?: string;
}

const CHAT_PROVIDER_PRESETS: ChatProviderPreset[] = [
  { key: "anthropic", label: "Anthropic", backend: "anthropic" },
  { key: "openai", label: "OpenAI", backend: "openai-compatible", baseUrl: "https://api.openai.com/v1" },
  { key: "deepseek", label: "DeepSeek", backend: "openai-compatible", baseUrl: "https://api.deepseek.com" },
  { key: "moonshot", label: "Moonshot (Kimi)", backend: "openai-compatible", baseUrl: "https://api.moonshot.cn/v1" },
];

export function applyChatPreset(preset: ChatProviderPreset): { backend: "anthropic" | "openai-compatible"; baseUrl: string } {
  return { backend: preset.backend, baseUrl: preset.baseUrl ?? "" };
}

function ConfirmDeleteProviderDialog({
  open,
  onCancel,
  onConfirm,
}: {
  open: boolean;
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
      <div role="alertdialog" aria-modal="true" className="relative z-10 w-full max-w-sm rounded-2xl bg-surface p-5 shadow-2xl">
        <h2 className="text-sm font-semibold">删除这条 Provider 配置？</h2>
        <p className="mt-1.5 text-sm text-text-secondary">此操作不可撤销。</p>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" autoFocus onClick={onCancel} className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar">
            取消
          </button>
          <button type="button" onClick={onConfirm} className="rounded-lg bg-red-500 px-3 py-1.5 text-sm text-white hover:bg-red-600">
            删除
          </button>
        </div>
      </div>
    </div>
  );
}

function ProviderList({
  title,
  description,
  configs,
  onActivate,
  onDelete,
}: {
  title: string;
  description: string;
  configs: ProviderConfig[];
  onActivate: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <h2 className="mb-1 text-sm font-medium">{title}</h2>
      <p className="mb-3 text-xs text-text-secondary">{description}</p>
      {configs.length === 0 ? (
        <p className="text-sm text-text-secondary">还没有配置。</p>
      ) : (
        <ul className="space-y-2">
          {configs.map((config) => (
            <li key={config.id} className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm">
              <div className="flex-1">
                <span className="font-medium">{config.name}</span>
                <span className="ml-2 text-text-secondary">
                  {config.backend ?? "embedding"} · {config.model_name} · {config.api_key_masked}
                  {config.active && " · 已激活"}
                </span>
              </div>
              {!config.active && (
                <button
                  type="button"
                  onClick={() => onActivate(config.id)}
                  className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-sidebar"
                >
                  激活
                </button>
              )}
              <button
                type="button"
                aria-label={`删除 Provider 配置：${config.name}`}
                onClick={() => onDelete(config.id)}
                className="text-text-secondary hover:text-red-500"
              >
                <TrashIcon width={14} height={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function ProvidersPage() {
  const [configs, setConfigs] = useState<ProviderConfig[] | null>(null);
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState<"chat" | "embedding">("chat");
  const [backend, setBackend] = useState<"anthropic" | "openai-compatible" | "mock">("anthropic");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [modelName, setModelName] = useState("");
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listProviderConfigs()
      .then(setConfigs)
      .catch(() => setConfigs([]));
  }, []);

  const resetForm = () => {
    setName("");
    setBaseUrl("");
    setApiKey("");
    setModelName("");
  };

  const handleAdd = async () => {
    const trimmedName = name.trim();
    const trimmedKey = apiKey.trim();
    const trimmedModel = modelName.trim();
    if (!trimmedName || !trimmedKey || !trimmedModel) return;
    setError(null);
    setBusy(true);
    try {
      const config = await createProviderConfig({
        name: trimmedName,
        purpose,
        backend: purpose === "chat" ? backend : undefined,
        base_url: baseUrl.trim() || undefined,
        api_key: trimmedKey,
        model_name: trimmedModel,
      });
      setConfigs((prev) => [config, ...(prev ?? [])]);
      resetForm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "添加失败");
    } finally {
      setBusy(false);
    }
  };

  const handlePickPreset = (preset: ChatProviderPreset) => {
    setError(null);
    setName(preset.label);
    setPurpose("chat");
    const applied = applyChatPreset(preset);
    setBackend(applied.backend);
    setBaseUrl(applied.baseUrl);
  };

  const handleActivate = async (id: string) => {
    const updated = await activateProviderConfig(id);
    setConfigs((prev) => prev?.map((c) => (c.id === id ? updated : c.purpose === updated.purpose ? { ...c, active: false } : c)) ?? null);
  };

  const handleDelete = async (id: string) => {
    await deleteProviderConfig(id);
    setConfigs((prev) => prev?.filter((c) => c.id !== id) ?? null);
  };

  if (configs === null) return <PageSkeleton />;

  const chatConfigs = configs.filter((c) => c.purpose === "chat");
  const embeddingConfigs = configs.filter((c) => c.purpose === "embedding");

  return (
    <section className="p-6">
      <h1 className="mb-4 text-xl font-semibold">Provider</h1>
      <p className="mb-4 text-sm text-text-secondary">
        统一管理聊天模型和 embedding 模型的 provider 配置。改动对下一个新建的任务/embedding 调用立刻生效，不需要重启。
      </p>

      <div className="mb-6 rounded-xl border border-border bg-surface p-4">
        <h2 className="mb-3 text-sm font-medium">常用聊天 Provider</h2>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {CHAT_PROVIDER_PRESETS.map((preset) => (
            <button
              key={preset.key}
              type="button"
              onClick={() => handlePickPreset(preset)}
              className="rounded-lg border border-border p-3 text-left text-sm hover:bg-sidebar"
            >
              <div className="font-medium">{preset.label}</div>
              <div className="mt-0.5 text-xs text-text-secondary">{preset.backend}</div>
            </button>
          ))}
        </div>
      </div>

      <div className="mb-6 rounded-xl border border-border bg-surface p-4">
        <h2 className="mb-3 text-sm font-medium">添加 Provider 配置</h2>
        <div className="space-y-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="名称，例如：我的 Anthropic"
            className="w-full rounded-lg border border-border px-3 py-1.5 text-sm"
          />
          <div className="flex gap-3 text-sm">
            <label className="flex items-center gap-1.5">
              <input type="radio" checked={purpose === "chat"} onChange={() => setPurpose("chat")} />
              聊天
            </label>
            <label className="flex items-center gap-1.5">
              <input type="radio" checked={purpose === "embedding"} onChange={() => setPurpose("embedding")} />
              Embedding
            </label>
          </div>
          {purpose === "chat" && (
            <select
              value={backend}
              onChange={(e) => setBackend(e.target.value as "anthropic" | "openai-compatible" | "mock")}
              className="w-full rounded-lg border border-border px-3 py-1.5 text-sm"
            >
              <option value="anthropic">anthropic</option>
              <option value="openai-compatible">openai-compatible</option>
              <option value="mock">mock</option>
            </select>
          )}
          <input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="服务地址（可选）"
            className="w-full rounded-lg border border-border px-3 py-1.5 text-sm"
          />
          <input
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            type="password"
            placeholder="API Key"
            className="w-full rounded-lg border border-border px-3 py-1.5 text-sm"
          />
          <input
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
            placeholder="模型名"
            className="w-full rounded-lg border border-border px-3 py-1.5 text-sm"
          />
          <button
            type="button"
            disabled={busy}
            onClick={() => void handleAdd()}
            className="rounded-lg bg-text px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy ? "添加中…" : "添加"}
          </button>
        </div>
        {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
      </div>

      <div className="space-y-4">
        <ProviderList
          title="聊天"
          description="用于对话任务的模型 provider。"
          configs={chatConfigs}
          onActivate={(id) => void handleActivate(id)}
          onDelete={(id) => setPendingDeleteId(id)}
        />
        <ProviderList
          title="Embedding"
          description="用于长期记忆检索的 embedding provider。"
          configs={embeddingConfigs}
          onActivate={(id) => void handleActivate(id)}
          onDelete={(id) => setPendingDeleteId(id)}
        />
      </div>

      <ConfirmDeleteProviderDialog
        open={pendingDeleteId !== null}
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
