import { useEffect, useState } from "react";
import { AdminAuthError, banUser, deleteUser, listUsers, unbanUser } from "../api.js";
import type { UserRecord } from "../types.js";

interface UserListProps {
  onAuthError: () => void;
}

const STATUS_LABEL: Record<UserRecord["status"], string> = {
  active: "正常",
  banned: "已封禁",
  deleted: "已删除",
};

export function UserList({ onAuthError }: UserListProps) {
  const [users, setUsers] = useState<UserRecord[]>([]);
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
      setUsers(await listUsers());
    } catch (err) {
      handleError(err);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function handleBanToggle(user: UserRecord) {
    setError(undefined);
    try {
      if (user.status === "active") {
        await banUser(user.id);
      } else if (user.status === "banned") {
        await unbanUser(user.id);
      }
      await refresh();
    } catch (err) {
      handleError(err);
    }
  }

  async function handleDelete(user: UserRecord) {
    setError(undefined);
    try {
      await deleteUser(user.id);
      await refresh();
    } catch (err) {
      handleError(err);
    }
  }

  return (
    <div>
      {error && <p className="error-banner">{error}</p>}
      <ul className="tenant-list">
        {users.map((user) => (
          <li key={user.id} className="tenant-row">
            <div className="tenant-row-header">
              <span>
                {user.username} <span className={`user-status-${user.status}`}>({STATUS_LABEL[user.status]})</span>
              </span>
              <span>注册于 {new Date(user.createdAt).toLocaleString()}</span>
            </div>
            {user.status !== "deleted" && (
              <div className="user-row-actions">
                <button className="danger-button" onClick={() => void handleBanToggle(user)}>
                  {user.status === "active" ? "封号" : "解封"}
                </button>
                <button className="danger-button" onClick={() => void handleDelete(user)}>
                  删除
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
