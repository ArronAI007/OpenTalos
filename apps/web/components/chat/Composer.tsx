"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { shouldSubmitOnEnter } from "@/lib/composer-keys";

// 输入框自增高上限：约 6 行（text-base / leading-6），超出后框内滚动
const MAX_TEXTAREA_HEIGHT_PX = 160;

export function Composer({
  onSend,
  disabled,
  onStop,
  value: controlledValue,
  onChange,
  focusNonce,
}: {
  onSend: (text: string) => void;
  disabled: boolean;
  // 流式进行中可中断（busy 时发送按钮变 ■）；首页建任务不可中断，不传
  onStop?: () => void;
  value?: string;
  onChange?: (value: string) => void;
  // 外部触发聚焦的 nonce：编辑回填相同内容也要重新聚焦，所以用计数而非布尔/字符串
  focusNonce?: number;
}) {
  const [internalValue, setInternalValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isControlled = onChange !== undefined;
  const value = isControlled ? (controlledValue ?? "") : internalValue;
  const setValue = isControlled ? onChange : setInternalValue;

  // focusNonce 变化时聚焦并把光标挪到末尾（编辑回填场景：文本已就位，缺少的是焦点）
  useEffect(() => {
    if (focusNonce === undefined || focusNonce === 0) return;
    const el = textareaRef.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, [focusNonce]);

  // 高度随内容自适应：先归 auto 让 scrollHeight 反映真实内容高，再夹到上限。
  // 挂在 [value] 上而非 onChange：受控/非受控（含提交后清空草稿）都能触发，空值自动缩回单行。
  // useLayoutEffect 在绘制前纠高，输入长文本逐键无跳动。
  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT_PX)}px`;
  }, [value]);

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
      className="p-4"
      onSubmit={(event) => { event.preventDefault(); submit(); }}
    >
      <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-composer border border-border bg-white px-4 py-2">
        <textarea
          ref={textareaRef}
          rows={1}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (!shouldSubmitOnEnter({
              key: event.key,
              shiftKey: event.shiftKey,
              isComposing: event.nativeEvent.isComposing, // IME 候选窗激活时 Enter 仅选词（属性在原生事件上）
            })) return;
            event.preventDefault(); // 阻止换行插入，走发送
            submit();
          }}
          disabled={disabled}
          placeholder="给 OpenTalos 发任务…"
          className="max-h-40 flex-1 resize-none overflow-y-auto bg-transparent text-base leading-6 outline-none disabled:opacity-50"
          aria-label="输入消息"
        />
        {disabled && onStop ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="停止生成"
            className="rounded-full bg-user-bubble px-3 py-1.5 text-sm text-white"
          >
            ■
          </button>
        ) : (
          <button
            type="submit"
            disabled={disabled || !value.trim()}
            className="rounded-full bg-user-bubble px-3 py-1.5 text-sm text-white disabled:opacity-30"
          >
            ➤
          </button>
        )}
      </div>
    </form>
  );
}
