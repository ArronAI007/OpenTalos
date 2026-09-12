import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { ChatMessage } from "../types.js";

interface ChatPanelProps {
  messages: ChatMessage[];
  onSend: (text: string) => void;
  error?: string;
  disabled?: boolean;
  /** The assistant's reply so far, while it's still streaming in. Rendered as a trailing bubble
   * after `messages` until the real ChatMessage is appended once the run finishes. */
  streamingText?: string;
}

export function ChatPanel({ messages, onSend, error, disabled, streamingText }: ChatPanelProps) {
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLLIElement>(null);

  // message-list scrolls independently of the page now (app.css pins the composer below it), so
  // without this a new message or an in-progress stream would land below the visible fold instead
  // of the composer following it down.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, streamingText]);

  function submit() {
    if (disabled) return;
    const trimmed = draft.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setDraft("");
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    submit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <section className="chat-panel" aria-label="对话">
      {messages.length === 0 && !streamingText ? (
        <div className="chat-empty">
          <p className="chat-empty-title">开始对话</p>
          <p className="chat-empty-subtitle">在下方输入框输入消息开始对话</p>
        </div>
      ) : (
        <ul className="message-list">
          {messages.map((message) => (
            <li key={message.id} className={`message message-${message.role}`}>
              {message.text}
            </li>
          ))}
          {streamingText && (
            <li className="message message-assistant message-streaming">
              {streamingText}
              <span className="streaming-cursor" aria-hidden="true" />
            </li>
          )}
          <li ref={bottomRef} className="message-list-end" aria-hidden="true" />
        </ul>
      )}
      {error && <p className="chat-error">{error}</p>}
      <form className="composer" onSubmit={handleSubmit}>
        <textarea
          className="composer-input"
          placeholder="给智能体发消息"
          rows={1}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
        />
        <div className="composer-toolbar">
          <button className="composer-send" type="submit" disabled={disabled || !draft.trim()} aria-label="发送">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden="true">
              <path
                d="M3 11.5L20.5 3.5L14.5 21L11 13L3 11.5Z"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>
      </form>
      <p className="composer-status">{disabled ? "运行中…" : "准备就绪"}</p>
    </section>
  );
}
