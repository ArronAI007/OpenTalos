import { useEffect, useState, type FormEvent } from "react";
import { AdminAuthError, createTenant, listTenants, updateTenant } from "../api.js";
import type { TenantRecord } from "../types.js";
import { ApiKeyPanel } from "./ApiKeyPanel.js";

interface TenantListProps {
  onAuthError: () => void;
}

export function TenantList({ onAuthError }: TenantListProps) {
  const [tenants, setTenants] = useState<TenantRecord[]>([]);
  const [expandedId, setExpandedId] = useState<string>();
  const [newName, setNewName] = useState("");
  const [newQuota, setNewQuota] = useState("");
  const [error, setError] = useState<string>();

  function handleError(err: unknown) {
    if (err instanceof AdminAuthError) {
      onAuthError();
      return;
    }
    setError(err instanceof Error ? err.message : "操作失败，请重试");
  }

  async function refresh() {
    try {
      setTenants(await listTenants());
    } catch (err) {
      handleError(err);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!newName.trim()) return;
    const maxConcurrency = newQuota.trim() ? Number(newQuota) : undefined;
    setError(undefined);
    try {
      await createTenant(newName.trim(), maxConcurrency);
      setNewName("");
      setNewQuota("");
      await refresh();
    } catch (err) {
      handleError(err);
    }
  }

  async function handleToggleStatus(tenant: TenantRecord) {
    setError(undefined);
    try {
      await updateTenant(tenant.id, { status: tenant.status === "active" ? "disabled" : "active" });
      await refresh();
    } catch (err) {
      handleError(err);
    }
  }

  return (
    <div>
      {error && <p className="error-banner">{error}</p>}
      <form className="create-tenant-form" onSubmit={handleCreate}>
        <input placeholder="租户名称" value={newName} onChange={(event) => setNewName(event.target.value)} />
        <input
          placeholder="并发配额（可留空）"
          value={newQuota}
          onChange={(event) => setNewQuota(event.target.value)}
        />
        <button className="primary-button" type="submit">
          创建租户
        </button>
      </form>
      <ul className="tenant-list">
        {tenants.map((tenant) => (
          <li key={tenant.id}>
            <button className="tenant-row" onClick={() => setExpandedId(expandedId === tenant.id ? undefined : tenant.id)}>
              <div className="tenant-row-header">
                <span>
                  {tenant.name}{" "}
                  {tenant.status === "disabled" && <span className="tenant-status-disabled">(已禁用)</span>}
                </span>
                <span>配额：{tenant.maxConcurrency ?? "默认"}</span>
              </div>
            </button>
            {expandedId === tenant.id && (
              <div>
                <button
                  className="danger-button"
                  onClick={(event) => {
                    event.stopPropagation();
                    void handleToggleStatus(tenant);
                  }}
                >
                  {tenant.status === "active" ? "禁用此租户" : "启用此租户"}
                </button>
                <ApiKeyPanel tenantId={tenant.id} onAuthError={onAuthError} />
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
