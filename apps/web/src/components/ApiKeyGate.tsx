import { useState, type FormEvent } from "react";
import { setApiKey } from "../api.js";

interface ApiKeyGateProps {
  onSubmit: () => void;
  error?: string;
}

export function ApiKeyGate({ onSubmit, error }: ApiKeyGateProps) {
  const [draft, setDraft] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim()) return;
    setApiKey(draft.trim());
    onSubmit();
  }

  return (
    <div className="gate-card">
      <p>请输入管理员为你分配的 API Key</p>
      {error && <p className="chat-error">{error}</p>}
      <form onSubmit={handleSubmit}>
        <input
          className="gate-input"
          type="password"
          placeholder="API Key"
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
