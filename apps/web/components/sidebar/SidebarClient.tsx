"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { createTask, deleteTask, listTasks, type Task } from "@/lib/api";
import { readAgentType } from "@/lib/agent-type";
import { ClockIcon, PencilSquareIcon, PuzzleIcon, SearchIcon, SparklesIcon } from "@/components/ui/icons";
import { LogoMark } from "./Logo";

// 新建任务逻辑抽成 hook：窄栏图标与展开态按钮共用同一份 busy/error 状态，
// 失败时行内报错由展开后的 NewTaskButton 展示（窄栏触发失败会自动展开）。
export function useCreateTask() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = async (): Promise<boolean> => {
    if (busy) return false;
    setBusy(true);
    setError(null);
    try {
      const task = await createTask(readAgentType());
      router.push(`/t/${task.id}`);
      return true;
    } catch {
      setError("创建失败，请检查 API 是否启动");
      return false;
    } finally {
      setBusy(false);
    }
  };

  return { busy, error, create };
}

interface NewTaskButtonProps {
  busy: boolean;
  error: string | null;
  onCreate: () => void;
}

export function NewTaskButton({ busy, error, onCreate }: NewTaskButtonProps) {
  return (
    <>
      <button
        onClick={onCreate}
        disabled={busy}
        className="mb-2 rounded-lg border border-border bg-white px-3 py-2 text-left text-sm font-medium hover:border-text-secondary disabled:opacity-50"
      >
        ＋ 新建任务
      </button>
      {error && <p className="mb-2 text-xs text-red-500">{error}</p>}
    </>
  );
}

interface SidebarRailProps {
  busy: boolean;
  onCreate: () => void;
  onExpand: () => void;
  onOpenSearch: () => void;
}

export function SidebarRail({ busy, onCreate, onExpand, onOpenSearch }: SidebarRailProps) {
  const iconBtn = "rounded-lg p-1.5 text-text-secondary hover:bg-white hover:text-text";
  return (
    <nav aria-label="主导航" className="flex w-14 shrink-0 flex-col items-center gap-1 border-r border-border bg-sidebar p-2">
      <button type="button" aria-label="打开侧栏" title="打开侧栏" onClick={onExpand} className={iconBtn}>
        <LogoMark />
      </button>
      <button
        type="button"
        aria-label="新建任务"
        title="新建任务"
        onClick={onCreate}
        disabled={busy}
        className={`${iconBtn} disabled:opacity-50`}
      >
        <PencilSquareIcon />
      </button>
      <button type="button" aria-label="搜索任务" title="搜索任务" onClick={onOpenSearch} className={iconBtn}>
        <SearchIcon />
      </button>
      <Link href="/agents" aria-label="Agent" title="Agent" className={iconBtn}>
        <SparklesIcon />
      </Link>
      <Link href="/skills" aria-label="技能" title="技能" className={iconBtn}>
        <PuzzleIcon />
      </Link>
      <button type="button" aria-label="任务历史" title="任务历史" onClick={onExpand} className={iconBtn}>
        <ClockIcon />
      </button>
    </nav>
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
