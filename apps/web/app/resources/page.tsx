"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type ComponentType } from "react";

import {
  addMySkill,
  listCustomAgents,
  listSkills,
  removeMySkill,
  type CustomAgent,
  type SkillsResponse,
} from "@/lib/api";
import {
  applyAgentLibraryItem,
  createAgentLibraryItem,
  deleteAgentLibraryItem,
  listAgentCatalog,
  listAgentLibrary,
  listAgentResources,
  removeAgentLibraryItem,
  type AgentLibraryItem,
  type AgentLibraryKind,
  type AgentLocalResource,
  type AgentPlatformAgent,
  type AgentResourceIndex,
} from "@/lib/agent-platform-api";
import {
  listMCPServers,
  setMCPServerEnabled,
  type MCPServer,
} from "@/lib/mcp-api";
import {
  consolidateMemories,
  createMemory,
  deleteMemory,
  forgetMemories,
  listMemories,
  type Memory,
} from "@/lib/memory-api";
import {
  EmptyState,
  ManagementPageHeader,
} from "@/components/ui/ManagementPage";
import {
  BrainIcon,
  ExternalLinkIcon,
  FileTextIcon,
  KeyIcon,
  LibraryIcon,
  PlugIcon,
  SearchIcon,
  ServerIcon,
  SparklesIcon,
  TerminalIcon,
  TrashIcon,
  UsersIcon,
  type IconProps,
} from "@/components/ui/icons";
import { PageSkeleton } from "@/components/ui/PageSkeleton";

type SectionId =
  | "agents"
  | "instructions"
  | "memory"
  | "mcp"
  | "skills"
  | "hooks"
  | "environment"
  | "subagents"
  | "commands"
  | "specific"
  | "claude-plugins"
  | "pi-packages"
  | "magpie"
  | "rtk"
  | "billion-context";

interface NavItem {
  id: SectionId;
  label: string;
  icon: ComponentType<IconProps>;
}

const GENERAL_NAV: NavItem[] = [
  { id: "agents", label: "所有智能体", icon: UsersIcon },
  { id: "instructions", label: "指令", icon: FileTextIcon },
  { id: "memory", label: "记忆", icon: BrainIcon },
  { id: "mcp", label: "MCP 服务器", icon: ServerIcon },
  { id: "skills", label: "技能", icon: SparklesIcon },
  { id: "hooks", label: "Hooks", icon: PlugIcon },
  { id: "environment", label: "环境变量", icon: KeyIcon },
  { id: "subagents", label: "子代理", icon: UsersIcon },
  { id: "commands", label: "斜杠命令", icon: TerminalIcon },
];

const SPECIFIC_NAV: NavItem[] = [
  { id: "specific", label: "特定智能体", icon: LibraryIcon },
  { id: "claude-plugins", label: "Claude 插件", icon: PlugIcon },
  { id: "pi-packages", label: "Pi 包", icon: LibraryIcon },
  { id: "magpie", label: "magpie", icon: TerminalIcon },
  { id: "rtk", label: "RTK", icon: TerminalIcon },
  { id: "billion-context", label: "billion-context", icon: BrainIcon },
];

const LIBRARY_SECTIONS: Partial<Record<SectionId, AgentLibraryKind>> = {
  instructions: "instructions",
  hooks: "hooks",
  environment: "env",
  subagents: "subagents",
  commands: "commands",
};

const SECTION_DESCRIPTIONS: Record<SectionId, string> = {
  agents: "查看本机安装的 Agent、能力边界和可管理资源。",
  instructions: "管理可被 Codex、Claude Code、Gemini CLI 和 OpenCode 使用的指令。",
  memory: "管理所有 Agent 共用的长期记忆。",
  mcp: "查看和启停接入 OpenTalos 的 MCP 服务器。",
  skills: "查看和管理 OpenTalos 技能。",
  hooks: "保存并应用 Agent Hooks 配置。",
  environment: "保存可复用的环境变量资源，不读取 Agent 现有密钥。",
  subagents: "管理 Claude Code、Codex 等 Agent 的子代理定义。",
  commands: "管理可复用的斜杠命令和提示词。",
  specific: "按已安装 Agent 查看专属资源与兼容能力。",
  "claude-plugins": "查看本机 Claude Code 插件市场中发现的插件。",
  "pi-packages": "查看 Pi 的托管运行时和包信息。",
  magpie: "查看本机 Magpie 资源库和插件配置。",
  rtk: "查看本机 RTK 相关资源。",
  "billion-context": "查看本机 billion-context 相关资源。",
};

export default function ResourcesPage() {
  const [section, setSection] = useState<SectionId>("agents");
  const [query, setQuery] = useState("");
  const [skills, setSkills] = useState<SkillsResponse | null>(null);
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);
  const [customAgents, setCustomAgents] = useState<CustomAgent[]>([]);
  const [externalAgents, setExternalAgents] = useState<AgentPlatformAgent[]>([]);
  const [resourceIndex, setResourceIndex] = useState<AgentResourceIndex | null>(
    null
  );
  const [library, setLibrary] = useState<AgentLibraryItem[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshMemories = () => {
    void listMemories()
      .then(setMemories)
      .catch(() => setMemories([]));
  };

  useEffect(() => {
    void Promise.allSettled([
      listSkills(),
      listMCPServers(),
      listCustomAgents(),
      listAgentCatalog(),
      listAgentResources(),
      listAgentLibrary(),
      listMemories(),
    ]).then((results) => {
      const [
        nextSkills,
        nextMcp,
        nextCustom,
        nextExternal,
        nextResources,
        nextLibrary,
        nextMemories,
      ] = results;
      if (nextSkills.status === "fulfilled") setSkills(nextSkills.value);
      else setSkills({ reachable: false, skills: [], error: "无法读取技能" });
      if (nextMcp.status === "fulfilled") setMcpServers(nextMcp.value);
      if (nextCustom.status === "fulfilled") setCustomAgents(nextCustom.value);
      if (nextExternal.status === "fulfilled") setExternalAgents(nextExternal.value);
      if (nextResources.status === "fulfilled") setResourceIndex(nextResources.value);
      else setResourceIndex({ home: "", resources: [], agents: [] });
      if (nextLibrary.status === "fulfilled") setLibrary(nextLibrary.value);
      if (nextMemories.status === "fulfilled") setMemories(nextMemories.value);

      const failed = results.find((result) => result.status === "rejected");
      if (failed?.status === "rejected") {
        setError(
          failed.reason instanceof Error
            ? failed.reason.message
            : "部分资源加载失败"
        );
      }
      setLoading(false);
    });
  }, []);

  const installedExternal = useMemo(
    () => externalAgents.filter((agent) => agent.installed),
    [externalAgents]
  );

  const localResources = useMemo(
    () => resourceIndex?.resources ?? [],
    [resourceIndex?.resources]
  );
  const needle = query.trim().toLowerCase();

  const sectionCounts = useMemo(() => {
    const countKind = (kind: AgentLibraryKind) =>
      localResources.filter((item) => item.kind === kind).length +
      library.filter((item) => item.kind === kind).length;
    return {
      agents: installedExternal.length + customAgents.length,
      instructions: countKind("instructions"),
      memory: memories.length,
      mcp: mcpServers.length,
      skills: skills?.skills.length ?? 0,
      hooks: countKind("hooks"),
      environment: countKind("env"),
      subagents: countKind("subagents"),
      commands: countKind("commands"),
      specific: resourceIndex?.agents.length ?? 0,
      "claude-plugins": localResources.filter(
        (item) => item.metadata.group === "claude-plugins"
      ).length,
      "pi-packages": localResources.filter(
        (item) => item.metadata.group === "pi-packages"
      ).length,
      magpie: localResources.filter((item) => item.metadata.group === "magpie")
        .length,
      rtk: localResources.filter((item) => item.metadata.group === "rtk").length,
      "billion-context": localResources.filter(
        (item) => item.metadata.group === "billion-context"
      ).length,
    } satisfies Record<SectionId, number>;
  }, [
    customAgents.length,
    installedExternal.length,
    library,
    localResources,
    mcpServers.length,
    memories.length,
    resourceIndex?.agents.length,
    skills?.skills.length,
  ]);

  const toggleSkill = async (name: string, added: boolean) => {
    if (!skills) return;
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

  const addMemory = async (content: string, importance: number) => {
    try {
      const memory = await createMemory(content, importance);
      setMemories((current) => [memory, ...current]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "添加记忆失败");
    }
  };

  const removeMemory = async (id: number) => {
    try {
      await deleteMemory(id);
      setMemories((current) => current.filter((item) => item.id !== id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除记忆失败");
    }
  };

  const forgetMemorySet = async (strategy: "importance_based" | "time_based" | "capacity_based") => {
    if (!window.confirm("确认执行批量遗忘？")) return;
    try {
      await forgetMemories({ strategy });
      refreshMemories();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "遗忘失败");
    }
  };

  const consolidateMemorySet = async () => {
    if (!window.confirm("确认整合相似记忆？")) return;
    try {
      await consolidateMemories();
      refreshMemories();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "整合失败");
    }
  };

  if (loading || !skills || !resourceIndex) return <PageSkeleton />;

  const libraryKind = LIBRARY_SECTIONS[section];
  const currentNav = [...GENERAL_NAV, ...SPECIFIC_NAV].find(
    (item) => item.id === section
  );
  const CurrentIcon = currentNav?.icon;

  return (
    <section className="p-6">
      <ManagementPageHeader
        title="资源库"
        description="统一管理 Agent、指令、记忆、MCP、技能和专属资源。"
      />

      <div className="grid min-h-[620px] gap-5 lg:grid-cols-[210px_minmax(0,1fr)]">
        <nav className="border-b border-border pb-4 lg:border-b-0 lg:border-r lg:pb-0 lg:pr-4">
          <NavGroup title="所有智能体" items={GENERAL_NAV} active={section} counts={sectionCounts} onSelect={setSection} />
          <div className="mt-6">
            <NavGroup title="特定智能体" items={SPECIFIC_NAV} active={section} counts={sectionCounts} onSelect={setSection} />
          </div>
        </nav>

        <div className="min-w-0">
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="flex items-center gap-2 text-lg font-semibold">
                {CurrentIcon && <CurrentIcon width={17} height={17} />}
                {currentNav?.label}
              </h2>
              <p className="mt-1 text-sm text-text-secondary">
                {SECTION_DESCRIPTIONS[section]}
              </p>
            </div>
            {(section === "mcp" || section === "skills") && (
              <Link
                href={section === "mcp" ? "/mcp" : "/skills"}
                className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar"
              >
                打开完整页面 <ExternalLinkIcon width={13} height={13} />
              </Link>
            )}
          </div>

          <label className="mb-4 flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2">
            <SearchIcon className="shrink-0 text-text-secondary" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={`搜索${currentNav?.label ?? "资源"}`}
              className="min-w-0 flex-1 bg-transparent text-sm outline-none"
            />
          </label>

          {error && <p className="mb-3 text-sm text-red-500">{error}</p>}

          {section === "agents" && (
            <AgentsPanel
              agents={installedExternal}
              customAgents={customAgents}
              query={needle}
            />
          )}

          {section === "memory" && (
            <MemoryPanel
              memories={memories}
              query={needle}
              onAdd={addMemory}
              onDelete={removeMemory}
              onForget={forgetMemorySet}
              onConsolidate={consolidateMemorySet}
            />
          )}

          {section === "mcp" && (
            <MCPPanel
              servers={mcpServers}
              query={needle}
              onToggle={toggleMcp}
            />
          )}

          {section === "skills" && (
            <SkillsPanel
              skills={skills.skills}
              query={needle}
              onToggle={toggleSkill}
            />
          )}

          {libraryKind && (
            <LibraryResourcePanel
              key={libraryKind}
              kind={libraryKind}
              query={needle}
              localResources={localResources.filter(
                (item) => item.kind === libraryKind
              )}
              libraryItems={library.filter(
                (item) => item.kind === libraryKind
              )}
              agents={installedExternal}
              onCreate={async (name, content) => {
                const item = await createAgentLibraryItem({
                  kind: libraryKind,
                  name,
                  content,
                });
                setLibrary((current) => [item, ...current]);
              }}
              onDelete={async (itemId) => {
                await deleteAgentLibraryItem(itemId);
                setLibrary((current) =>
                  current.filter((item) => item.id !== itemId)
                );
              }}
              onApply={async (agentId, itemId) => {
                await applyAgentLibraryItem(agentId, itemId);
                const refreshed = await listAgentLibrary();
                setLibrary(refreshed);
              }}
              onRemove={async (agentId, itemId) => {
                await removeAgentLibraryItem(agentId, itemId);
                const refreshed = await listAgentLibrary();
                setLibrary(refreshed);
              }}
              onError={setError}
            />
          )}

          {section === "specific" && (
            <SpecificAgentsPanel
              agents={resourceIndex.agents}
              localResources={localResources}
              query={needle}
            />
          )}

          {isLocalOnlySection(section) && (
            <LocalOnlyResourcePanel
              resources={localResources.filter(
                (item) => item.metadata.group === section
              )}
              query={needle}
            />
          )}
        </div>
      </div>
    </section>
  );
}

function NavGroup({
  title,
  items,
  active,
  counts,
  onSelect,
}: {
  title: string;
  items: NavItem[];
  active: SectionId;
  counts: Record<SectionId, number>;
  onSelect: (id: SectionId) => void;
}) {
  return (
    <div>
      <p className="mb-1 px-2 text-[11px] font-medium text-text-secondary">
        {title}
      </p>
      <div className="space-y-0.5">
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => onSelect(item.id)}
            className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm ${
              active === item.id
                ? "bg-surface font-medium text-text shadow-sm"
                : "text-text-secondary hover:bg-surface hover:text-text"
            }`}
          >
            <item.icon width={15} height={15} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">{item.label}</span>
            <span className="text-[11px] text-text-secondary">
              {counts[item.id]}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function AgentsPanel({
  agents,
  customAgents,
  query,
}: {
  agents: AgentPlatformAgent[];
  customAgents: CustomAgent[];
  query: string;
}) {
  const items = [
    ...agents.map((agent) => ({
      id: agent.id,
      name: agent.name,
      version: agent.version,
      description: agent.compatibility_path,
      capabilities: agent.capabilities,
      external: true,
    })),
    ...customAgents.map((agent) => ({
      id: agent.id,
      name: agent.name,
      version: null,
      description: agent.description,
      capabilities: agent.skills,
      external: false,
    })),
  ].filter(
    (agent) =>
      !query ||
      `${agent.name} ${agent.description} ${agent.capabilities.join(" ")}`
        .toLowerCase()
        .includes(query)
  );

  if (items.length === 0) {
    return <EmptyState title="没有匹配的 Agent" />;
  }

  return (
    <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
      {items.map((agent) => (
        <Link
          key={`${agent.external ? "external" : "custom"}:${agent.id}`}
          href="/agents"
          className="rounded-lg border border-border bg-surface p-4 hover:border-text-secondary"
        >
          <div className="flex items-center gap-2">
            <TerminalIcon width={16} height={16} className="text-text-secondary" />
            <span className="min-w-0 flex-1 truncate text-sm font-medium">
              {agent.name}
            </span>
            <span className="text-[11px] text-text-secondary">
              {agent.version ?? (agent.external ? "本机 Agent" : "OpenTalos")}
            </span>
          </div>
          <p className="mt-2 line-clamp-2 text-xs text-text-secondary">
            {agent.description}
          </p>
          {agent.capabilities.length > 0 && (
            <p className="mt-2 truncate text-[11px] text-text-secondary">
              {agent.capabilities.join(" · ")}
            </p>
          )}
        </Link>
      ))}
    </div>
  );
}

function MemoryPanel({
  memories,
  query,
  onAdd,
  onDelete,
  onForget,
  onConsolidate,
}: {
  memories: Memory[];
  query: string;
  onAdd: (content: string, importance: number) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  onForget: (
    strategy: "importance_based" | "time_based" | "capacity_based"
  ) => Promise<void>;
  onConsolidate: () => Promise<void>;
}) {
  const [adding, setAdding] = useState(false);
  const [content, setContent] = useState("");
  const [importance, setImportance] = useState(0.5);
  const filtered = memories.filter(
    (memory) => !query || memory.content.toLowerCase().includes(query)
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setAdding((current) => !current)}
          className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar"
        >
          + 添加记忆
        </button>
        <button
          type="button"
          onClick={() => void onForget("importance_based")}
          className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar"
        >
          按重要性遗忘
        </button>
        <button
          type="button"
          onClick={() => void onForget("time_based")}
          className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar"
        >
          按时间遗忘
        </button>
        <button
          type="button"
          onClick={() => void onConsolidate()}
          className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar"
        >
          整合相似记忆
        </button>
      </div>

      {adding && (
        <div className="grid gap-2 border-y border-border py-3 sm:grid-cols-[minmax(0,1fr)_150px_auto]">
          <input
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder="要长期记住的内容"
            className="rounded-lg border border-border px-3 py-1.5 text-sm"
          />
          <label className="flex items-center gap-2 text-xs text-text-secondary">
            重要性
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              value={importance}
              onChange={(event) => setImportance(Number(event.target.value))}
              className="min-w-0 flex-1"
            />
            {Math.round(importance * 100)}%
          </label>
          <button
            type="button"
            disabled={!content.trim()}
            onClick={() => {
              void onAdd(content.trim(), importance).then(() => {
                setContent("");
                setAdding(false);
              });
            }}
            className="rounded-lg bg-text px-3 py-1.5 text-sm text-white disabled:opacity-40"
          >
            保存
          </button>
        </div>
      )}

      {filtered.length === 0 ? (
        <EmptyState title="还没有记忆" description="对 Agent 说“记住……”，或在这里添加。" />
      ) : (
        <div className="divide-y divide-border border-y border-border">
          {filtered.map((memory) => (
            <div key={memory.id} className="flex items-center gap-3 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm">{memory.content}</p>
                <p className="mt-1 text-[11px] text-text-secondary">
                  重要性 {Math.round(memory.importance * 100)}%
                </p>
              </div>
              <button
                type="button"
                aria-label={`删除记忆：${memory.content}`}
                onClick={() => void onDelete(memory.id)}
                className="rounded-lg p-1.5 text-text-secondary hover:bg-sidebar hover:text-red-500"
              >
                <TrashIcon width={14} height={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MCPPanel({
  servers,
  query,
  onToggle,
}: {
  servers: MCPServer[];
  query: string;
  onToggle: (server: MCPServer) => Promise<void>;
}) {
  const filtered = servers.filter(
    (server) =>
      !query ||
      `${server.name} ${server.transport} ${server.cached_tools
        .map((tool) => tool.name)
        .join(" ")}`
        .toLowerCase()
        .includes(query)
  );
  if (filtered.length === 0) {
    return <EmptyState title="没有匹配的 MCP Server" description="可在完整 MCP 页面添加连接。" />;
  }
  return (
    <div className="divide-y divide-border border-y border-border">
      {filtered.map((server) => (
        <div key={server.id} className="flex flex-wrap items-center gap-3 py-3">
          <ServerIcon width={16} height={16} className="text-text-secondary" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">{server.name}</p>
            <p className="mt-0.5 text-xs text-text-secondary">
              {server.transport} · {server.cached_tools.length} 个工具
            </p>
          </div>
          <button
            type="button"
            onClick={() => void onToggle(server)}
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
    </div>
  );
}

function SkillsPanel({
  skills,
  query,
  onToggle,
}: {
  skills: SkillsResponse["skills"];
  query: string;
  onToggle: (name: string, added: boolean) => Promise<void>;
}) {
  const filtered = skills.filter(
    (skill) =>
      !query ||
      `${skill.name} ${skill.description} ${skill.tags.join(" ")}`
        .toLowerCase()
        .includes(query)
  );
  if (filtered.length === 0) {
    return <EmptyState title="没有匹配的技能" />;
  }
  return (
    <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
      {filtered.map((skill) => (
        <div key={skill.name} className="rounded-lg border border-border bg-surface p-4">
          <div className="flex items-start gap-2">
            <SparklesIcon width={16} height={16} className="mt-0.5 text-text-secondary" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{skill.name}</p>
              <p className="mt-1 line-clamp-2 text-xs text-text-secondary">
                {skill.description}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => void onToggle(skill.name, skill.added)}
            className={`mt-3 rounded-md border px-2 py-1 text-xs ${
              skill.added
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600"
                : "border-border text-text-secondary hover:bg-sidebar"
            }`}
          >
            {skill.added ? "已添加" : "添加"}
          </button>
        </div>
      ))}
    </div>
  );
}

function LibraryResourcePanel({
  kind,
  query,
  localResources,
  libraryItems,
  agents,
  onCreate,
  onDelete,
  onApply,
  onRemove,
  onError,
}: {
  kind: AgentLibraryKind;
  query: string;
  localResources: AgentLocalResource[];
  libraryItems: AgentLibraryItem[];
  agents: AgentPlatformAgent[];
  onCreate: (name: string, content: string) => Promise<void>;
  onDelete: (itemId: string) => Promise<void>;
  onApply: (agentId: string, itemId: string) => Promise<void>;
  onRemove: (agentId: string, itemId: string) => Promise<void>;
  onError: (message: string) => void;
}) {
  const compatibleAgents = agents.filter((agent) =>
    Boolean(agent.resource_paths[kind])
  );
  const [targetAgent, setTargetAgent] = useState(
    compatibleAgents[0]?.id ?? ""
  );
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);

  const local = localResources.filter(
    (item) =>
      !query ||
      `${item.name} ${item.description} ${item.agent_name} ${item.path}`
        .toLowerCase()
        .includes(query)
  );
  const managed = libraryItems.filter(
    (item) =>
      !query ||
      `${item.name} ${item.content}`.toLowerCase().includes(query)
  );

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "资源操作失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setAdding((current) => !current)}
          className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar"
        >
          + 添加
        </button>
        {managed.length > 0 && compatibleAgents.length > 0 && (
          <label className="flex items-center gap-2 text-xs text-text-secondary">
            应用到
            <select
              value={targetAgent}
              onChange={(event) => setTargetAgent(event.target.value)}
              className="rounded-lg border border-border bg-surface px-2 py-1.5 text-xs text-text"
            >
              {compatibleAgents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {adding && (
        <div className="grid gap-2 border-y border-border py-3">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="资源名称"
            className="rounded-lg border border-border px-3 py-1.5 text-sm"
          />
          <textarea
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder={
              kind === "env"
                ? "每行一个 KEY=VALUE"
                : kind === "hooks"
                  ? "Hooks 配置内容"
                  : "资源内容"
            }
            rows={6}
            className="rounded-lg border border-border px-3 py-2 font-mono text-xs"
          />
          <button
            type="button"
            disabled={busy || !name.trim() || !content.trim()}
            onClick={() =>
              void run(async () => {
                await onCreate(name.trim(), content);
                setName("");
                setContent("");
                setAdding(false);
              })
            }
            className="justify-self-start rounded-lg bg-text px-3 py-1.5 text-sm text-white disabled:opacity-40"
          >
            保存资源
          </button>
        </div>
      )}

      {local.length === 0 && managed.length === 0 ? (
        <EmptyState title="还没有资源" description="本机 Agent 中未发现该类型资源，可以在这里添加托管资源。" />
      ) : (
        <div className="space-y-5">
          {local.length > 0 && (
            <section>
              <h3 className="mb-2 text-xs font-medium text-text-secondary">
                本机资源
              </h3>
              <div className="divide-y divide-border border-y border-border">
                {local.map((item) => (
                  <details key={item.id} className="py-3">
                    <summary className="cursor-pointer list-none">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium">{item.name}</span>
                        <span className="rounded-full bg-sidebar px-2 py-0.5 text-[11px] text-text-secondary">
                          {item.agent_name}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-right text-[11px] text-text-secondary">
                          {item.path}
                        </span>
                      </div>
                      <p className="mt-1 truncate text-xs text-text-secondary">
                        {item.description}
                      </p>
                    </summary>
                    <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-sidebar p-3 text-xs">
                      {item.content}
                    </pre>
                  </details>
                ))}
              </div>
            </section>
          )}

          {managed.length > 0 && (
            <section>
              <h3 className="mb-2 text-xs font-medium text-text-secondary">
                OpenTalos 托管资源
              </h3>
              <div className="divide-y divide-border border-y border-border">
                {managed.map((item) => {
                  const binding = item.bindings.find(
                    (entry) => entry.agent_id === targetAgent
                  );
                  return (
                    <div key={item.id} className="flex flex-wrap items-center gap-2 py-3">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{item.name}</p>
                        <p className="mt-0.5 truncate text-xs text-text-secondary">
                          {item.content}
                        </p>
                      </div>
                      <span className="text-[11px] text-text-secondary">
                        {item.bindings.length} 个 Agent 已应用
                      </span>
                      {targetAgent && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            void run(() =>
                              binding
                                ? onRemove(targetAgent, item.id)
                                : onApply(targetAgent, item.id)
                            )
                          }
                          className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-sidebar disabled:opacity-40"
                        >
                          {binding ? "移除" : "应用"}
                        </button>
                      )}
                      <button
                        type="button"
                        disabled={busy}
                        aria-label={`删除资源 ${item.name}`}
                        onClick={() => void run(() => onDelete(item.id))}
                        className="rounded-lg p-1.5 text-text-secondary hover:bg-sidebar hover:text-red-500"
                      >
                        <TrashIcon width={14} height={14} />
                      </button>
                    </div>
                  );
                })}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

function SpecificAgentsPanel({
  agents,
  localResources,
  query,
}: {
  agents: AgentResourceIndex["agents"];
  localResources: AgentLocalResource[];
  query: string;
}) {
  const filtered = agents.filter(
    (agent) =>
      !query ||
      `${agent.name} ${agent.capabilities.join(" ")}`
        .toLowerCase()
        .includes(query)
  );
  if (filtered.length === 0) {
    return <EmptyState title="没有匹配的特定智能体资源" />;
  }
  return (
    <div className="divide-y divide-border border-y border-border">
      {filtered.map((agent) => {
        const resources = localResources.filter(
          (item) => item.agent_id === agent.id
        );
        return (
          <Link
            key={agent.id}
            href="/agents"
            className="flex items-center gap-3 py-3 hover:bg-sidebar"
          >
            <TerminalIcon width={16} height={16} className="text-text-secondary" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{agent.name}</p>
              <p className="mt-0.5 truncate text-xs text-text-secondary">
                {resources.length} 个资源 · {agent.capabilities.join(" · ")}
              </p>
            </div>
            <ExternalLinkIcon width={13} height={13} className="text-text-secondary" />
          </Link>
        );
      })}
    </div>
  );
}

function LocalOnlyResourcePanel({
  resources,
  query,
}: {
  resources: AgentLocalResource[];
  query: string;
}) {
  const filtered = resources.filter(
    (item) =>
      !query ||
      `${item.name} ${item.description} ${item.path}`.toLowerCase().includes(query)
  );
  if (filtered.length === 0) {
    return <EmptyState title="没有发现资源" description="当前电脑上没有该智能体可读取的公开资源文件。" />;
  }
  return (
    <div className="divide-y divide-border border-y border-border">
      {filtered.map((item) => (
        <details key={item.id} className="py-3">
          <summary className="cursor-pointer list-none">
            <div className="flex items-center gap-2">
              <FileTextIcon width={15} height={15} className="text-text-secondary" />
              <span className="text-sm font-medium">{item.name}</span>
              <span className="min-w-0 flex-1 truncate text-right text-[11px] text-text-secondary">
                {item.path}
              </span>
            </div>
            <p className="mt-1 text-xs text-text-secondary">{item.description}</p>
          </summary>
          <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-sidebar p-3 text-xs">
            {item.content}
          </pre>
        </details>
      ))}
    </div>
  );
}

function isLocalOnlySection(section: SectionId): boolean {
  return [
    "claude-plugins",
    "pi-packages",
    "magpie",
    "rtk",
    "billion-context",
  ].includes(section);
}
