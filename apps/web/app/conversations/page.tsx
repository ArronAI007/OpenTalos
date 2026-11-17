"use client";

import { useEffect, useMemo, useState } from "react";

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
  FolderIcon,
  SearchIcon,
  TerminalIcon,
} from "@/components/ui/icons";
import { LocalSessionDetailDialog } from "@/components/conversations/LocalSessionDetailDialog";

const SOURCE_STORAGE_KEY = "opentalos.sessionsAgent";

export default function ConversationsPage() {
  const [localSessions, setLocalSessions] = useState<LocalAgentSession[]>([]);
  const [localSources, setLocalSources] = useState<LocalAgentSource[]>([]);
  const [localHome, setLocalHome] = useState("");
  const [source, setSource] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSession, setSelectedSession] =
    useState<LocalAgentSession | null>(null);

  useEffect(() => {
    listLocalAgentSessions()
      .then((payload) => {
        setLocalSessions(payload.sessions);
        setLocalSources(payload.sources);
        setLocalHome(payload.home);

        const saved = localStorage.getItem(SOURCE_STORAGE_KEY);
        const nextSource =
          payload.sources.find((item) => item.id === saved)?.id ??
          payload.sources[0]?.id ??
          "";
        setSource(nextSource);
        if (nextSource) localStorage.setItem(SOURCE_STORAGE_KEY, nextSource);
      })
      .catch((reason) => {
        setError(
          reason instanceof Error
            ? `无法读取本机 Agent 会话：${reason.message}`
            : "无法读取本机 Agent 会话"
        );
      })
      .finally(() => setLoading(false));
  }, []);

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
    const needle = query.trim().toLowerCase();
    return localSessions
      .filter((session) => {
        if (session.subagent || session.source !== source) return false;
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
      .sort((left, right) => right.updated_at.localeCompare(left.updated_at));
  }, [localSessions, query, source]);

  const chooseSource = (sourceId: string) => {
    setSource(sourceId);
    localStorage.setItem(SOURCE_STORAGE_KEY, sourceId);
  };

  return (
    <section className="p-6">
      <ManagementPageHeader
        title="会话"
        description="浏览并从本机 Agent 的历史会话继续工作。"
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1.5" aria-label="Agent 来源">
          {localSources.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => chooseSource(option.id)}
              className={`rounded-full border px-3 py-1.5 text-sm ${
                source === option.id
                  ? "border-text bg-text text-white"
                  : "border-border bg-surface text-text-secondary hover:text-text"
              }`}
            >
              {option.name} {option.count}
            </button>
          ))}
        </div>
        <label className="ml-auto flex min-w-56 flex-1 items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 sm:max-w-sm">
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
      {loading && (
        <p role="status" className="mb-3 text-xs text-text-secondary">
          正在读取本机会话…
        </p>
      )}

      {filtered.length === 0 ? (
        <EmptyState
          title={loading ? "正在读取会话" : "没有本机会话"}
          description={
            loading
              ? "正在扫描 Codex、Claude Code 和 Pi 的本地会话目录。"
              : query
                ? "当前 Agent 中没有匹配的会话。"
                : "启动并使用 Codex、Claude Code 或 Pi 后，会话会显示在这里。"
          }
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-border bg-surface">
          {filtered.map((session, index) => (
            <LocalConversationRow
              key={session.id}
              session={session}
              home={localHome}
              subagentCount={subagentCounts.get(session.session_id) ?? 0}
              separated={index > 0}
              onOpen={() => setSelectedSession(session)}
            />
          ))}
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
      className={`grid w-full gap-3 px-4 py-3 text-left hover:bg-sidebar sm:grid-cols-[minmax(0,1fr)_150px_190px_auto] sm:items-center ${
        separated ? "border-t border-border" : ""
      }`}
    >
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{session.title}</p>
        <p className="mt-0.5 truncate text-xs text-text-secondary">
          {session.preview !== session.title
            ? session.preview
            : session.source_name}
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
