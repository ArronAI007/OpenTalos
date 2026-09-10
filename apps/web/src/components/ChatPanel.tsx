import { useState, type FormEvent } from "react";
import type { ChatMessage } from "../types.js";

interface ChatPanelProps {
  messages: ChatMessage[];
  onSend: (text: string) => void;
  error?: string;
  disabled?: boolean;
}

export function ChatPanel({ messages, onSend, error, disabled }: ChatPanelProps) {
  const [draft, setDraft] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (disabled) return;
    const trimmed = draft.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setDraft("");
  }

  return (
    <section className="chat-panel" aria-label="对话">
      <ul className="message-list">
        {messages.map((message) => (
          <li key={message.id} className={`message message-${message.role}`}>
            {message.text}
          </li>
        ))}
      </ul>
      {error && <p className="chat-error">{error}</p>}
      <form className="chat-input-row" onSubmit={handleSubmit}>
        <input
          className="chat-input"
          placeholder="输入消息…"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          disabled={disabled}
        />
        <button className="chat-send" type="submit" disabled={disabled}>
          发送
        </button>
      </form>
    </section>
  );
}
