import { useEffect, useState } from "react";
import { createApiKey, listApiKeys, revokeApiKey } from "../api.js";
import type { ApiKeyRecord } from "../types.js";

interface ApiKeyPanelProps {
  tenantId: string;
}

export function ApiKeyPanel({ tenantId }: ApiKeyPanelProps) {
  const [keys, setKeys] = useState<ApiKeyRecord[]>([]);
  const [newRawKey, setNewRawKey] = useState<string>();

  async function refresh() {
    setKeys(await listApiKeys(tenantId));
  }

  useEffect(() => {
    void refresh();
  }, [tenantId]);

  async function handleCreate() {
    const { rawKey } = await createApiKey(tenantId);
    setNewRawKey(rawKey);
    await refresh();
  }

  async function handleRevoke(keyId: string) {
    await revokeApiKey(keyId);
    await refresh();
  }

  return (
    <div className="api-key-panel">
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
