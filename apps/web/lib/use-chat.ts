"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, deleteTurn as deleteTurnApi, listMessages, respondToApproval as respondToApprovalApi, steerTask, type StoredMessage } from "./api";
import {
  appendStoppedNotice,
  denyPendingApprovals,
  dropStoppedNotice,
  dropSuggestions,
  dropTurn,
  finalizeStreaming,
  nextUiId,
  reduceChatEvent,
  turnUserMessage,
  type ChatEvent,
  type UiMessage,
} from "./chat-events";
import { getSse, postSse, type SseHandler } from "./sse";
import { emitTaskTitleUpdated } from "./task-events";

function fromStored(row: StoredMessage): UiMessage {
  // 服务端断连兜底落的 stopped 标记行 → 渲染为"已停止 — 发送消息以继续"提示
  if (row.kind === "stopped") {
    return { id: `row-${row.id}`, kind: "stopped" };
  }
  if (row.kind === "tool") {
    const parsed = JSON.parse(row.content) as { name: string; arguments: Record<string, unknown>; result: string; ok: boolean };
    return { id: `row-${row.id}`, kind: "tool", ...parsed };
  }
  if (row.kind === "user" || row.kind === "assistant") {
    // 服务端 created_at 为无时区后缀的本地 ISO：Date.parse 按本地时区解析，与后端同机一致
    return { id: `row-${row.id}`, kind: row.kind, content: row.content, completedAt: Date.parse(row.created_at) };
  }
  return { id: `row-${row.id}`, kind: "error", content: `未知消息类型: ${row.kind}` };
}

// 断线续传：从 after+1 起补发错过的 SSE 事件并跟随到本轮结束，失败按指数退避重试若干次。
// after 未知（连 user_stored 都没收到）时无从续传，直接返回 false。
const RESUME_ATTEMPTS = 5;

async function resumeStream(
  taskId: string,
  after: number | undefined,
  onEvent: SseHandler,
  signal: AbortSignal,
): Promise<boolean> {
  if (after === undefined) return false;
  for (let attempt = 0; attempt < RESUME_ATTEMPTS; attempt++) {
    if (signal.aborted) return false;
    try {
      await getSse(`${API_URL}/api/tasks/${taskId}/stream?after=${after + 1}`, onEvent, signal);
      return true;
    } catch {
      if (signal.aborted) return false;
      await new Promise((resolve) => setTimeout(resolve, 500 * 2 ** attempt));
    }
  }
  return false;
}

export function useChat(taskId: string) {
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [busy, setBusy] = useState(false);
  // 当前流式请求的开关：stop() 通过它中断 fetch 读取循环
  const abortRef = useRef<AbortController | null>(null);
  // 本轮是否已收到 done：done 之后流还活着（服务端在生成跟进问题推荐），
  // 此时点停止只该掐掉推荐尾巴——回复已定稿，不该加"已停止"提示行。
  const doneRef = useRef(false);

  // 仅清自己那次 send 建的控制器（busy 互斥已防并发，双保险不误清）
  const stop = useCallback(() => {
    // 先通知服务端置位停止信号（消费循环 ≤1s 响应、partial+stopped 标记落库），
    // 再 abort 本地读取。落库发生在服务端，与此后本地连接是否已断无关；
    // 单发即可，失败（如网络已断）也无妨——断连路径由同一个服务端兜底覆盖。
    void fetch(`${API_URL}/api/tasks/${taskId}/stop`, { method: "POST" }).catch(() => {});
    abortRef.current?.abort();
  }, [taskId]);

  useEffect(() => {
    void listMessages(taskId)
      .then((rows) =>
        // 历史 GET 与自动发送 effect 同在挂载时触发：若发送先于历史返回产生乐观用户泡，
        // 历史返回（新任务为空数组）会覆盖掉乐观泡。此时若已有任何 live 消息，说明更可能
        // 属于同任务新对话，丢弃该历史快照；空历史场景 prev 本就为空，不受影响。
        // 对称的另一面：打开旧任务后、历史返回前秒发消息时，本守卫会让本次挂载暂看不到
        // 历史（仅视图层缺失，服务端数据仍在，刷新即恢复）；改用 id 合并会在 StrictMode
        // effect 双跑下重复历史行、需额外去重，当前写法幂等，故按 YAGNI 保持现状。
        setMessages((prev) => (prev.length > 0 ? prev : rows.map(fromStored))),
      )
      .catch(() => setMessages([{ id: nextUiId([]), kind: "error", content: "历史消息加载失败，请刷新重试" }]));
  }, [taskId]);

  const send = useCallback(
    async (text: string) => {
      const content = text.trim();
      if (!content) return;
      // 运行中：作为 steering 注入当前轮（乐观加 user 泡，服务端 user_stored 回流校准为 row-N），
      // 不新起一轮、不开新流。
      if (busy) {
        setMessages((prev) => [
          ...dropSuggestions(dropStoppedNotice(prev)),
          { id: nextUiId(prev), kind: "user", content, completedAt: Date.now() },
        ]);
        const steered = await steerTask(taskId, content).catch(() => false);
        if (!steered) {
          setMessages((prev) => [
            ...prev,
            { id: nextUiId(prev), kind: "error", content: "纠偏失败：当前没有进行中的回复，请重试" },
          ]);
        }
        return;
      }
      // 新一轮发送清掉上一轮的"已停止"提示行与跟进问题推荐（两者都已过时）。
      // user 泡乐观带上本地时刻（操作行据此显示时间）；user_stored 回执到后即校准为服务端时间。
      doneRef.current = false;
      setMessages((prev) => [
        ...dropSuggestions(dropStoppedNotice(prev)),
        { id: nextUiId(prev), kind: "user", content, completedAt: Date.now() },
      ]);
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setBusy(true);
      let lastId: number | undefined;
      const applyEvent = (event: ChatEvent, id?: number) => {
        if (id !== undefined) lastId = id;
        if (event.type === "done") doneRef.current = true;
        // 标题事件不进本页消息列表，单独转发给侧栏（两者是独立组件/独立 state）。
        if (event.type === "title") emitTaskTitleUpdated(taskId, event.title);
        setMessages((prev) => reduceChatEvent(prev, event));
      };
      try {
        await postSse(`${API_URL}/api/tasks/${taskId}/messages`, { content }, applyEvent, ctrl.signal);
      } catch (error) {
        // 用户点停止 → fetch 抛 AbortError：定稿已流出的部分内容（保留在流中），
        // 不追加错误泡；其余错误尝试续传。
        if (error instanceof Error && error.name === "AbortError") {
          // done 已收到 = 回复已正常定稿，此刻点停止只掐推荐尾巴：不加"已停止"行
          if (!doneRef.current) {
            // 定稿部分内容 + 未决审批标为拒绝（服务端也会拒，但回流事件可能已随流断开）+ "已停止"提示行
            setMessages((prev) => appendStoppedNotice(denyPendingApprovals(finalizeStreaming(prev))));
          }
        } else {
          // 网络抖动：续传补齐错过的事件；成功后以服务端历史为准刷新（拿回落库的 assistant/stopped 行）。
          const recovered = await resumeStream(taskId, lastId, applyEvent, ctrl.signal);
          if (recovered) {
            const rows = await listMessages(taskId).catch(() => null);
            if (rows) setMessages(rows.map(fromStored));
          } else {
            setMessages((prev) => [...prev, { id: nextUiId(prev), kind: "error", content: "连接中断，重连失败，请重试" }]);
          }
        }
      } finally {
        if (abortRef.current === ctrl) abortRef.current = null;
        setBusy(false);
      }
    },
    [busy, taskId],
  );

  // 删除整轮问答（目标 user 行 + 其后直到下一 user 前的所有行）：先服务端后本地，
  // 本地用与 DB 同语义的区间删除，无需重拉历史。
  const deleteTurn = useCallback(
    async (messageId: string) => {
      const rowId = /^row-(\d+)$/.exec(messageId)?.[1];
      // live-N 泡没有服务端行——删除入口只在 row-N 上出现，此分支理论不可达，防御性早退。
      if (!rowId) return;
      try {
        await deleteTurnApi(taskId, Number(rowId));
        setMessages((prev) => dropTurn(prev, messageId));
      } catch {
        setMessages((prev) => [...prev, { id: nextUiId(prev), kind: "error", content: "删除失败，请重试" }]);
      }
    },
    [taskId],
  );

  // 审批决定回传：本地状态由流内的 approval_resolved 事件更新（不在此处改，避免与流乱序）。
  const respondToApproval = useCallback(
    async (approvalId: string, approved: boolean) => {
      try {
        await respondToApprovalApi(taskId, approvalId, approved);
      } catch {
        setMessages((prev) => [...prev, { id: nextUiId(prev), kind: "error", content: "审批提交失败，请重试" }]);
      }
    },
    [taskId],
  );

  // 重新生成：定位该回复所属轮的提问 → 删整轮（服务端 + 本地）→ 原样重发。
  // 未落库的 live user（几乎不可能：重生成入口只在定稿回复上）无法重放，防御性早退。
  const regenerate = useCallback(
    async (assistantId: string) => {
      const user = turnUserMessage(messages, assistantId);
      const rowId = user ? /^row-(\d+)$/.exec(user.id)?.[1] : undefined;
      if (!user || !rowId) return;
      const content = user.content;
      try {
        await deleteTurnApi(taskId, Number(rowId));
      } catch {
        setMessages((prev) => [...prev, { id: nextUiId(prev), kind: "error", content: "重新生成失败，请重试" }]);
        return;
      }
      setMessages((prev) => dropTurn(prev, user.id));
      await send(content);
    },
    [messages, send, taskId],
  );

  return { messages, busy, send, stop, deleteTurn, respondToApproval, regenerate };
}
