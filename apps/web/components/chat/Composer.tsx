"use client";

import { useState } from "react";

export function Composer({
  onSend,
  disabled,
  value: controlledValue,
  onChange,
}: {
  onSend: (text: string) => void;
  disabled: boolean;
  value?: string;
  onChange?: (value: string) => void;
}) {
  const [internalValue, setInternalValue] = useState("");
  const isControlled = onChange !== undefined;
  const value = isControlled ? (controlledValue ?? "") : internalValue;
  const setValue = isControlled ? onChange : setInternalValue;

  const submit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    // 受控模式由父组件（HomeComposer）决定何时清空，失败时才能保留草稿；
    // 非受控模式保持“提交即清空”的原有行为（任务页复用）。
    if (!isControlled) setValue("");
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
