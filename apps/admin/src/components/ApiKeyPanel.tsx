import { useEffect, useState } from "react";
import { AdminAuthError, createApiKey, listApiKeys, revokeApiKey } from "../api.js";
import type { ApiKeyRecord } from "../types.js";

interface ApiKeyPanelProps {
  tenantId: string;
  onAuthError: () => void;
}

export function ApiKeyPanel({ tenantId, onAuthError }: ApiKeyPanelProps) {
  const [keys, setKeys] = useState<ApiKeyRecord[]>([]);
  const [newRawKey, setNewRawKey] = useState<string>();
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
      setKeys(await listApiKeys(tenantId));
    } catch (err) {
      handleError(err);
    }
  }

  useEffect(() => {
    void refresh();
  }, [tenantId]);

  async function handleCreate() {
    setError(undefined);
    try {
      const { rawKey } = await createApiKey(tenantId);
      setNewRawKey(rawKey);
      await refresh();
    } catch (err) {
      handleError(err);
    }
  }

  async function handleRevoke(keyId: string) {
    setError(undefined);
    try {
      await revokeApiKey(keyId);
      await refresh();
    } catch (err) {
      handleError(err);
    }
  }

  return (
    <div className="api-key-panel">
      {error && <p className="error-banner">{error}</p>}
      <button className="primary-button" onClick={handleCreate}>
        + 新建 API Key
      </button>
      {newRawKey && (
        <div className="new-key-reveal">
          <strong>请立即复制，离开此页面后将无法再次查看：</strong>
          <div>{newRawKey}</div>
        </div>
      )}
      <ul className="tenant-list">
        {keys.map((key) => (
          <li key={key.id} className="tenant-row">
            <div className="tenant-row-header">
              <span>
                {key.keyPrefix}… ({key.status})
              </span>
              {key.status === "active" && (
                <button className="danger-button" onClick={() => handleRevoke(key.id)}>
                  吊销
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
