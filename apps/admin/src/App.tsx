import { useState } from "react";
import { getAdminKey } from "./api.js";
import { AdminKeyGate } from "./components/AdminKeyGate.js";
import { TenantList } from "./components/TenantList.js";
import { UserList } from "./components/UserList.js";
import "./styles/tokens.css";
import "./styles/app.css";

type View = "tenants" | "users";

export function App() {
  const [hasKey, setHasKey] = useState(() => getAdminKey() !== null);
  const [view, setView] = useState<View>("tenants");

  function handleAuthError() {
    setHasKey(false);
  }

  if (!hasKey) {
    return (
      <main className="admin-shell">
        <AdminKeyGate onSubmit={() => setHasKey(true)} />
      </main>
    );
  }

  return (
    <main className="admin-shell">
      <header className="admin-header">
        <span className="admin-title">OpenTalos · 平台管理</span>
        <nav className="admin-nav">
          <button
            type="button"
            className={view === "tenants" ? "admin-nav-tab admin-nav-tab-active" : "admin-nav-tab"}
            onClick={() => setView("tenants")}
          >
            租户
          </button>
          <button
            type="button"
            className={view === "users" ? "admin-nav-tab admin-nav-tab-active" : "admin-nav-tab"}
            onClick={() => setView("users")}
          >
            用户
          </button>
        </nav>
      </header>
      {view === "tenants" ? <TenantList onAuthError={handleAuthError} /> : <UserList onAuthError={handleAuthError} />}
    </main>
  );
}
