"use client";

import { useEffect, useState } from "react";
import {
  createMCPServer,
  listMCPServers,
  setMCPServerEnabled,
  refreshMCPServer,
  deleteMCPServer,
  type MCPServer,
} from "@/lib/mcp-api";
import { TrashIcon } from "@/components/ui/icons";
import { PageSkeleton } from "@/components/ui/PageSkeleton";

function ConfirmDeleteServerDialog({
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
      <div role="alertdialog" aria-modal="true" className="relative z-10 w-full max-w-sm rounded-2xl bg-white p-5 shadow-2xl">
        <h2 className="text-sm font-semibold">删除这个 MCP Server 连接？</h2>
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

export default function MCPPage() {
  const [servers, setServers] = useState<MCPServer[] | null>(null);
  const [name, setName] = useState("");
  const [transport, setTransport] = useState<"stdio" | "http">("stdio");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [url, setUrl] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listMCPServers().then(setServers);
  }, []);

  const handleAdd = async () => {
    const trimmedName = name.trim();
    if (!trimmedName) return;
    setError(null);
    setBusy(true);
    try {
      const server = await createMCPServer({
        name: trimmedName,
        transport,
        command: transport === "stdio" ? command.trim() : undefined,
        args: transport === "stdio" ? args.split(" ").filter(Boolean) : undefined,
        url: transport === "http" ? url.trim() : undefined,
      });
      setServers((prev) => [server, ...(prev ?? [])]);
      setName("");
      setCommand("");
      setArgs("");
      setUrl("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "添加失败");
    } finally {
      setBusy(false);
    }
  };

  const handleToggle = async (server: MCPServer) => {
    const updated = await setMCPServerEnabled(server.id, !server.enabled);
    setServers((prev) => prev?.map((s) => (s.id === server.id ? updated : s)) ?? null);
  };

  const handleRefresh = async (id: string) => {
    const updated = await refreshMCPServer(id);
    setServers((prev) => prev?.map((s) => (s.id === id ? updated : s)) ?? null);
  };

  const handleDelete = async (id: string) => {
    await deleteMCPServer(id);
    setServers((prev) => prev?.filter((s) => s.id !== id) ?? null);
  };

  if (servers === null) return <PageSkeleton />;

  return (
    <section className="p-6">
      <h1 className="mb-4 text-xl font-semibold">MCP</h1>
      <p className="mb-4 text-sm text-text-secondary">
        连接外部 MCP（Model Context Protocol）server，把它暴露的工具接入 agent 的工具集。
      </p>

      <div className="mb-6 rounded-xl border border-border bg-white p-4">
        <h2 className="mb-3 text-sm font-medium">添加 MCP Server</h2>
        <div className="space-y-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="名称，例如：weather"
            className="w-full rounded-lg border border-border px-3 py-1.5 text-sm"
          />
          <div className="flex gap-3 text-sm">
            <label className="flex items-center gap-1.5">
              <input type="radio" checked={transport === "stdio"} onChange={() => setTransport("stdio")} />
              stdio
            </label>
            <label className="flex items-center gap-1.5">
              <input type="radio" checked={transport === "http"} onChange={() => setTransport("http")} />
              http
            </label>
          </div>
          {transport === "stdio" ? (
            <div className="flex gap-2">
              <input
                value={command}
                onChange={(e) => setCommand(e.target.value)}
                placeholder="命令，例如：python"
                className="flex-1 rounded-lg border border-border px-3 py-1.5 text-sm"
              />
              <input
                value={args}
                onChange={(e) => setArgs(e.target.value)}
                placeholder="参数（空格分隔），例如：demo_server.py"
                className="flex-[2] rounded-lg border border-border px-3 py-1.5 text-sm"
              />
            </div>
          ) : (
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="URL，例如：http://127.0.0.1:8765/mcp"
              className="w-full rounded-lg border border-border px-3 py-1.5 text-sm"
            />
          )}
          <button
            type="button"
            disabled={busy}
            onClick={() => void handleAdd()}
            className="rounded-lg bg-text px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy ? "连接中…" : "添加"}
          </button>
        </div>
        {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
      </div>

      <div className="rounded-xl border border-border bg-white p-4">
        <h2 className="mb-3 text-sm font-medium">已配置的 Server</h2>
        {servers.length === 0 ? (
          <p className="text-sm text-text-secondary">还没有配置任何 MCP Server。</p>
        ) : (
          <ul className="space-y-2">
            {servers.map((server) => {
              const expanded = expandedId === server.id;
              return (
                <li key={server.id} className="rounded-lg border border-border">
                  <div className="flex items-center gap-2 px-3 py-2 text-sm">
                    <button
                      type="button"
                      onClick={() => setExpandedId(expanded ? null : server.id)}
                      className="flex flex-1 items-center justify-between text-left"
                    >
                      <span>
                        <span className="font-medium">{server.name}</span>
                        <span className="ml-2 text-text-secondary">
                          {server.transport} · {server.enabled ? "已启用" : "已禁用"}
                        </span>
                      </span>
                      <span className="text-text-secondary">{expanded ? "收起" : "展开"}</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleToggle(server)}
                      className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-sidebar"
                    >
                      {server.enabled ? "禁用" : "启用"}
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleRefresh(server.id)}
                      className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-sidebar"
                    >
                      刷新
                    </button>
                    <button
                      type="button"
                      aria-label={`删除 MCP Server：${server.name}`}
                      onClick={() => setPendingDeleteId(server.id)}
                      className="text-text-secondary hover:text-red-500"
                    >
                      <TrashIcon width={14} height={14} />
                    </button>
                  </div>
                  {expanded && (
                    <div className="space-y-2 border-t border-border p-3 text-sm">
                      {server.last_error && <p className="text-red-500">{server.last_error}</p>}
                      {server.cached_tools.length === 0 ? (
                        <p className="text-text-secondary">没有探测到任何工具。</p>
                      ) : (
                        <ul className="space-y-1">
                          {server.cached_tools.map((tool) => (
                            <li key={tool.name}>
                              <span className="font-medium">{tool.name}</span>
                              <span className="ml-2 text-text-secondary">{tool.description}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <ConfirmDeleteServerDialog
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
