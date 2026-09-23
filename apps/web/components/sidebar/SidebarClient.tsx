"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { createTask, deleteTask, listTasks, type Task } from "@/lib/api";
import { readAgentType } from "@/lib/agent-type";

export function NewTaskButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCreate = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const task = await createTask(readAgentType());
      router.push(`/t/${task.id}`);
    } catch {
      setError("创建失败，请检查 API 是否启动");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        onClick={handleCreate}
        disabled={busy}
        className="mb-2 rounded-lg border border-border bg-white px-3 py-2 text-left text-sm font-medium hover:border-text-secondary disabled:opacity-50"
      >
        ＋ 新建任务
      </button>
      {error && <p className="mb-2 text-xs text-red-500">{error}</p>}
    </>
  );
}

export function TaskList() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    void listTasks().then(setTasks).catch(() => undefined);
  }, [pathname]); // 路由变化（新建/删除导航）触发刷新

  const handleDelete = async (taskId: string) => {
    await deleteTask(taskId);
    setTasks((prev) => prev.filter((t) => t.id !== taskId));
    if (pathname === `/t/${taskId}`) router.push("/");
  };

  return (
    <section aria-label="任务历史" className="flex-1 overflow-y-auto">
      <p className="px-3 py-1 text-xs text-text-secondary">任务历史</p>
      <ul>
        {tasks.map((task) => {
          const active = pathname === `/t/${task.id}`;
          return (
            <li key={task.id} className="group relative">
              <a
                href={`/t/${task.id}`}
                className={`block rounded-lg px-3 py-2 text-sm hover:bg-white ${active ? "bg-white font-medium" : ""}`}
              >
                <span className="block truncate">{task.title || "（未命名任务）"}</span>
                <span className="text-xs text-text-secondary">{task.agent_type}</span>
              </a>
              <button
                aria-label={`删除 ${task.title}`}
                onClick={() => void handleDelete(task.id)}
                className="absolute right-2 top-2 hidden rounded px-1 text-xs text-text-secondary hover:text-red-500 group-hover:block"
              >
                ✕
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
