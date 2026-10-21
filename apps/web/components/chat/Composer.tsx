"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { shouldSubmitOnEnter } from "@/lib/composer-keys";
import { detectMentionQuery, stripMention, type MentionQuery } from "@/lib/agent-mention";

// 输入框自增高上限：约 6 行（text-base / leading-6），超出后框内滚动
const MAX_TEXTAREA_HEIGHT_PX = 160;

export interface AgentOption {
  id: string;
  name: string;
}

export function Composer({
  onSend,
  disabled,
  onStop,
  value: controlledValue,
  onChange,
  focusNonce,
  agent,
  agents = [],
  onSelectAgent,
}: {
  onSend: (text: string) => void;
  disabled: boolean;
  // 流式进行中可中断（busy 时发送按钮变 ■）；首页建任务不可中断，不传
  onStop?: () => void;
  value?: string;
  onChange?: (value: string) => void;
  // 外部触发聚焦的 nonce：编辑回填相同内容也要重新聚焦，所以用计数而非布尔/字符串
  focusNonce?: number;
  // 当前对话绑定的自建 Agent（null/未传 = 默认 Agent）；左侧显示可移除的 @ 标签
  agent?: AgentOption | null;
  // 可 @ 选中的自建 Agent 列表（通常是「我的 Agent」）
  agents?: AgentOption[];
  // 选中/移除 Agent 的回调；不传则不展示 @ 选择器（只读展示 agent 标签）
  onSelectAgent?: (agent: AgentOption | null) => void;
}) {
  const [internalValue, setInternalValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pickerRef = useRef<HTMLDivElement>(null);
  // 正在输入中的 @ 查询；null = 不展示候选列表
  const [mention, setMention] = useState<MentionQuery | null>(null);
  const [highlight, setHighlight] = useState(0);
  const isControlled = onChange !== undefined;
  const value = isControlled ? (controlledValue ?? "") : internalValue;
  const setValue = isControlled ? onChange : setInternalValue;
  // 运行中（disabled 且有 onStop）：允许继续输入并以"纠偏"语义提交。
  const steering = disabled && onStop !== undefined;
  // 运行中不允许换绑 Agent：后端换绑要逐出缓存的 Agent，不能在流进行中做。
  const canPick = onSelectAgent !== undefined && agents.length > 0 && !disabled;

  const query = mention?.query ?? "";
  const filtered = canPick
    ? agents.filter((a) => a.name.toLowerCase().includes(query.toLowerCase()))
    : [];
  const pickerOpen = mention !== null && filtered.length > 0;
  const activeIndex = pickerOpen ? Math.min(highlight, filtered.length - 1) : -1;

  // focusNonce 变化时聚焦并把光标挪到末尾（编辑回填场景：文本已就位，缺少的是焦点）
  useEffect(() => {
    if (focusNonce === undefined || focusNonce === 0) return;
    const el = textareaRef.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, [focusNonce]);

  // 点击选择器之外或 Esc 关闭候选列表。
  useEffect(() => {
    if (!pickerOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!pickerRef.current?.contains(e.target as Node)) setMention(null);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [pickerOpen]);

  // 进入 busy 时候选列表自然收起：canPick 含 !disabled，filtered 变空、pickerOpen 为 false。
  // 提交/选中都会 closePicker，mention 不会残留；无需额外 effect 同步。

  // 高度随内容自适应：先归 auto 让 scrollHeight 反映真实内容高，再夹到上限。
  // 挂在 [value] 上而非 onChange：受控/非受控（含提交后清空草稿）都能触发，空值自动缩回单行。
  // useLayoutEffect 在绘制前纠高，输入长文本逐键无跳动。
  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT_PX)}px`;
  }, [value]);

  const closePicker = () => setMention(null);

  // 把输入框内已键入的 `@query` 片段剔除，并回填 Agent 绑定标签；光标落回剔除处。
  const handlePick = (next: AgentOption) => {
    const el = textareaRef.current;
    const cursor = el?.selectionStart ?? value.length;
    if (mention) {
      const result = stripMention(value, cursor, mention.start);
      setValue(result.value);
      requestAnimationFrame(() => el?.setSelectionRange(result.cursor, result.cursor));
    }
    onSelectAgent?.(next);
    closePicker();
  };

  const submit = () => {
    const text = value.trim();
    if (!text) return;
    // disabled 且不可中断（如首页建任务 busy、无 onStop）时不允许提交；
    // disabled 且有 onStop（任务页运行中）= steering：允许提交。
    if (disabled && !steering) return;
    // 受控模式由父组件（HomeComposer）决定何时清空，失败时才能保留草稿；
    // 非受控模式保持"提交即清空"的原有行为（任务页复用）。
    if (!isControlled) setValue("");
    closePicker();
    onSend(text);
  };

  return (
    <form
      className="relative p-4"
      onSubmit={(event) => { event.preventDefault(); submit(); }}
    >
      <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-composer border border-border bg-surface px-4 py-2">
        {agent ? (
          <span
            title={`当前 Agent：${agent.name}`}
            className="mb-0.5 flex max-w-[12rem] shrink-0 items-center gap-1 rounded-full bg-sidebar px-2.5 py-1 text-xs font-medium"
          >
            <span className="truncate">@{agent.name}</span>
            {onSelectAgent && (
              <button
                type="button"
                disabled={disabled}
                aria-label={`移除智能体 ${agent.name}`}
                title="移除智能体"
                onClick={() => onSelectAgent(null)}
                className="shrink-0 rounded-full px-0.5 text-sm leading-none text-text-secondary hover:text-text disabled:opacity-40"
              >
                ×
              </button>
            )}
          </span>
        ) : null}
        <textarea
          ref={textareaRef}
          rows={1}
          value={value}
          onChange={(event) => {
            const el = event.target;
            setValue(el.value);
            if (canPick) {
              setMention(detectMentionQuery(el.value, el.selectionStart ?? el.value.length));
              setHighlight(0);
            }
          }}
          onKeyDown={(event) => {
            if (pickerOpen) {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setHighlight((i) => (i + 1) % filtered.length);
                return;
              }
              if (event.key === "ArrowUp") {
                event.preventDefault();
                setHighlight((i) => (i - 1 + filtered.length) % filtered.length);
                return;
              }
              if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                event.preventDefault(); // 选中候选，不提交消息
                handlePick(filtered[activeIndex]);
                return;
              }
              if (event.key === "Escape") {
                event.preventDefault();
                closePicker();
                return;
              }
            }
            if (!shouldSubmitOnEnter({
              key: event.key,
              shiftKey: event.shiftKey,
              isComposing: event.nativeEvent.isComposing, // IME 候选窗激活时 Enter 仅选词（属性在原生事件上）
            })) return;
            event.preventDefault(); // 阻止换行插入，走发送
            submit();
          }}
          disabled={disabled && !steering}
          placeholder={steering ? "补充指令以纠偏…" : `给 ${agent?.name ?? "OpenTalos"} 发任务…`}
          className="max-h-40 flex-1 resize-none overflow-y-auto bg-transparent text-base leading-6 outline-none disabled:opacity-50"
          aria-label="输入消息"
        />
        {steering && !value.trim() ? (
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
            disabled={!value.trim() || (disabled && !steering)}
            aria-label={steering ? "发送纠偏" : "发送"}
            className="rounded-full bg-user-bubble px-3 py-1.5 text-sm text-white disabled:opacity-30"
          >
            ➤
          </button>
        )}
      </div>
      {pickerOpen && (
        <div
          ref={pickerRef}
          role="listbox"
          aria-label="选择智能体"
          className="absolute bottom-full left-1/2 z-20 mb-1 w-full max-w-3xl -translate-x-1/2 px-4"
        >
          <ul className="max-h-60 overflow-y-auto rounded-xl border border-border bg-surface p-1 shadow-lg">
            {filtered.map((option, index) => (
              <li key={option.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={index === activeIndex}
                  onMouseDown={(e) => e.preventDefault()} // 保持 textarea 焦点，避免 blur 先于 click 关闭列表
                  onMouseEnter={() => setHighlight(index)}
                  onClick={() => handlePick(option)}
                  className={`w-full truncate rounded-md px-3 py-2 text-left text-sm ${
                    index === activeIndex ? "bg-sidebar" : "hover:bg-sidebar"
                  }`}
                >
                  @{option.name}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </form>
  );
}
