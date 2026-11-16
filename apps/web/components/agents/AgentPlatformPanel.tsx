"use client";

import { useEffect, useMemo, useState } from "react";
import {
  applyAgentConfiguration,
  applyAgentLibraryItem,
  applyAgentProfile,
  bindAgentModel,
  createAgentLibraryItem,
  deleteAgentLibraryItem,
  deleteAgentProfile,
  discoverAgents,
  executeAgentUpdate,
  getAgentUpdatePlan,
  listAgentCatalog,
  listAgentLibrary,
  listAgentModels,
  listAgentProfiles,
  previewAgentConfiguration,
  removeAgentLibraryItem,
  restoreAgentConfiguration,
  saveAgentProfile,
  type AgentConfigPreview,
  type AgentLibraryItem,
  type AgentLibraryKind,
  type AgentModelOption,
  type AgentPlatformAgent,
  type AgentPlatformProfile,
  type AgentUpdatePlan,
} from "@/lib/agent-platform-api";
import {
  ArchiveRestoreIcon,
  CheckIcon,
  ExternalLinkIcon,
  SearchIcon,
  TrashIcon,
} from "@/components/ui/icons";

const EMPTY_LIBRARY = {
  kind: "instructions" as AgentLibraryKind,
  name: "",
  content: "",
};

export function AgentPlatformPanel() {
  const [agents, setAgents] = useState<AgentPlatformAgent[]>([]);
  const [profiles, setProfiles] = useState<AgentPlatformProfile[]>([]);
  const [library, setLibrary] = useState<AgentLibraryItem[]>([]);
  const [models, setModels] = useState<AgentModelOption[]>([]);
  const [modelAgentId, setModelAgentId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [modelQuery, setModelQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [profileName, setProfileName] = useState("");
  const [libraryDraft, setLibraryDraft] = useState(EMPTY_LIBRARY);
  const [preview, setPreview] = useState<AgentConfigPreview | null>(null);
  const [updatePlan, setUpdatePlan] = useState<AgentUpdatePlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selected = agents.find((agent) => agent.id === selectedId) ?? null;
  const visibleAgents = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return agents.filter((agent) => {
      if (!showAll && !agent.installed) return false;
      if (!needle) return true;
      return `${agent.name} ${agent.id} ${agent.version ?? ""}`
        .toLowerCase()
        .includes(needle);
    });
  }, [agents, query, showAll]);
  const visibleModels = useMemo(() => {
    if (modelAgentId !== selectedId) return [];
    const needle = modelQuery.trim().toLowerCase();
    return models.filter(
      (model) => !needle || `${model.label} ${model.value}`.toLowerCase().includes(needle)
    );
  }, [modelAgentId, modelQuery, models, selectedId]);

  const loadPlatform = async (runDiscovery = false) => {
    setBusy(true);
    setError(null);
    try {
      if (runDiscovery) await discoverAgents();
      const [nextAgents, nextProfiles, nextLibrary] = await Promise.all([
        listAgentCatalog(),
        listAgentProfiles(),
        listAgentLibrary(),
      ]);
      setAgents(nextAgents);
      setProfiles(nextProfiles);
      setLibrary(nextLibrary);
      setSelectedId((current) => current ?? nextAgents.find((agent) => agent.installed)?.id ?? null);
    } catch (err) {
      setError(messageOf(err, "无法加载 Agent 平台"));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) void loadPlatform(true);
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    listAgentModels(selectedId)
      .then((items) => {
        if (!cancelled) {
          setModels(items);
          setModelAgentId(selectedId);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setModels([]);
          setModelAgentId(selectedId);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const selectAgent = (agentId: string) => {
    setSelectedId(agentId);
    setPreview(null);
    setUpdatePlan(null);
    setModelQuery("");
  };

  const bind = async (model: string, shortlist?: string[]) => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const binding = await bindAgentModel(selected.id, {
        model,
        shortlist: shortlist ?? selected.binding?.shortlist ?? [model],
        routing_preference: selected.binding?.routing_preference ?? model,
      });
      setAgents((current) =>
        current.map((agent) =>
          agent.id === selected.id ? { ...agent, binding } : agent
        )
      );
      setPreview(null);
      setNotice("模型绑定已保存");
    } catch (err) {
      setError(messageOf(err, "保存模型绑定失败"));
    } finally {
      setBusy(false);
    }
  };

  const toggleShortlist = async (model: string) => {
    if (!selected) return;
    const shortlist = selected.binding?.shortlist ?? [];
    const next = shortlist.includes(model)
      ? shortlist.filter((item) => item !== model)
      : [...shortlist, model];
    await bind(selected.binding?.model || model, next);
  };

  const previewConfiguration = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      setPreview(await previewAgentConfiguration(selected.id));
    } catch (err) {
      setError(messageOf(err, "无法生成配置预览"));
    } finally {
      setBusy(false);
    }
  };

  const applyConfiguration = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await applyAgentConfiguration(selected.id);
      setNotice(`配置已写入 ${result.path}`);
      setPreview(null);
    } catch (err) {
      setError(messageOf(err, "应用配置失败"));
    } finally {
      setBusy(false);
    }
  };

  const restoreConfiguration = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await restoreAgentConfiguration(selected.id);
      setNotice("已恢复到首次托管前的配置");
      setPreview(null);
    } catch (err) {
      setError(messageOf(err, "恢复配置失败"));
    } finally {
      setBusy(false);
    }
  };

  const checkUpdate = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      setUpdatePlan(await getAgentUpdatePlan(selected.id));
    } catch (err) {
      setError(messageOf(err, "无法读取更新方式"));
    } finally {
      setBusy(false);
    }
  };

  const runUpdate = async () => {
    if (!selected || !updatePlan?.automatic) return;
    if (!window.confirm(`执行：${updatePlan.display_command}`)) return;
    setBusy(true);
    setError(null);
    try {
      await executeAgentUpdate(selected.id);
      setNotice("Agent 更新完成");
      setUpdatePlan(null);
      await loadPlatform(true);
    } catch (err) {
      setError(messageOf(err, "Agent 更新失败"));
    } finally {
      setBusy(false);
    }
  };

  const saveProfile = async () => {
    if (!profileName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const profile = await saveAgentProfile(profileName.trim());
      setProfiles((current) => [
        profile,
        ...current.filter((item) => item.id !== profile.id),
      ]);
      setProfileName("");
      setNotice("Profile 已保存");
    } catch (err) {
      setError(messageOf(err, "保存 Profile 失败"));
    } finally {
      setBusy(false);
    }
  };

  const applyProfile = async (profileId: string) => {
    setBusy(true);
    setError(null);
    try {
      await applyAgentProfile(profileId);
      await loadPlatform(false);
      setNotice("Profile 已应用");
    } catch (err) {
      setError(messageOf(err, "应用 Profile 失败"));
    } finally {
      setBusy(false);
    }
  };

  const removeProfile = async (profileId: string) => {
    await deleteAgentProfile(profileId);
    setProfiles((current) => current.filter((item) => item.id !== profileId));
  };

  const createLibraryItem = async () => {
    if (!libraryDraft.name.trim() || !libraryDraft.content.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const item = await createAgentLibraryItem(libraryDraft);
      setLibrary((current) => [item, ...current]);
      setLibraryDraft(EMPTY_LIBRARY);
      setNotice("Library 项目已保存");
    } catch (err) {
      setError(messageOf(err, "创建 Library 项目失败"));
    } finally {
      setBusy(false);
    }
  };

  const toggleLibraryItem = async (item: AgentLibraryItem) => {
    if (!selected) return;
    const applied = item.bindings.some((binding) => binding.agent_id === selected.id);
    setBusy(true);
    setError(null);
    try {
      if (applied) {
        await removeAgentLibraryItem(selected.id, item.id);
      } else {
        await applyAgentLibraryItem(selected.id, item.id);
      }
      setLibrary(await listAgentLibrary());
    } catch (err) {
      setError(messageOf(err, applied ? "移除 Library 项目失败" : "应用 Library 项目失败"));
    } finally {
      setBusy(false);
    }
  };

  const removeLibraryItem = async (itemId: string) => {
    await deleteAgentLibraryItem(itemId);
    setLibrary((current) => current.filter((item) => item.id !== itemId));
  };

  return (
    <section className="mt-10 border-t border-border pt-8">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">外部 Agent 平台</h2>
          <p className="mt-1 text-sm text-text-secondary">
            统一发现、绑定模型、写入配置，并管理跨 Agent 资源。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={showAll}
              onChange={(event) => setShowAll(event.target.checked)}
            />
            显示完整目录
          </label>
          <button
            type="button"
            onClick={() => void loadPlatform(true)}
            disabled={busy}
            className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar disabled:opacity-40"
          >
            重新发现
          </button>
        </div>
      </div>

      {error && <p className="mb-3 text-sm text-red-500">{error}</p>}
      {notice && <p className="mb-3 text-sm text-emerald-600">{notice}</p>}

      <div className="grid gap-5 lg:grid-cols-[minmax(220px,0.75fr)_minmax(0,2fr)]">
        <div>
          <label className="flex items-center gap-2 rounded-lg border border-border px-3 py-2">
            <SearchIcon className="shrink-0 text-text-secondary" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索 Agent"
              className="min-w-0 flex-1 bg-transparent text-sm outline-none"
            />
          </label>
          <div className="mt-2 max-h-[520px] space-y-1 overflow-y-auto pr-1">
            {visibleAgents.map((agent) => (
              <button
                key={agent.id}
                type="button"
                onClick={() => selectAgent(agent.id)}
                className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm ${
                  selectedId === agent.id ? "bg-sidebar" : "hover:bg-sidebar"
                }`}
              >
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${
                    agent.installed ? "bg-emerald-500" : "bg-border"
                  }`}
                />
                <span className="min-w-0 flex-1 truncate">{agent.name}</span>
                <span className="shrink-0 text-xs text-text-secondary">
                  {agent.version ?? (agent.installed ? "已安装" : "未安装")}
                </span>
              </button>
            ))}
            {visibleAgents.length === 0 && (
              <p className="px-3 py-6 text-sm text-text-secondary">没有匹配的 Agent。</p>
            )}
          </div>
        </div>

        <div className="min-w-0 border-l border-border pl-5">
          {!selected ? (
            <p className="py-12 text-sm text-text-secondary">选择一个 Agent 查看平台配置。</p>
          ) : (
            <div className="space-y-6">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-lg font-semibold">{selected.name}</h3>
                    <span className="rounded-full border border-border px-2 py-0.5 text-xs text-text-secondary">
                      {selected.compatibility === "native" ? "原生适配" : "兼容路径"}
                    </span>
                    {selected.installed && (
                      <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-600">
                        {selected.version ?? "已安装"}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 break-words text-sm text-text-secondary">
                    {selected.compatibility_path}
                  </p>
                  <dl className="mt-3 grid gap-2 text-xs text-text-secondary sm:grid-cols-2">
                    <div>
                      <dt className="font-medium text-text">配置位置</dt>
                      <dd className="break-all font-mono">{selected.config_path ?? "不可用"}</dd>
                    </div>
                    <div>
                      <dt className="font-medium text-text">安装来源</dt>
                      <dd className="break-all font-mono">
                        {selected.install_path ?? selected.install_hint}
                      </dd>
                    </div>
                  </dl>
                </div>
                <button
                  type="button"
                  onClick={() => void checkUpdate()}
                  disabled={busy}
                  className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar disabled:opacity-40"
                >
                  检查更新
                </button>
              </div>

              {updatePlan && (
                <div className="rounded-lg border border-border p-3 text-sm">
                  <p className="font-medium">
                    {updatePlan.automatic ? "可自动更新" : "需要手动更新"}
                  </p>
                  <p className="mt-1 break-all font-mono text-xs text-text-secondary">
                    {updatePlan.display_command ?? updatePlan.install_hint}
                  </p>
                  {updatePlan.automatic && (
                    <button
                      type="button"
                      onClick={() => void runUpdate()}
                      disabled={busy}
                      className="mt-2 rounded-lg bg-text px-3 py-1.5 text-xs text-white disabled:opacity-40"
                    >
                      执行更新
                    </button>
                  )}
                </div>
              )}

              <div>
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <h4 className="text-sm font-medium">模型与短名单</h4>
                  <label className="flex items-center gap-2 rounded-lg border border-border px-2.5 py-1.5">
                    <SearchIcon width={14} height={14} className="text-text-secondary" />
                    <input
                      value={modelQuery}
                      onChange={(event) => setModelQuery(event.target.value)}
                      placeholder="筛选模型"
                      className="w-36 bg-transparent text-xs outline-none"
                    />
                  </label>
                </div>
                <div className="grid max-h-64 gap-1 overflow-y-auto border-y border-border py-2">
                  {visibleModels.map((model) => {
                    const primary = selected.binding?.model === model.value;
                    const shortlisted = selected.binding?.shortlist.includes(model.value) ?? false;
                    return (
                      <div
                        key={model.value}
                        className={`flex items-center gap-2 rounded-lg px-2 py-1.5 ${
                          primary ? "bg-sidebar" : ""
                        }`}
                      >
                        <button
                          type="button"
                          disabled={busy || !model.eligible}
                          title={model.reason ?? model.value}
                          onClick={() => void bind(model.value)}
                          className="min-w-0 flex-1 text-left disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          <span className="block truncate text-sm">{model.label}</span>
                          <span className="block truncate font-mono text-xs text-text-secondary">
                            {model.value}
                          </span>
                        </button>
                        <button
                          type="button"
                          disabled={busy || !model.eligible}
                          title={shortlisted ? "从短名单移除" : "加入短名单"}
                          aria-label={shortlisted ? "从短名单移除" : "加入短名单"}
                          onClick={() => void toggleShortlist(model.value)}
                          className={`rounded-md p-1.5 disabled:opacity-30 ${
                            shortlisted ? "text-emerald-600" : "text-text-secondary hover:bg-sidebar"
                          }`}
                        >
                          <CheckIcon width={14} height={14} />
                        </button>
                      </div>
                    );
                  })}
                  {visibleModels.length === 0 && (
                    <p className="py-4 text-sm text-text-secondary">
                      当前没有可用模型，请先在 Provider 页面发现模型。
                    </p>
                  )}
                </div>
              </div>

              <div>
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <h4 className="text-sm font-medium">配置事务</h4>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => void previewConfiguration()}
                      disabled={busy || !selected.binding?.model || !selected.configuration_ready}
                      className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar disabled:opacity-40"
                    >
                      预览
                    </button>
                    <button
                      type="button"
                      onClick={() => void applyConfiguration()}
                      disabled={busy || !selected.binding?.model || !selected.configuration_ready}
                      className="rounded-lg bg-text px-3 py-1.5 text-sm text-white disabled:opacity-40"
                    >
                      应用配置
                    </button>
                    <button
                      type="button"
                      onClick={() => void restoreConfiguration()}
                      disabled={busy || !selected.configuration_ready}
                      title="恢复首次托管前配置"
                      aria-label="恢复首次托管前配置"
                      className="rounded-lg border border-border p-2 hover:bg-sidebar disabled:opacity-40"
                    >
                      <ArchiveRestoreIcon width={15} height={15} />
                    </button>
                  </div>
                </div>
                {preview && (
                  <div>
                    <p className="mb-1 break-all font-mono text-xs text-text-secondary">
                      {preview.path}
                    </p>
                    <pre className="max-h-64 overflow-auto rounded-lg border border-border bg-sidebar p-3 text-xs">
                      {preview.diff || "配置无变化"}
                    </pre>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="mt-8 grid gap-8 border-t border-border pt-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-3 text-sm font-medium">Agent Profile</h3>
          <div className="flex gap-2">
            <input
              value={profileName}
              onChange={(event) => setProfileName(event.target.value)}
              placeholder="Profile 名称"
              className="min-w-0 flex-1 rounded-lg border border-border px-3 py-1.5 text-sm"
            />
            <button
              type="button"
              onClick={() => void saveProfile()}
              disabled={busy || !profileName.trim()}
              className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar disabled:opacity-40"
            >
              保存
            </button>
          </div>
          <div className="mt-2 space-y-1">
            {profiles.map((profile) => (
              <div key={profile.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5">
                <button
                  type="button"
                  onClick={() => void applyProfile(profile.id)}
                  className="min-w-0 flex-1 truncate text-left text-sm hover:underline"
                >
                  {profile.name}
                </button>
                <button
                  type="button"
                  onClick={() => void removeProfile(profile.id)}
                  aria-label={`删除 Profile ${profile.name}`}
                  className="p-1 text-text-secondary hover:text-red-500"
                >
                  <TrashIcon width={14} height={14} />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div>
          <h3 className="mb-3 text-sm font-medium">跨 Agent Library</h3>
          <div className="grid gap-2 sm:grid-cols-[130px_1fr]">
            <select
              value={libraryDraft.kind}
              onChange={(event) =>
                setLibraryDraft((current) => ({
                  ...current,
                  kind: event.target.value as AgentLibraryKind,
                }))
              }
              className="rounded-lg border border-border px-3 py-1.5 text-sm"
            >
              <option value="instructions">Instructions</option>
              <option value="mcp">MCP Server</option>
              <option value="skills">Skill</option>
              <option value="hooks">Hook</option>
              <option value="env">Environment</option>
              <option value="subagents">Subagent</option>
              <option value="commands">Slash command</option>
              <option value="plugins">Claude plugin</option>
            </select>
            <input
              value={libraryDraft.name}
              onChange={(event) =>
                setLibraryDraft((current) => ({ ...current, name: event.target.value }))
              }
              placeholder="资源名称"
              className="min-w-0 rounded-lg border border-border px-3 py-1.5 text-sm"
            />
            <textarea
              value={libraryDraft.content}
              onChange={(event) =>
                setLibraryDraft((current) => ({ ...current, content: event.target.value }))
              }
              placeholder={libraryDraft.kind === "mcp" ? "MCP JSON 配置" : "内容"}
              className="min-h-20 rounded-lg border border-border px-3 py-1.5 font-mono text-xs sm:col-span-2"
            />
            <button
              type="button"
              onClick={() => void createLibraryItem()}
              disabled={
                busy || !libraryDraft.name.trim() || !libraryDraft.content.trim()
              }
              className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar disabled:opacity-40 sm:col-span-2"
            >
              保存 Library 项目
            </button>
          </div>
          <div className="mt-2 space-y-1">
            {library.map((item) => {
              const applied = item.bindings.some(
                (binding) => binding.agent_id === selected?.id
              );
              return (
                <div key={item.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5">
                  <span className="w-20 shrink-0 text-xs text-text-secondary">{item.kind}</span>
                  <span className="min-w-0 flex-1 truncate text-sm">{item.name}</span>
                  <button
                    type="button"
                    onClick={() => void toggleLibraryItem(item)}
                    disabled={busy || !selected?.configuration_ready}
                    className={`rounded-md px-2 py-1 text-xs disabled:opacity-30 ${
                      applied
                        ? "bg-emerald-500/10 text-emerald-600"
                        : "border border-border hover:bg-sidebar"
                    }`}
                  >
                    {applied ? "已应用" : "应用"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void removeLibraryItem(item.id)}
                    aria-label={`删除资源 ${item.name}`}
                    className="p-1 text-text-secondary hover:text-red-500"
                  >
                    <TrashIcon width={14} height={14} />
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <a
        href={agents[0]?.catalog_source ?? "https://github.com/yetone/magpie"}
        target="_blank"
        rel="noreferrer"
        className="mt-6 inline-flex items-center gap-1 text-xs text-text-secondary hover:underline"
      >
        固定 Agent 目录来源
        <ExternalLinkIcon width={12} height={12} />
      </a>
    </section>
  );
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}
