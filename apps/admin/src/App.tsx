import { useState } from "react";
import { getAdminKey } from "./api.js";
import { AdminKeyGate } from "./components/AdminKeyGate.js";
import { TenantList } from "./components/TenantList.js";
import "./styles/tokens.css";
import "./styles/app.css";

export function App() {
  const [hasKey, setHasKey] = useState(() => getAdminKey() !== null);

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
      </header>
      <TenantList onAuthError={handleAuthError} />
    </main>
  );
}
