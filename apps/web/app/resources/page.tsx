"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  addMySkill,
  listCustomAgents,
  listSkills,
  removeMySkill,
  type CustomAgent,
  type SkillsResponse,
} from "@/lib/api";
import {
  createAgentLibraryItem,
  deleteAgentLibraryItem,
  listAgentCatalog,
  listAgentLibrary,
  type AgentLibraryItem,
  type AgentLibraryKind,
  type AgentPlatformAgent,
} from "@/lib/agent-platform-api";
import {
  listMCPServers,
  setMCPServerEnabled,
  type MCPServer,
} from "@/lib/mcp-api";
import {
  EmptyState,
  ManagementPageHeader,
} from "@/components/ui/ManagementPage";
import {
  LibraryIcon,
  SearchIcon,
  TerminalIcon,
  TrashIcon,
} from "@/components/ui/icons";
import { PageSkeleton } from "@/components/ui/PageSkeleton";

type ResourceTab = "skills" | "mcp" | "agents" | "library";

const LIBRARY_KIND_LABELS: Record<AgentLibraryKind, string> = {
  instructions: "Instructions",
  mcp: "MCP",
  skills: "Skill",
  hooks: "Hook",
  env: "Environment",
  subagents: "Subagent",
  commands: "Command",
  plugins: "Plugin",
};

export default function ResourcesPage() {
  const [tab, setTab] = useState<ResourceTab>("skills");
  const [skills, setSkills] = useState<SkillsResponse | null>(null);
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);
  const [customAgents, setCustomAgents] = useState<CustomAgent[]>([]);
  const [externalAgents, setExternalAgents] = useState<AgentPlatformAgent[]>([]);
  const [library, setLibrary] = useState<AgentLibraryItem[]>([]);
  const [query, setQuery] = useState("");
  const [libraryDraft, setLibraryDraft] = useState({
    kind: "instructions" as AgentLibraryKind,
    name: "",
    content: "",
  });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      listSkills(),
      listMCPServers(),
      listCustomAgents(),
      listAgentCatalog(),
      listAgentLibrary(),
    ])
      .then(([nextSkills, nextMcp, nextCustom, nextExternal, nextLibrary]) => {
        setSkills(nextSkills);
        setMcpServers(nextMcp);
        setCustomAgents(nextCustom);
        setExternalAgents(nextExternal);
        setLibrary(nextLibrary);
      })
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : "无法加载资源库")
      );
  }, []);

  const counts = {
    skills: skills?.skills.length ?? 0,
    mcp: mcpServers.length,
    agents: customAgents.length + externalAgents.filter((agent) => agent.installed).length,
    library: library.length,
  };

  const needle = query.trim().toLowerCase();
  const filteredSkills = useMemo(
    () =>
      (skills?.skills ?? []).filter(
        (skill) =>
          !needle ||
          `${skill.name} ${skill.description}`.toLowerCase().includes(needle)
      ),
    [needle, skills]
  );
  const filteredMcp = useMemo(
    () =>
      mcpServers.filter(
        (server) =>
          !needle ||
          `${server.name} ${server.transport}`.toLowerCase().includes(needle)
      ),
    [mcpServers, needle]
  );
  const filteredAgents = useMemo(
    () =>
      [
        ...customAgents.map((agent) => ({
          id: agent.id,
          name: agent.name,
          description: agent.description,
          source: "OpenTalos Agent",
          href: "/agents",
        })),
        ...externalAgents
          .filter((agent) => agent.installed)
          .map((agent) => ({
            id: agent.id,
            name: agent.name,
            description: agent.compatibility_path,
            source: agent.version ?? "外部 Agent",
            href: "/agents",
          })),
      ].filter(
        (agent) =>
          !needle ||
          `${agent.name} ${agent.description}`.toLowerCase().includes(needle)
      ),
    [customAgents, externalAgents, needle]
  );
  const filteredLibrary = useMemo(
    () =>
      library.filter(
        (item) =>
          !needle ||
          `${item.name} ${item.kind} ${item.content}`.toLowerCase().includes(needle)
      ),
    [library, needle]
  );

  if (skills === null) return <PageSkeleton />;

  const toggleSkill = async (name: string, added: boolean) => {
    try {
      if (added) await removeMySkill(name);
      else await addMySkill(name);
      setSkills({
        ...skills,
        skills: skills.skills.map((skill) =>
          skill.name === name ? { ...skill, added: !added } : skill
        ),
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "更新技能失败");
    }
  };

  const toggleMcp = async (server: MCPServer) => {
    try {
      const updated = await setMCPServerEnabled(server.id, !server.enabled);
      setMcpServers((current) =>
        current.map((item) => (item.id === server.id ? updated : item))
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "更新 MCP 失败");
    }
  };

  const createLibrary = async () => {
    if (!libraryDraft.name.trim() || !libraryDraft.content.trim()) return;
    try {
      const item = await createAgentLibraryItem(libraryDraft);
      setLibrary((current) => [item, ...current]);
      setLibraryDraft({ kind: "instructions", name: "", content: "" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建 Library 项目失败");
    }
  };

  const deleteLibrary = async (itemId: string) => {
    try {
      await deleteAgentLibraryItem(itemId);
      setLibrary((current) => current.filter((item) => item.id !== itemId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除 Library 项目失败");
    }
  };

  return (
    <section className="p-6">
      <ManagementPageHeader
        title="资源库"
        description="集中查看 OpenTalos 中的技能、MCP、Agent 和托管资源。"
        actions={
          <Link
            href="/agents"
            className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar"
          >
            管理 Agent
          </Link>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap rounded-lg border border-border p-0.5">
          {(
            [
              ["skills", "技能", counts.skills],
              ["mcp", "MCP", counts.mcp],
              ["agents", "Agent", counts.agents],
              ["library", "Library", counts.library],
            ] as const
          ).map(([id, label, count]) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={`rounded-md px-3 py-1.5 text-sm ${
                tab === id ? "bg-text text-white" : "text-text-secondary"
              }`}
            >
              {label} {count}
            </button>
          ))}
        </div>
        <label className="flex min-w-56 flex-1 items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2">
          <SearchIcon className="shrink-0 text-text-secondary" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索资源"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none"
          />
        </label>
      </div>

      {error && <p className="mb-3 text-sm text-red-500">{error}</p>}

      {tab === "skills" && (
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {filteredSkills.map((skill) => (
            <div key={skill.name} className="rounded-lg border border-border bg-surface p-4">
              <div className="flex items-start gap-2">
                <LibraryIcon className="mt-0.5 shrink-0 text-text-secondary" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{skill.name}</p>
                  <p className="mt-1 line-clamp-2 text-xs text-text-secondary">
                    {skill.description}
                  </p>
                </div>
                <button
                  type="button"
                  aria-label={`${skill.added ? "移除" : "添加"}技能 ${skill.name}`}
                  onClick={() => void toggleSkill(skill.name, skill.added)}
                  className={`rounded-md border px-2 py-1 text-xs ${
                    skill.added
                      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600"
                      : "border-border text-text-secondary hover:bg-sidebar"
                  }`}
                >
                  {skill.added ? "已添加" : "添加"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === "mcp" && (
        <div className="overflow-hidden rounded-lg border border-border bg-surface">
          {filteredMcp.map((server, index) => (
            <div
              key={server.id}
              className={`flex flex-wrap items-center gap-3 px-4 py-3 ${
                index ? "border-t border-border" : ""
              }`}
            >
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{server.name}</p>
                <p className="mt-0.5 truncate text-xs text-text-secondary">
                  {server.transport} · {server.cached_tools.length} tools
                  {server.last_error ? ` · ${server.last_error}` : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={() => void toggleMcp(server)}
                className={`rounded-lg border px-2 py-1 text-xs ${
                  server.enabled
                    ? "border-emerald-500/30 text-emerald-600"
                    : "border-border text-text-secondary"
                }`}
              >
                {server.enabled ? "已启用" : "已停用"}
              </button>
            </div>
          ))}
          {filteredMcp.length === 0 && (
            <EmptyState
              title="没有 MCP 资源"
              action={
                <Link href="/mcp" className="text-sm text-accent hover:underline">
                  添加 MCP Server
                </Link>
              }
            />
          )}
        </div>
      )}

      {tab === "agents" && (
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {filteredAgents.map((agent) => (
            <Link
              key={`${agent.source}-${agent.id}`}
              href={agent.href}
              className="rounded-lg border border-border bg-surface p-4 hover:border-text-secondary"
            >
              <div className="flex items-center gap-2">
                <TerminalIcon className="shrink-0 text-text-secondary" />
                <span className="min-w-0 flex-1 truncate text-sm font-medium">
                  {agent.name}
                </span>
                <span className="text-[11px] text-text-secondary">{agent.source}</span>
              </div>
              <p className="mt-2 line-clamp-2 text-xs text-text-secondary">
                {agent.description}
              </p>
            </Link>
          ))}
        </div>
      )}

      {tab === "library" && (
        <div className="space-y-4">
          <div className="grid gap-2 rounded-lg border border-border bg-surface p-3 sm:grid-cols-[140px_1fr]">
            <select
              value={libraryDraft.kind}
              onChange={(event) =>
                setLibraryDraft({
                  ...libraryDraft,
                  kind: event.target.value as AgentLibraryKind,
                })
              }
              className="rounded-lg border border-border px-3 py-1.5 text-sm"
            >
              {Object.entries(LIBRARY_KIND_LABELS).map(([kind, label]) => (
                <option key={kind} value={kind}>
                  {label}
                </option>
              ))}
            </select>
            <input
              value={libraryDraft.name}
              onChange={(event) =>
                setLibraryDraft({ ...libraryDraft, name: event.target.value })
              }
              placeholder="资源名称"
              className="rounded-lg border border-border px-3 py-1.5 text-sm"
            />
            <textarea
              value={libraryDraft.content}
              onChange={(event) =>
                setLibraryDraft({ ...libraryDraft, content: event.target.value })
              }
              placeholder="资源内容或 MCP JSON"
              className="min-h-24 rounded-lg border border-border px-3 py-2 font-mono text-xs sm:col-span-2"
            />
            <button
              type="button"
              onClick={() => void createLibrary()}
              disabled={!libraryDraft.name.trim() || !libraryDraft.content.trim()}
              className="rounded-lg bg-text px-3 py-1.5 text-sm text-white disabled:opacity-40 sm:col-span-2"
            >
              保存到资源库
            </button>
          </div>
          <div className="overflow-hidden rounded-lg border border-border bg-surface">
            {filteredLibrary.map((item, index) => (
              <div
                key={item.id}
                className={`flex items-center gap-3 px-4 py-3 ${
                  index ? "border-t border-border" : ""
                }`}
              >
                <span className="w-24 shrink-0 text-xs text-text-secondary">
                  {LIBRARY_KIND_LABELS[item.kind]}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{item.name}</p>
                  <p className="mt-0.5 truncate text-xs text-text-secondary">
                    {item.bindings.length} 个 Agent 已应用 · {item.content}
                  </p>
                </div>
                <button
                  type="button"
                  aria-label={`删除资源 ${item.name}`}
                  onClick={() => void deleteLibrary(item.id)}
                  className="rounded-lg p-1.5 text-text-secondary hover:bg-sidebar hover:text-red-500"
                >
                  <TrashIcon width={14} height={14} />
                </button>
              </div>
            ))}
            {filteredLibrary.length === 0 && (
              <EmptyState title="Library 为空" description="创建可跨 Agent 复用的托管资源。" />
            )}
          </div>
        </div>
      )}

      {(tab === "skills" && filteredSkills.length === 0) ||
      (tab === "agents" && filteredAgents.length === 0) ? (
        <EmptyState title="没有匹配的资源" />
      ) : null}
    </section>
  );
}
