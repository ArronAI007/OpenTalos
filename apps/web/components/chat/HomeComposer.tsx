"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Composer, type AgentOption } from "./Composer";
import { createTask, listCustomAgents } from "@/lib/api";
import { stashPendingMessage, takeHomeDraft } from "@/lib/pending-message";

export function HomeComposer() {
  const router = useRouter();
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [focusNonce, setFocusNonce] = useState(0);
  // 首页可直接 @ 指定自建 Agent，建任务时按其 id 绑定；null = 默认 Agent
  const [agent, setAgent] = useState<AgentOption | null>(null);
  const [agents, setAgents] = useState<AgentOption[]>([]);

  // 从技能详情弹窗的"推荐用法"点过来的草稿：挂载时取一次（take-once），聚焦到末尾方便直接编辑。
  useEffect(() => {
    const pending = takeHomeDraft();
    if (pending === null) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft(pending);
    setFocusNonce((n) => n + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    listCustomAgents()
      .then((list) => {
        if (!cancelled) setAgents(list.map((a) => ({ id: a.id, name: a.name })));
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  const handleSend = async (text: string) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const task = await createTask(agent?.id);
      stashPendingMessage(task.id, text);
      setDraft(""); // 仅成功才清空草稿，失败保留输入框内容
      router.push(`/t/${task.id}`);
    } catch {
      setError("创建任务失败，请检查 API 是否启动");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {error && (
        <p className="mx-auto mb-2 w-full max-w-3xl px-4 text-xs text-red-500">{error}</p>
      )}
      <Composer
        value={draft}
        onChange={setDraft}
        onSend={(text) => void handleSend(text)}
        disabled={busy}
        focusNonce={focusNonce}
        agent={agent}
        agents={agents}
        onSelectAgent={setAgent}
      />
    </>
  );
}
