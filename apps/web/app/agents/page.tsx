"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  createTask,
  deleteCustomAgent,
  generateAgent,
  listCustomAgents,
  type CustomAgent,
} from "@/lib/api";
import { TrashIcon } from "@/components/ui/icons";
import { PageSkeleton } from "@/components/ui/PageSkeleton";

const EXAMPLES = ["帮我把零散笔记整理成结构清晰的周报", "做一个严谨的代码审查员，只指出真正的问题", "一个耐心的英语口语陪练"];

export default function AgentsPage() {
  const router = useRouter();
  const [agents, setAgents] = useState<CustomAgent[] | null>(null);
  const [prompt, setPrompt] = useState("");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    listCustomAgents()
      .then(setAgents)
      .catch(() => {
        setAgents([]);
        setError("无法加载 Agent 列表，请检查 API 是否启动");
      });
  }, []);

  const handleGenerate = async () => {
    const text = prompt.trim();
    if (!text || generating) return;
    setGenerating(true);
    setError(null);
    try {
      const agent = await generateAgent(text);
      setAgents((prev) => [agent, ...(prev ?? [])]);
      setPrompt("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成失败");
    } finally {
      setGenerating(false);
    }
  };

  const handleUse = async (id: string) => {
    setBusyId(id);
    setError(null);
    try {
      const task = await createTask(id);
      router.push(`/t/${task.id}`);
    } catch {
      setError("创建任务失败，请检查 API 是否启动");
      setBusyId(null);
    }
  };

  const handleDelete = async (id: string) => {
    setBusyId(id);
    setError(null);
    try {
      await deleteCustomAgent(id);
      setAgents((prev) => prev?.filter((a) => a.id !== id) ?? null);
    } catch {
      setError("删除失败，请检查 API 是否启动");
    } finally {
      setBusyId(null);
    }
  };

  if (agents === null) return <PageSkeleton />;

  return (
    <section className="p-6">
      <h1 className="mb-4 text-xl font-semibold">Agent</h1>
      <p className="mb-4 text-sm text-text-secondary">
        用一句话描述你想要的 Agent，自动生成名称、角色设定和可用技能；之后可以随时用它开启新任务。
      </p>

      <div className="mb-6 rounded-xl border border-border bg-surface p-4">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void handleGenerate();
            }
          }}
          maxLength={500}
          rows={2}
          placeholder="例如：帮我把零散笔记整理成结构清晰的周报"
          className="w-full resize-none rounded-lg border border-border bg-transparent p-2 text-sm outline-none focus:border-text-secondary"
        />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => setPrompt(ex)}
              className="rounded-full border border-border px-2.5 py-1 text-xs text-text-secondary hover:bg-sidebar"
            >
              {ex}
            </button>
          ))}
          <button
            type="button"
            onClick={() => void handleGenerate()}
            disabled={generating || !prompt.trim()}
            className="ml-auto rounded-lg bg-black px-3 py-1.5 text-sm text-white disabled:opacity-40"
          >
            {generating ? "生成中…" : "生成 Agent"}
          </button>
        </div>
        {error && <p className="mt-2 text-sm text-red-500">{error}</p>}
      </div>

      {agents.length === 0 ? (
        <p className="text-sm text-text-secondary">还没有自建的 Agent。任务默认由通用的 ReAct Agent 执行。</p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {agents.map((a) => (
            <li key={a.id} className="flex flex-col rounded-lg border border-border bg-surface p-4">
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-medium">{a.name}</p>
                <button
                  type="button"
                  aria-label={`删除 ${a.name}`}
                  disabled={busyId === a.id}
                  onClick={() => void handleDelete(a.id)}
                  className="text-text-secondary hover:text-red-500 disabled:opacity-40"
                >
                  <TrashIcon />
                </button>
              </div>
              <p className="mt-1 text-sm text-text-secondary">{a.description}</p>
              <details className="mt-2 text-xs text-text-secondary">
                <summary className="cursor-pointer">角色设定</summary>
                <p className="mt-1 whitespace-pre-wrap">{a.system_prompt}</p>
              </details>
              {a.skills.length > 0 && (
                <p className="mt-2 text-xs text-text-secondary">技能：{a.skills.join("、")}</p>
              )}
              <button
                type="button"
                disabled={busyId === a.id}
                onClick={() => void handleUse(a.id)}
                className="mt-3 self-start rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-sidebar disabled:opacity-40"
              >
                用它开始新任务
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
