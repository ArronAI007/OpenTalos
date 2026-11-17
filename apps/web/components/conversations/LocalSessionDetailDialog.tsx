"use client";

import { useEffect, useState } from "react";

import {
  getLocalAgentSession,
  resumeCommand,
  type LocalAgentSession,
  type LocalAgentSessionDetail,
} from "@/lib/local-sessions-api";
import { copyText } from "@/lib/clipboard";
import {
  CopyIcon,
  FolderIcon,
  TerminalIcon,
  XIcon,
} from "@/components/ui/icons";

export function LocalSessionDetailDialog({
  session,
  onClose,
}: {
  session: LocalAgentSession;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<LocalAgentSessionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let active = true;
    getLocalAgentSession(session.source, session.session_id)
      .then((value) => {
        if (active) setDetail(value);
      })
      .catch((reason) => {
        if (active) {
          setError(reason instanceof Error ? reason.message : "无法读取会话");
        }
      });
    return () => {
      active = false;
    };
  }, [session.session_id, session.source]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const command = resumeCommand(session.source, session.session_id);
  const current = detail ?? session;

  const copyResume = async () => {
    if (!command) return;
    try {
      await copyText(command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setError("无法复制继续命令");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-3 py-5">
      <button
        type="button"
        aria-label="关闭会话详情"
        className="absolute inset-0 bg-black/45"
        onClick={onClose}
      />
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="local-session-title"
        className="relative flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-2xl"
      >
        <header className="flex shrink-0 items-start gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0 flex-1">
            <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-text-secondary">
              <span className="rounded-full bg-sidebar px-2 py-0.5 font-medium text-text">
                {current.source_name}
              </span>
              {current.model && <span>{current.model}</span>}
              {current.total_tokens > 0 && (
                <span>{formatNumber(current.total_tokens)} tokens</span>
              )}
              {current.cost_usd != null && current.cost_usd > 0 && (
                <span>${current.cost_usd.toFixed(4)}</span>
              )}
            </div>
            <h2 id="local-session-title" className="truncate text-base font-semibold">
              {current.title}
            </h2>
            {current.cwd && (
              <p
                className="mt-1 flex min-w-0 items-center gap-1.5 text-xs text-text-secondary"
                title={current.cwd}
              >
                <FolderIcon width={13} height={13} className="shrink-0" />
                <span className="truncate">{current.cwd}</span>
              </p>
            )}
          </div>
          {command && (
            <button
              type="button"
              onClick={() => void copyResume()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs hover:bg-sidebar"
              title={command}
            >
              {copied ? <TerminalIcon width={13} height={13} /> : <CopyIcon width={13} height={13} />}
              {copied ? "已复制" : "继续命令"}
            </button>
          )}
          <button
            type="button"
            aria-label="关闭"
            onClick={onClose}
            className="rounded-lg p-1.5 text-text-secondary hover:bg-sidebar hover:text-text"
          >
            <XIcon width={16} height={16} />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {!detail && !error && (
            <p role="status" className="py-10 text-center text-sm text-text-secondary">
              正在读取会话…
            </p>
          )}
          {error && <p className="py-8 text-center text-sm text-red-500">{error}</p>}
          {detail && detail.messages.length === 0 && (
            <p className="py-8 text-center text-sm text-text-secondary">
              这个会话没有可显示的对话内容。
            </p>
          )}
          {detail && detail.messages.length > 0 && (
            <div className="divide-y divide-border">
              {detail.messages.map((message, index) => (
                <article
                  key={`${message.timestamp ?? "message"}-${index}`}
                  className="grid gap-2 py-4 sm:grid-cols-[74px_minmax(0,1fr)]"
                >
                  <div>
                    <span
                      className={`text-xs font-medium ${
                        message.role === "user" ? "text-text" : "text-accent"
                      }`}
                    >
                      {message.role === "user" ? "你" : current.source_name}
                    </span>
                    {message.timestamp && (
                      <p className="mt-1 text-[11px] text-text-secondary">
                        {formatMessageDate(message.timestamp)}
                      </p>
                    )}
                  </div>
                  <p className="min-w-0 whitespace-pre-wrap break-words text-sm leading-6">
                    {message.content}
                  </p>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("zh-CN", { notation: "compact" }).format(value);
}

function formatMessageDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
