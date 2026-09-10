import { useState, type FormEvent } from "react";
import { setAdminKey } from "../api.js";

interface AdminKeyGateProps {
  onSubmit: () => void;
}

export function AdminKeyGate({ onSubmit }: AdminKeyGateProps) {
  const [draft, setDraft] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim()) return;
    setAdminKey(draft.trim());
    onSubmit();
  }

  return (
    <div className="gate-card">
      <p>请输入管理员密钥（ADMIN_API_KEY）</p>
      <form onSubmit={handleSubmit}>
        <input
          className="gate-input"
          type="password"
          placeholder="管理员密钥"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button className="gate-button" type="submit">
          进入
        </button>
      </form>
    </div>
  );
}
