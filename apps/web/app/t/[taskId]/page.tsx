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
  const { messages, busy, send, stop } = useChat(taskId);

  // 首页首发消息交接：先取（取即删）再发，StrictMode 双跑 effect 时第二次 take 返回 null，
  // 不会重复发送。send 引用稳定（useCallback 仅依赖 taskId），列入 deps 满足 exhaustive-deps。
  useEffect(() => {
    const pending = takePendingMessage(taskId);
    if (pending) void send(pending);
  }, [taskId, send]);

  return (
    // 滚动容器（MessageList 的 ol）铺满整个内容区：鼠标在右侧区域任意处都能滚动对话。
    // 列宽约束下放到各消息行与 Composer 外壳，视觉与原先 max-w-3xl 居中完全一致。
    <section className="flex h-full flex-col">
      <MessageList messages={messages} />
      <div className="mx-auto w-full max-w-3xl">
        <Composer onSend={send} disabled={busy} onStop={stop} />
      </div>
    </section>
  );
}
