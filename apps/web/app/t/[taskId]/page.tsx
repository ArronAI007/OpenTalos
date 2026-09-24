"use client";

import { useEffect, use, useState } from "react";
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
  const { messages, busy, send, stop, deleteTurn } = useChat(taskId);
  // Composer 受控化：编辑操作把气泡内容回填进输入框；提交后清空由父负责（受控模式自清职责在父）。
  const [draft, setDraft] = useState("");
  // 回填后聚焦的触发计数：同一内容再次编辑也要重新聚焦，用 nonce 而非直接比对 draft
  const [focusNonce, setFocusNonce] = useState(0);

  // 首页首发消息交接：先取（取即删）再发，StrictMode 双跑 effect 时第二次 take 返回 null，
  // 不会重复发送。send 引用稳定（useCallback 仅依赖 taskId），列入 deps 满足 exhaustive-deps。
  useEffect(() => {
    const pending = takePendingMessage(taskId);
    if (pending) void send(pending);
  }, [taskId, send]);

  const handleSend = (text: string) => {
    setDraft(""); // 受控提交父层清空（与 HomeComposer 同一范式）
    void send(text);
  };

  const handleEditUser = (content: string) => {
    setDraft(content);
    setFocusNonce((n) => n + 1);
  };

  return (
    // 滚动容器（MessageList 的 ol）铺满整个内容区：鼠标在右侧区域任意处都能滚动对话。
    // 列宽约束下放到各消息行与 Composer 外壳，视觉与原先 max-w-3xl 居中完全一致。
    <section className="flex h-full flex-col">
      <MessageList
        messages={messages}
        taskId={taskId}
        busy={busy}
        onEditUser={handleEditUser}
        onDeleteTurn={(messageId) => void deleteTurn(messageId)}
      />
      <div className="mx-auto w-full max-w-3xl">
        <Composer
          onSend={handleSend}
          disabled={busy}
          onStop={stop}
          value={draft}
          onChange={setDraft}
          focusNonce={focusNonce}
        />
      </div>
    </section>
  );
}
