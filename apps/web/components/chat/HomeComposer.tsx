"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Composer } from "./Composer";
import { createTask } from "@/lib/api";
import { readAgentType } from "@/lib/agent-type";
import { stashPendingMessage } from "@/lib/pending-message";

export function HomeComposer() {
  const router = useRouter();
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSend = async (text: string) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const task = await createTask(readAgentType());
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
      />
    </>
  );
}
