"use client";

import { useEffect, use } from "react";
import { MessageList } from "@/components/chat/MessageList";
import { Composer } from "@/components/chat/Composer";
import { takePendingMessage } from "@/lib/pending-message";
import { useChat } from "@/lib/use-chat";

export default function TaskPage({ params }: { params: Promise<{ taskId: string }> }) {
  const { taskId } = use(params);
  // key=taskId：切换任务时整棵子树重挂载，旧任务的 busy/messages/流闭包随卸载废弃，
  // 杜绝跨任务事件串台与历史覆盖竞态（A 的流仍在后台跑到结束——Phase 1 接受的取舍）。
  return <TaskChat key={taskId} taskId={taskId} />;
}

function TaskChat({ taskId }: { taskId: string }) {
  const { messages, busy, send } = useChat(taskId);

  // 首页首发消息交接：先取（取即删）再发，StrictMode 双跑 effect 时第二次 take 返回 null，
  // 不会重复发送。send 引用稳定（useCallback 仅依赖 taskId），列入 deps 满足 exhaustive-deps。
  useEffect(() => {
    const pending = takePendingMessage(taskId);
    if (pending) void send(pending);
  }, [taskId, send]);

  return (
    <section className="mx-auto flex h-full max-w-3xl flex-col">
      <MessageList messages={messages} />
      <Composer onSend={send} disabled={busy} />
    </section>
  );
}
