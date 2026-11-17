"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  createTask,
  listProjects,
  listTasks,
  updateTask,
  type Project,
  type Task,
} from "@/lib/api";
import {
  conversationTitle,
  filterConversations,
} from "@/lib/conversation-filter";
import {
  listLocalAgentSessions,
  type LocalAgentSession,
  type LocalAgentSource,
} from "@/lib/local-sessions-api";
import {
  EmptyState,
  ManagementPageHeader,
} from "@/components/ui/ManagementPage";
import {
  ArchiveIcon,
  ArchiveRestoreIcon,
  FolderIcon,
  PinIcon,
  SearchIcon,
  TerminalIcon,
} from "@/components/ui/icons";
import { LocalSessionDetailDialog } from "@/components/conversations/LocalSessionDetailDialog";

type ConversationTab = "active" | "archived";

type ConversationItem =
  | { kind: "task"; task: Task }
  | { kind: "local"; session: LocalAgentSession };

const OPEN_TALOS_SOURCE = {
  id: "opentalos",
  name: "OpenTalos",
};

export default function ConversationsPage() {
  const router = useRouter();
  const [tab, setTab] = useState<ConversationTab>("active");
  const [activeTasks, setActiveTasks] = useState<Task[]>([]);
  const [archivedTasks, setArchivedTasks] = useState<Task[]>([]);
  const [localSessions, setLocalSessions] = useState<LocalAgentSession[]>([]);
  const [localSources, setLocalSources] = useState<LocalAgentSource[]>([]);
  const [localHome, setLocalHome] = useState("");
  const [localLoading, setLocalLoading] = useState(true);
  const [projects, setProjects] = useState<Project[]>([]);
  const [source, setSource] = useState("all");
  const [query, setQuery] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [selectedSession, setSelectedSession] =
    useState<LocalAgentSession | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void Promise.allSettled([
      listTasks(),
      listTasks({ archived: true }),
      listProjects(),
    ]).then(([active, archived, nextProjects]) => {
      if (active.status === "fulfilled") setActiveTasks(active.value);
      else setError("无法加载 OpenTalos 会话");
      if (archived.status === "fulfilled") setArchivedTasks(archived.value);
      if (nextProjects.status === "fulfilled") setProjects(nextProjects.value);
    });

    listLocalAgentSessions()
      .then((payload) => {
        setLocalSessions(payload.sessions);
        setLocalSources(payload.sources);
        setLocalHome(payload.home);
      })
      .catch((reason) => {
        setError(
          reason instanceof Error
            ? `无法读取本机 Agent 会话：${reason.message}`
            : "无法读取本机 Agent 会话"
        );
      })
      .finally(() => setLocalLoading(false));
  }, []);

  const sourceOptions = useMemo(
    () => [
      {
        id: "all",
        name: "全部",
        count: activeTasks.length + localSessions.length,
      },
      {
        ...OPEN_TALOS_SOURCE,
        count: activeTasks.length,
      },
      ...localSources,
    ],
    [activeTasks.length, localSessions.length, localSources]
  );

  const subagentCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const session of localSessions) {
      if (!session.subagent || !session.parent_session_id) continue;
      counts.set(
        session.parent_session_id,
        (counts.get(session.parent_session_id) ?? 0) + 1
      );
    }
    return counts;
  }, [localSessions]);

  const filtered = useMemo(() => {
    if (tab === "archived") {
      return filterConversations(archivedTasks, query).map(
        (task): ConversationItem => ({ kind: "task", task })
      );
    }

    const needle = query.trim().toLowerCase();
    const taskItems: ConversationItem[] = activeTasks
      .filter((task) => {
        if (source !== "all" && source !== OPEN_TALOS_SOURCE.id) return false;
        if (!needle) return true;
        return `${task.title} ${task.agent_name ?? ""} ${task.agent_type}`
          .toLowerCase()
          .includes(needle);
      })
      .map((task) => ({ kind: "task", task }));

    const localItems: ConversationItem[] = localSessions
      .filter((session) => {
        if (session.subagent) return false;
        if (
          source !== "all" &&
          source !== OPEN_TALOS_SOURCE.id &&
          source !== session.source
        ) {
          return false;
        }
        if (source === OPEN_TALOS_SOURCE.id) return false;
        if (!needle) return true;
        return [
          session.title,
          session.preview,
          session.cwd,
          session.source_name,
          session.model,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(needle);
      })
      .map((session) => ({ kind: "local", session }));

    return [...taskItems, ...localItems].sort((left, right) => {
      if (left.kind === "task" && right.kind === "task") {
        if (left.task.pinned !== right.task.pinned) {
          return left.task.pinned ? -1 : 1;
        }
      }
      return updatedAt(right).localeCompare(updatedAt(left));
    });
  }, [activeTasks, archivedTasks, localSessions, query, source, tab]);

  const createConversation = async () => {
    setCreating(true);
    setError(null);
    try {
      const task = await createTask();
      router.push(`/t/${task.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建会话失败");
      setCreating(false);
    }
  };

  const setArchived = async (task: Task, archived: boolean) => {
    setBusyId(task.id);
    setError(null);
    try {
      const updated = await updateTask(task.id, { archived });
      if (archived) {
        setActiveTasks((current) =>
          current.filter((item) => item.id !== task.id)
        );
        setArchivedTasks((current) => [updated, ...current]);
      } else {
        setArchivedTasks((current) =>
          current.filter((item) => item.id !== task.id)
        );
        setActiveTasks((current) => [updated, ...current]);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "更新会话失败");
    } finally {
      setBusyId(null);
    }
  };

  const togglePinned = async (task: Task) => {
    setBusyId(task.id);
    try {
      const updated = await updateTask(task.id, { pinned: !task.pinned });
      setActiveTasks((current) =>
        current.map((item) => (item.id === task.id ? updated : item))
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "更新会话失败");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="p-6">
      <ManagementPageHeader
        title="会话"
        description="浏览和恢复 OpenTalos 与本机 Agent 的会话。"
        actions={
          <button
            type="button"
            onClick={() => void createConversation()}
            disabled={creating}
            className="rounded-lg bg-text px-3 py-1.5 text-sm text-white disabled:opacity-40"
          >
            {creating ? "创建中…" : "新建会话"}
          </button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border border-border p-0.5">
          <button
            type="button"
            onClick={() => {
              setTab("active");
              setSource("all");
            }}
            className={`rounded-md px-3 py-1.5 text-sm ${
              tab === "active" ? "bg-text text-white" : "text-text-secondary"
            }`}
          >
            会话{" "}
            {activeTasks.length + localSessions.length}
          </button>
          <button
            type="button"
            onClick={() => setTab("archived")}
            className={`rounded-md px-3 py-1.5 text-sm ${
              tab === "archived" ? "bg-text text-white" : "text-text-secondary"
            }`}
          >
            已归档 {archivedTasks.length}
          </button>
        </div>
        <label className="flex min-w-56 flex-1 items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2">
          <SearchIcon className="shrink-0 text-text-secondary" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索会话"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none"
          />
        </label>
      </div>

      {tab === "active" && (
        <div className="mb-4 flex flex-wrap gap-1.5" aria-label="会话来源">
          {sourceOptions.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => setSource(option.id)}
              className={`rounded-full border px-2.5 py-1 text-xs ${
                source === option.id
                  ? "border-text bg-text text-white"
                  : "border-border bg-surface text-text-secondary hover:text-text"
              }`}
            >
              {option.name} {option.count}
            </button>
          ))}
        </div>
      )}

      {error && <p className="mb-3 text-sm text-red-500">{error}</p>}
      {tab === "active" && localLoading && (
        <p role="status" className="mb-3 text-xs text-text-secondary">
          正在读取本机会话…
        </p>
      )}

      {filtered.length === 0 ? (
        <EmptyState
          title={
            tab === "archived"
              ? "归档为空"
              : localLoading
                ? "正在读取会话"
                : "还没有会话"
          }
          description={
            tab === "archived"
              ? "归档的 OpenTalos 会话会显示在这里。"
              : "OpenTalos 和本机 Agent 的新会话会显示在这里。"
          }
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-border bg-surface">
          {filtered.map((item, index) =>
            item.kind === "task" ? (
              <TaskConversationRow
                key={`task:${item.task.id}`}
                task={item.task}
                project={projects.find(
                  (entry) => entry.id === item.task.project_id
                )}
                tab={tab}
                busy={busyId === item.task.id}
                separated={index > 0}
                onTogglePinned={togglePinned}
                onSetArchived={setArchived}
              />
            ) : (
              <LocalConversationRow
                key={item.session.id}
                session={item.session}
                home={localHome}
                subagentCount={
                  subagentCounts.get(item.session.session_id) ?? 0
                }
                separated={index > 0}
                onOpen={() => setSelectedSession(item.session)}
              />
            )
          )}
        </div>
      )}

      {selectedSession && (
        <LocalSessionDetailDialog
          session={selectedSession}
          onClose={() => setSelectedSession(null)}
        />
      )}
    </section>
  );
}

function TaskConversationRow({
  task,
  project,
  tab,
  busy,
  separated,
  onTogglePinned,
  onSetArchived,
}: {
  task: Task;
  project: Project | undefined;
  tab: ConversationTab;
  busy: boolean;
  separated: boolean;
  onTogglePinned: (task: Task) => Promise<void>;
  onSetArchived: (task: Task, archived: boolean) => Promise<void>;
}) {
  return (
    <div
      className={`grid gap-3 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_140px_150px_auto] sm:items-center ${
        separated ? "border-t border-border" : ""
      }`}
    >
      <div className="min-w-0">
        <Link
          href={`/t/${task.id}`}
          className="block truncate text-sm font-medium hover:underline"
        >
          {conversationTitle(task)}
        </Link>
        <p className="mt-0.5 truncate text-xs text-text-secondary">
          OpenTalos · {task.agent_name ?? task.agent_type}
          {project ? ` · ${project.name}` : ""}
        </p>
      </div>
      <span className="text-xs text-text-secondary">
        {formatRelativeDate(task.updated_at)}
      </span>
      <span className="text-xs text-text-secondary">
        {task.pinned ? "已置顶" : task.starred ? "已收藏" : "OpenTalos 会话"}
      </span>
      <div className="flex items-center justify-end gap-1">
        {tab === "active" && (
          <button
            type="button"
            onClick={() => void onTogglePinned(task)}
            disabled={busy}
            aria-label={`${task.pinned ? "取消置顶" : "置顶"} ${conversationTitle(task)}`}
            className={`rounded-lg p-1.5 hover:bg-sidebar ${
              task.pinned ? "text-accent" : "text-text-secondary"
            }`}
          >
            <PinIcon width={14} height={14} />
          </button>
        )}
        <button
          type="button"
          onClick={() => void onSetArchived(task, tab === "active")}
          disabled={busy}
          aria-label={`${tab === "active" ? "归档" : "恢复"} ${conversationTitle(task)}`}
          title={tab === "active" ? "归档" : "恢复"}
          className="rounded-lg p-1.5 text-text-secondary hover:bg-sidebar"
        >
          {tab === "active" ? (
            <ArchiveIcon width={14} height={14} />
          ) : (
            <ArchiveRestoreIcon width={14} height={14} />
          )}
        </button>
      </div>
    </div>
  );
}

function LocalConversationRow({
  session,
  home,
  subagentCount,
  separated,
  onOpen,
}: {
  session: LocalAgentSession;
  home: string;
  subagentCount: number;
  separated: boolean;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={`grid w-full gap-3 px-4 py-3 text-left hover:bg-sidebar sm:grid-cols-[minmax(0,1fr)_150px_170px_auto] sm:items-center ${
        separated ? "border-t border-border" : ""
      }`}
    >
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{session.title}</p>
        <p className="mt-0.5 truncate text-xs text-text-secondary">
          {session.preview !== session.title ? session.preview : session.source_name}
        </p>
        <p
          className="mt-1 flex min-w-0 items-center gap-1 text-[11px] text-text-secondary"
          title={session.cwd ?? undefined}
        >
          <FolderIcon width={12} height={12} className="shrink-0" />
          <span className="truncate">
            {session.cwd ? formatCwd(session.cwd, home) : "无项目目录"}
          </span>
        </p>
      </div>
      <span className="text-xs text-text-secondary">
        {formatRelativeDate(session.updated_at)}
      </span>
      <span className="flex flex-wrap items-center gap-1.5 text-[11px] text-text-secondary">
        <span className={`rounded-full px-2 py-0.5 ${sourceTone(session.source)}`}>
          {session.source_name}
        </span>
        {session.user_message_count > 0 && (
          <span>{session.user_message_count} 轮</span>
        )}
        {session.total_tokens > 0 && (
          <span>{formatNumber(session.total_tokens)} tokens</span>
        )}
        {subagentCount > 0 && <span>{subagentCount} 个子代理</span>}
      </span>
      <span className="inline-flex items-center justify-end gap-1 text-xs text-text-secondary">
        <TerminalIcon width={13} height={13} />
        查看
      </span>
    </button>
  );
}

function updatedAt(item: ConversationItem): string {
  return item.kind === "task" ? item.task.updated_at : item.session.updated_at;
}

function formatRelativeDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const formatter = new Intl.RelativeTimeFormat("zh-CN", { numeric: "auto" });
  if (Math.abs(seconds) < 60) return formatter.format(seconds, "second");
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return formatter.format(hours, "hour");
  const days = Math.round(hours / 24);
  if (Math.abs(days) < 30) return formatter.format(days, "day");
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function formatCwd(cwd: string, home: string): string {
  if (home && cwd === home) return "~";
  if (home && cwd.startsWith(`${home}/`)) return `~${cwd.slice(home.length)}`;
  return cwd;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("zh-CN", { notation: "compact" }).format(value);
}

function sourceTone(source: string): string {
  if (source === "codex") return "bg-amber-500/10 text-amber-700";
  if (source === "claude-code") return "bg-orange-500/10 text-orange-700";
  if (source === "pi") return "bg-sky-500/10 text-sky-700";
  return "bg-sidebar text-text-secondary";
}
