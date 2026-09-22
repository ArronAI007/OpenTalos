"use client";

import { useState } from "react";

export function Composer({ onSend, disabled }: { onSend: (text: string) => void; disabled: boolean }) {
  const [value, setValue] = useState("");

  const submit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    setValue("");
    onSend(text);
  };

  return (
    <form
      className="border-t border-border p-4"
      onSubmit={(event) => { event.preventDefault(); submit(); }}
    >
      <div className="mx-auto flex max-w-3xl items-center gap-2 rounded-composer border border-border bg-white px-4 py-2">
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          disabled={disabled}
          placeholder="给 OpenTalos 发任务…"
          className="flex-1 bg-transparent text-sm outline-none disabled:opacity-50"
          aria-label="输入消息"
        />
        <button
          type="submit"
          disabled={disabled || !value.trim()}
          className="rounded-full bg-user-bubble px-3 py-1.5 text-sm text-white disabled:opacity-30"
        >
          ➤
        </button>
      </div>
    </form>
  );
}
