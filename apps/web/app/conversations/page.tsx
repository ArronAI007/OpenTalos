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
  EmptyState,
  ManagementPageHeader,
} from "@/components/ui/ManagementPage";
import {
  ArchiveIcon,
  ArchiveRestoreIcon,
  PinIcon,
  SearchIcon,
} from "@/components/ui/icons";

type ConversationTab = "active" | "archived";

export default function ConversationsPage() {
  const router = useRouter();
  const [tab, setTab] = useState<ConversationTab>("active");
  const [activeTasks, setActiveTasks] = useState<Task[]>([]);
  const [archivedTasks, setArchivedTasks] = useState<Task[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [query, setQuery] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listTasks(), listTasks({ archived: true }), listProjects()])
      .then(([active, archived, nextProjects]) => {
        setActiveTasks(active);
        setArchivedTasks(archived);
        setProjects(nextProjects);
      })
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : "无法加载会话")
      );
  }, []);

  const filtered = useMemo(
    () =>
      filterConversations(
        tab === "active" ? activeTasks : archivedTasks,
        query
      ),
    [activeTasks, archivedTasks, query, tab]
  );

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
        setActiveTasks((current) => current.filter((item) => item.id !== task.id));
        setArchivedTasks((current) => [updated, ...current]);
      } else {
        setArchivedTasks((current) => current.filter((item) => item.id !== task.id));
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
        description="浏览、恢复和整理 OpenTalos 中的所有会话。"
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
            onClick={() => setTab("active")}
            className={`rounded-md px-3 py-1.5 text-sm ${
              tab === "active" ? "bg-text text-white" : "text-text-secondary"
            }`}
          >
            会话 {activeTasks.length}
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

      {error && <p className="mb-3 text-sm text-red-500">{error}</p>}

      {filtered.length === 0 ? (
        <EmptyState
          title={tab === "active" ? "还没有会话" : "归档为空"}
          description={
            tab === "active"
              ? "从首页或右上角新建一个会话。"
              : "归档的会话会显示在这里。"
          }
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-border bg-surface">
          {filtered.map((task, index) => {
            const project = projects.find((item) => item.id === task.project_id);
            return (
              <div
                key={task.id}
                className={`grid gap-3 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_140px_150px_auto] sm:items-center ${
                  index ? "border-t border-border" : ""
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
                    {task.agent_name ?? task.agent_type}
                    {project ? ` · ${project.name}` : ""}
                  </p>
                </div>
                <span className="text-xs text-text-secondary">
                  {formatDate(task.updated_at)}
                </span>
                <span className="text-xs text-text-secondary">
                  {task.pinned ? "已置顶" : task.starred ? "已收藏" : "普通会话"}
                </span>
                <div className="flex items-center justify-end gap-1">
                  {tab === "active" && (
                    <button
                      type="button"
                      onClick={() => void togglePinned(task)}
                      disabled={busyId === task.id}
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
                    onClick={() => void setArchived(task, tab === "active")}
                    disabled={busyId === task.id}
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
          })}
        </div>
      )}
    </section>
  );
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
