"use client";

import { useEffect, useState } from "react";
import {
  createAgentRole,
  listAgentRoles,
  setAgentRoleEnabled,
  deleteAgentRole,
  type AgentRole,
} from "@/lib/roles-api";
import { TrashIcon } from "@/components/ui/icons";

function ConfirmDeleteRoleDialog({
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
        <h2 className="text-sm font-semibold">删除这个角色？</h2>
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

export default function RolesPage() {
  const [roles, setRoles] = useState<AgentRole[] | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [peerUrl, setPeerUrl] = useState("");
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listAgentRoles().then(setRoles);
  }, []);

  const handleAdd = async () => {
    const trimmedName = name.trim();
    const trimmedDescription = description.trim();
    const trimmedUrl = peerUrl.trim();
    if (!trimmedName || !trimmedDescription || !trimmedUrl) return;
    setError(null);
    setBusy(true);
    try {
      const role = await createAgentRole({
        name: trimmedName, description: trimmedDescription, peer_url: trimmedUrl,
      });
      setRoles((prev) => [role, ...(prev ?? [])]);
      setName("");
      setDescription("");
      setPeerUrl("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "添加失败");
    } finally {
      setBusy(false);
    }
  };

  const handleToggle = async (role: AgentRole) => {
    const updated = await setAgentRoleEnabled(role.id, !role.enabled);
    setRoles((prev) => prev?.map((r) => (r.id === role.id ? updated : r)) ?? null);
  };

  const handleDelete = async (id: string) => {
    await deleteAgentRole(id);
    setRoles((prev) => prev?.filter((r) => r.id !== id) ?? null);
  };

  if (roles === null) return null;

  return (
    <section className="p-6">
      <h1 className="mb-4 text-xl font-semibold">角色</h1>
      <p className="mb-4 text-sm text-text-secondary">
        配置 PlanExecuteAgent 可以把规划步骤分发给哪些角色——每个角色是一个独立运行的 A2A peer 进程。
      </p>

      <div className="mb-6 rounded-xl border border-border bg-white p-4">
        <h2 className="mb-3 text-sm font-medium">添加角色</h2>
        <div className="space-y-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="名字，例如：researcher"
            className="w-full rounded-lg border border-border px-3 py-1.5 text-sm"
          />
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="描述，例如：擅长检索和总结事实信息"
            className="w-full rounded-lg border border-border px-3 py-1.5 text-sm"
          />
          <input
            value={peerUrl}
            onChange={(e) => setPeerUrl(e.target.value)}
            placeholder="Peer URL，例如：http://127.0.0.1:8431/"
            className="w-full rounded-lg border border-border px-3 py-1.5 text-sm"
          />
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
        <h2 className="mb-3 text-sm font-medium">已配置的角色</h2>
        {roles.length === 0 ? (
          <p className="text-sm text-text-secondary">还没有配置任何角色。</p>
        ) : (
          <ul className="space-y-2">
            {roles.map((role) => (
              <li key={role.id} className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm">
                <span className="flex-1">
                  <span className="font-medium">{role.name}</span>
                  <span className="ml-2 text-text-secondary">{role.description}</span>
                  <span className="ml-2 text-text-secondary">· {role.peer_url}</span>
                  <span className="ml-2 text-text-secondary">· {role.enabled ? "已启用" : "已禁用"}</span>
                </span>
                <button
                  type="button"
                  onClick={() => void handleToggle(role)}
                  className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-sidebar"
                >
                  {role.enabled ? "禁用" : "启用"}
                </button>
                <button
                  type="button"
                  aria-label={`删除角色：${role.name}`}
                  onClick={() => setPendingDeleteId(role.id)}
                  className="text-text-secondary hover:text-red-500"
                >
                  <TrashIcon width={14} height={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <ConfirmDeleteRoleDialog
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
