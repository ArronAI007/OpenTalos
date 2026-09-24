"use client";

import { useLayoutEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { UiMessage } from "@/lib/chat-events";
import { isNearBottom, scrollToBottom } from "@/lib/scroll-stick";
import { LogoMark } from "@/components/sidebar/Logo";
import { CirclePauseIcon } from "@/components/ui/icons";
import { formatDateTimeCN } from "@/lib/format-time";
import { CopyReplyButton } from "./CopyReplyButton";
import { UserActionRow } from "./UserActionRow";

function ToolBubble({ message }: { message: Extract<UiMessage, { kind: "tool" }> }) {
  const argsPreview = Object.entries(message.arguments)
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(", ");
  return (
    <details className="mx-auto w-full max-w-xl rounded-lg border border-border bg-sidebar px-3 py-2 text-xs text-text-secondary">
      <summary className="cursor-pointer select-none">
        🔧 {message.name}({argsPreview})
        {message.ok !== undefined && (message.ok ? " ✓" : " ✗")}
      </summary>
      {message.result !== undefined && (
        <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap break-all">{message.result}</pre>
      )}
    </details>
  );
}

// 回复块品牌头：assistant 回复带；孤立的「已停止」提示（未流出内容即停）作为唯一可见块也带，
// 一轮问答里品牌头只出现一次（对齐 Manus“每个产出块带头”版式）
function BrandHeader() {
  return (
    <div className="mb-1 flex items-center gap-1.5">
      <LogoMark size={18} />
      <span className="text-sm font-semibold tracking-tight">OpenTalos</span>
    </div>
  );
}

// 消息行行壳：ol 已铺满内容区，列宽与内边距约束收回到行级（与原先 max-w-3xl + px-4 的几何等同）。
const rowCls = "mx-auto w-full max-w-3xl px-4";

export function MessageList({
  messages,
  taskId,
  busy,
  onEditUser,
  onDeleteTurn,
  onPickSuggestion,
}: {
  messages: UiMessage[];
  taskId: string;
  busy: boolean;
  onEditUser: (content: string) => void;
  onDeleteTurn: (messageId: string) => void;
  onPickSuggestion: (text: string) => void;
}) {
  const listRef = useRef<HTMLOListElement>(null);
  // 跟随滚动开关：初始 true（进入任务/历史加载后落在最新消息）；用户上翻超过阈值即停跟，回到底部恢复。
  const stickRef = useRef(true);
  const prevLenRef = useRef(0);

  // 绘制前纠位，避免流式 token 逐帧闪现错位。每条 delta 都产生新 messages 引用，在此统一兜底。
  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el) return;
    // 新出现的是用户消息 = 自己刚发送：无条件回到底部（即便之前在上翻阅读）。
    const appendedUser =
      messages.length > prevLenRef.current && messages[messages.length - 1]?.kind === "user";
    prevLenRef.current = messages.length;
    if (appendedUser) stickRef.current = true;
    if (stickRef.current) scrollToBottom(el);
  }, [messages]);

  return (
    <ol
      ref={listRef}
      onScroll={(e) => {
        stickRef.current = isNearBottom(e.currentTarget);
      }}
      className="flex flex-1 flex-col gap-3 overflow-y-auto py-6"
    >
      {messages.map((message, index) => {
        if (message.kind === "user") {
          return (
            <li key={message.id} className={`${rowCls} group`}>
              {/* 气泡底色与左侧栏同 token（--color-sidebar），文字用主前景色 */}
              <div className="ml-auto w-fit max-w-[75%] rounded-2xl bg-sidebar px-4 py-2 text-base text-text">
                {message.content}
              </div>
              {/* Manus 式操作行：相对时间 + 复制/分享/编辑/删除整轮，右对齐贴在气泡下方；
                  默认隐藏，仅 hover/键盘聚焦本行区域时显现（group 挂在整行 li 上） */}
              <UserActionRow
                content={message.content}
                completedAt={message.completedAt}
                taskId={taskId}
                busy={busy}
                onEdit={() => onEditUser(message.content)}
                onDelete={() => onDeleteTurn(message.id)}
              />
            </li>
          );
        }
        if (message.kind === "assistant") {
          // 紧跟其后的 stopped（本轮有内容流出后被停止）并入本回复块渲染，品牌头一轮只出现一次
          const followedByStopped = messages[index + 1]?.kind === "stopped";
          return (
            <li key={message.id} className={`${rowCls} group`}>
              <div className="max-w-[85%] text-base leading-6">
                {/* 每条回复带品牌头（流式与历史同等处理），对齐 Manus 版式 */}
                <BrandHeader />
                <div className="md">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                </div>
                {message.streaming && <span className="animate-pulse text-text-secondary">▍</span>}
                {/* 本轮被停止：停止提示并入本块收尾（品牌头不重复），复制/时间行照常保留 */}
                {followedByStopped && (
                  <div className="mt-1.5 flex items-center gap-2 text-amber-600">
                    <CirclePauseIcon />
                    OpenTalos已停止 — 发送消息以继续
                  </div>
                )}
                {/* 回复定稿（含被停止定稿与历史行）后提供复制与时间；流式中隐藏。
                    时间默认不可见：光标覆盖/键盘聚焦回复区域时显现，直接展示完整日期（与 UserActionRow 同一显隐范式） */}
                {!message.streaming && (
                  <div className="mt-1.5 flex items-center gap-2">
                    <CopyReplyButton content={message.content} />
                    {message.completedAt !== undefined && (
                      <time className="text-xs leading-6 text-text-secondary invisible opacity-0 transition-opacity group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100">
                        {formatDateTimeCN(message.completedAt)}
                      </time>
                    )}
                  </div>
                )}
              </div>
            </li>
          );
        }
        if (message.kind === "stopped") {
          // 紧跟 assistant（有内容流出后被停止）的提示已并入该回复块，这里不再单列；
          // 仅立即停止（尚无内容流出）的孤立提示自成一行——那时它是唯一可见的响应块，带头
          if (messages[index - 1]?.kind === "assistant") return null;
          return (
            <li key={message.id} className={rowCls}>
              <div className="max-w-[85%] text-base leading-6">
                <BrandHeader />
                <div className="flex items-center gap-2 text-amber-600">
                  <CirclePauseIcon />
                  OpenTalos已停止 — 发送消息以继续
                </div>
              </div>
            </li>
          );
        }
        if (message.kind === "suggestions") {
          // 跟进问题推荐：回复块的附属行（无品牌头——一轮只出现一次），点击条目直接发送，不回填输入框
          return (
            <li key={message.id} className={rowCls}>
              <div className="flex max-w-[85%] flex-col items-start gap-1.5">
                {message.items.map((item, index) => (
                  <button
                    key={`${index}-${item}`}
                    type="button"
                    disabled={busy}
                    onClick={() => onPickSuggestion(item)}
                    className="rounded-full border border-border px-3 py-1.5 text-left text-sm text-text-secondary transition-colors hover:bg-sidebar hover:text-text disabled:opacity-40"
                  >
                    {item}
                  </button>
                ))}
              </div>
            </li>
          );
        }
        if (message.kind === "tool") {
          return <li key={message.id} className={rowCls}><ToolBubble message={message} /></li>;
        }
        return (
          <li key={message.id} className={rowCls}>
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-base text-red-600">
              出错了：{message.content}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
