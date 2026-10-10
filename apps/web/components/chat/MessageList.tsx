"use client";

import { useLayoutEffect, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { UiMessage } from "@/lib/chat-events";
import { shouldShowThinkingHint, visibleIndexes } from "@/lib/chat-events";
import { humanizeToolCall } from "@/lib/humanize";
import { isNearBottom } from "@/lib/scroll-stick";
import { LogoMark } from "@/components/sidebar/Logo";
import { CirclePauseIcon } from "@/components/ui/icons";
import { formatDateTimeCN } from "@/lib/format-time";
import { formatUsage } from "@/lib/usage";
import { CopyReplyButton } from "./CopyReplyButton";
import { ThinkingBubble, type ThinkingItem } from "./ThinkingBubble";
import { UserActionRow } from "./UserActionRow";

// 从 start 起收集连续的 reasoning/tool —— 一个"思考过程"单元（自然语言思路 + 其中的工具动作）。
function thinkingRunFrom(messages: UiMessage[], start: number): { items: ThinkingItem[]; end: number } {
  const items: ThinkingItem[] = [];
  let i = start;
  while (i < messages.length && (messages[i].kind === "reasoning" || messages[i].kind === "tool")) {
    items.push(messages[i] as ThinkingItem);
    i++;
  }
  return { items, end: i };
}

// 思考单元是否仍在进行：有流式思维链/未返回的工具，或它位于列表末尾且整轮仍 busy。
function isThinkingStreaming(items: ThinkingItem[], busy: boolean, isLast: boolean): boolean {
  if (items.some((m) => (m.kind === "reasoning" && m.streaming) || (m.kind === "tool" && m.result === undefined))) {
    return true;
  }
  return busy && isLast;
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

// 消息行行壳：列宽与内边距约束收回到行级（与原先 max-w-3xl + px-4 的几何等同）。
const rowCls = "mx-auto w-full max-w-3xl px-4";

export function MessageList({
  messages,
  taskId,
  busy,
  onEditUser,
  onDeleteTurn,
  onPickSuggestion,
  onApproval,
  onRegenerate,
}: {
  messages: UiMessage[];
  taskId: string;
  busy: boolean;
  onEditUser: (content: string) => void;
  onDeleteTurn: (messageId: string) => void;
  onPickSuggestion: (text: string) => void;
  onApproval: (approvalId: string, approved: boolean) => void;
  onRegenerate: (messageId: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  // 跟随滚动开关：初始 true（进入任务/历史加载后落在最新消息）；用户上翻超过阈值即停跟，回到底部恢复。
  const stickRef = useRef(true);
  const prevLenRef = useRef(0);

  const rows = visibleIndexes(messages);
  const showHint = shouldShowThinkingHint(messages, busy);
  const count = rows.length + (showHint ? 1 : 0);

  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Virtual 官方 API 与 React Compiler 自动记忆化不兼容（本项目未启用 Compiler）
  const virtualizer = useVirtualizer({
    count,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 120, // 粗估；measureElement 实测后会纠正
    overscan: 8,
    getItemKey: (index) => (index < rows.length ? messages[rows[index]].id : "__thinking__"),
  });

  // 绘制前纠位：新内容（尤其流式 delta）后把视图顶到底。新出现的是用户消息 = 自己刚发送，
  // 无条件回到底部（即便之前在上翻阅读）；否则仅在"跟随"开启时贴底，不打断用户上翻。
  useLayoutEffect(() => {
    const appendedUser =
      messages.length > prevLenRef.current && messages[messages.length - 1]?.kind === "user";
    prevLenRef.current = messages.length;
    if (appendedUser) stickRef.current = true;
    if (stickRef.current && count > 0) {
      virtualizer.scrollToIndex(count - 1, { align: "end" });
    }
  }, [messages, count, virtualizer]);

  const renderItem = (message: UiMessage, index: number) => {
    if (message.kind === "user") {
      return (
        <div className={`${rowCls} group`}>
          {/* 气泡底色与左侧栏同 token（--color-sidebar），文字用主前景色 */}
          <div className="ml-auto w-fit max-w-[75%] rounded-2xl bg-sidebar px-4 py-2 text-base text-text">
            {message.content}
          </div>
          {/* Manus 式操作行：相对时间 + 复制/分享/编辑/删除整轮，右对齐贴在气泡下方；
              默认隐藏，仅 hover/键盘聚焦本行区域时显现（group 挂在整行上） */}
          <UserActionRow
            content={message.content}
            completedAt={message.completedAt}
            taskId={taskId}
            busy={busy}
            onEdit={() => onEditUser(message.content)}
            onDelete={() => onDeleteTurn(message.id)}
          />
        </div>
      );
    }
    if (message.kind === "assistant") {
      // 紧跟其后的 stopped（本轮有内容流出后被停止）并入本回复块渲染，品牌头一轮只出现一次
      const followedByStopped = messages[index + 1]?.kind === "stopped";
      // 紧邻本回复块之前的整段"思考单元"（reasoning/tool 连续段）并入本块，品牌头之后、正文之前统一渲染
      let thinkingStart = index;
      while (
        thinkingStart > 0 &&
        (messages[thinkingStart - 1].kind === "reasoning" || messages[thinkingStart - 1].kind === "tool")
      ) {
        thinkingStart--;
      }
      const thinking = messages.slice(thinkingStart, index) as ThinkingItem[];
      const thinkingStreaming = thinking.some(
        (m) => (m.kind === "reasoning" && m.streaming) || (m.kind === "tool" && m.result === undefined),
      );
      return (
        <div className={`${rowCls} group`}>
          <div className="max-w-[85%] text-base leading-6">
            {/* 每条回复带品牌头（流式与历史同等处理），对齐 Manus 版式 */}
            <BrandHeader />
            {thinking.length > 0 && <ThinkingBubble items={thinking} streaming={thinkingStreaming} />}
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
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onRegenerate(message.id)}
                  className="rounded px-1.5 py-1 text-xs text-text-secondary transition-colors hover:bg-sidebar hover:text-text disabled:opacity-40"
                >
                  重新生成
                </button>
                {message.completedAt !== undefined && (
                  <time className="text-xs leading-6 text-text-secondary invisible opacity-0 transition-opacity group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100">
                    {formatDateTimeCN(message.completedAt)}
                  </time>
                )}
                {formatUsage(message.usage) && (
                  <span className="text-xs leading-6 text-text-secondary">{formatUsage(message.usage)}</span>
                )}
              </div>
            )}
          </div>
        </div>
      );
    }
    if (message.kind === "reasoning" || message.kind === "tool") {
      // 同一思考单元只渲染一次（起始行）；可见集合已保证这里只会拿到单元起始行
      const run = thinkingRunFrom(messages, index);
      // 孤立的思考单元（思考中被停止、正文尚未流出）自成一行——此时它是本轮唯一可见的响应块，
      // 带头（与孤立 stopped 同处理），紧跟的停止提示也并入本块收尾，品牌头仍只出现一次
      const followedByStopped = run.end < messages.length && messages[run.end].kind === "stopped";
      const streaming = isThinkingStreaming(run.items, busy, run.end >= messages.length);
      return (
        <div className={rowCls}>
          <div className="max-w-[85%] text-base leading-6">
            <BrandHeader />
            <ThinkingBubble items={run.items} streaming={streaming} />
            {followedByStopped && (
              <div className="mt-1.5 flex items-center gap-2 text-amber-600">
                <CirclePauseIcon />
                OpenTalos已停止 — 发送消息以继续
              </div>
            )}
          </div>
        </div>
      );
    }
    if (message.kind === "stopped") {
      // 仅立即停止（毫无内容流出）的孤立提示自成一行——那时它是唯一可见的响应块，带头
      return (
        <div className={rowCls}>
          <div className="max-w-[85%] text-base leading-6">
            <BrandHeader />
            <div className="flex items-center gap-2 text-amber-600">
              <CirclePauseIcon />
              OpenTalos已停止 — 发送消息以继续
            </div>
          </div>
        </div>
      );
    }
    if (message.kind === "suggestions") {
      // 跟进问题推荐：回复块的附属行（无品牌头——一轮只出现一次），点击条目直接发送，不回填输入框
      return (
        <div className={rowCls}>
          <div className="flex max-w-[85%] flex-col items-start gap-1.5">
            {message.items.map((item, itemIndex) => (
              <button
                key={`${itemIndex}-${item}`}
                type="button"
                disabled={busy}
                onClick={() => onPickSuggestion(item)}
                className="rounded-full border border-border px-3 py-1.5 text-left text-sm text-text-secondary transition-colors hover:bg-sidebar hover:text-text disabled:opacity-40"
              >
                {item}
              </button>
            ))}
          </div>
        </div>
      );
    }
    if (message.kind === "approval") {
      // 副作用工具的人工确认卡片：pending 时两个按钮，resolve 后转为结果文案。
      const { label, detail } = humanizeToolCall(message.name, message.arguments);
      return (
        <div className={rowCls}>
          <div className="mx-auto w-full max-w-xl rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            <div className="flex items-baseline gap-1.5">
              <span aria-hidden>⚠️</span>
              <span className="font-medium">需要确认：{label}</span>
              {detail && <span className="truncate text-amber-700">：{detail}</span>}
            </div>
            {message.status === "pending" ? (
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  onClick={() => onApproval(message.approvalId, true)}
                  className="rounded-full bg-amber-600 px-3 py-1 text-xs font-medium text-white hover:bg-amber-700"
                >
                  允许
                </button>
                <button
                  type="button"
                  onClick={() => onApproval(message.approvalId, false)}
                  className="rounded-full border border-amber-400 px-3 py-1 text-xs font-medium text-amber-800 hover:bg-amber-100"
                >
                  拒绝
                </button>
              </div>
            ) : (
              <div className="mt-1 text-xs text-amber-700">
                {message.status === "approved" ? "已允许" : "已拒绝"}
              </div>
            )}
          </div>
        </div>
      );
    }
    return (
      <div className={rowCls}>
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-base text-red-600">
          出错了：{message.content}
        </div>
      </div>
    );
  };

  const renderHint = () => (
    <div className={rowCls}>
      <div className="max-w-[85%] text-base leading-6">
        <BrandHeader />
        <div className="flex items-center gap-2 text-sm text-text-secondary">
          <span className="flex items-center gap-1" aria-hidden>
            {[0, 150, 300].map((ms) => (
              <span
                key={ms}
                className="h-1.5 w-1.5 animate-bounce rounded-full bg-text-secondary"
                style={{ animationDelay: `${ms}ms` }}
              />
            ))}
          </span>
          正在思考…
        </div>
      </div>
    </div>
  );

  return (
    <div
      ref={scrollRef}
      data-message-scroll
      onScroll={(e) => {
        stickRef.current = isNearBottom(e.currentTarget);
      }}
      className="relative flex-1 overflow-y-auto py-6"
    >
      <div style={{ height: virtualizer.getTotalSize(), width: "100%", position: "relative" }}>
        {virtualizer.getVirtualItems().map((item) => (
          <div
            key={item.key}
            data-index={item.index}
            ref={virtualizer.measureElement}
            style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${item.start}px)` }}
          >
            {item.index < rows.length ? renderItem(messages[rows[item.index]], rows[item.index]) : renderHint()}
          </div>
        ))}
      </div>
    </div>
  );
}
