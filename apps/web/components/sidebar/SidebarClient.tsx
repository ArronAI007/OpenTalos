"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { createTask, deleteTask, listTasks, updateTask, type Task } from "@/lib/api";
import { readAgentType } from "@/lib/agent-type";
import { sortTasks } from "@/lib/task-sort";
import { ClockIcon, PencilSquareIcon, PinIcon, PuzzleIcon, SearchIcon, SparklesIcon, StarIcon } from "@/components/ui/icons";
import { LogoMark } from "./Logo";
import { TaskListMenu } from "./TaskListMenu";

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
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const committingRef = useRef(false);
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    void listTasks().then(setTasks).catch(() => undefined);
  }, [pathname]); // 路由变化（新建/删除导航）触发刷新

  // 点击菜单外或 Esc 关闭当前唯一打开的菜单。
  useEffect(() => {
    if (openMenuId === null) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && !target.closest(`[data-task-row="${openMenuId}"]`)) setOpenMenuId(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenMenuId(null);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [openMenuId]);

  const handleDelete = async (taskId: string) => {
    await deleteTask(taskId);
    setTasks((prev) => prev.filter((t) => t.id !== taskId));
    if (pathname === `/t/${taskId}`) router.push("/");
  };

  // 固定/取消固定：用接口返回的任务本地 patch 并按 sortTasks 重排，不重拉列表；失败静默。
  const handleTogglePin = async (task: Task) => {
    try {
      const updated = await updateTask(task.id, { pinned: !task.pinned });
      setTasks((prev) => sortTasks(prev.map((t) => (t.id === task.id ? updated : t))));
    } catch {
      // 与项目现状一致：不引入错误 UI 体系
    }
  };

  // 收藏/取消收藏：与 handleTogglePin 同构，本地 patch 后重排。
  const handleToggleStar = async (task: Task) => {
    try {
      const updated = await updateTask(task.id, { starred: !task.starred });
      setTasks((prev) => sortTasks(prev.map((t) => (t.id === task.id ? updated : t))));
    } catch {
      // 与项目现状一致：不引入错误 UI 体系
    }
  };

  const startEdit = (task: Task) => {
    setEditingId(task.id);
    setEditValue(task.title);
    setEditError(null);
    committingRef.current = false;
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditError(null);
  };

  const commitEdit = async (task: Task) => {
    if (committingRef.current) return; // 防 Enter 提交后 blur 二次触发
    const trimmed = editValue.trim();
    if (!trimmed) {
      cancelEdit(); // 空标题前端先挡，不提交
      return;
    }
    committingRef.current = true;
    try {
      const updated = await updateTask(task.id, { title: trimmed });
      setTasks((prev) => prev.map((t) => (t.id === task.id ? { ...t, ...updated } : t)));
      setEditingId(null);
    } catch {
      setEditError("重命名失败，请重试");
      setEditValue(task.title); // 回退原值
    } finally {
      committingRef.current = false;
    }
  };

  return (
    <section aria-label="任务历史" className="flex-1 overflow-y-auto">
      <p className="px-3 py-1 text-xs text-text-secondary">任务历史</p>
      <ul>
        {tasks.map((task) => {
          const active = pathname === `/t/${task.id}`;
          const editing = editingId === task.id;
          return (
            <li key={task.id} className="group relative" data-task-row={task.id}>
              {editing ? (
                <div className="px-3 py-2">
                  <input
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onBlur={() => void commitEdit(task)}
                    onKeyDown={(e) => {
                      if (e.nativeEvent.isComposing) return; // IME 候选窗激活时 Enter/Esc 仅作用于输入法，不提交/取消
                      if (e.key === "Enter") {
                        e.preventDefault();
                        void commitEdit(task);
                      } else if (e.key === "Escape") {
                        cancelEdit();
                      }
                    }}
                    autoFocus
                    onFocus={(e) => e.target.select()}
                    aria-label="重命名任务"
                    className="w-full rounded border border-border bg-white px-2 py-1 text-sm outline-none focus:border-accent"
                  />
                  {editError && <p className="mt-1 text-xs text-red-500">{editError}</p>}
                </div>
              ) : (
                <>
                  <a
                    href={`/t/${task.id}`}
                    className={`block rounded-lg px-3 py-2 text-sm hover:bg-white ${active ? "bg-white font-medium" : ""}`}
                  >
                    <span className="flex items-center gap-1.5">
                      {task.pinned && (
                        <PinIcon width={12} height={12} className="shrink-0 text-text-secondary" />
                      )}
                      {task.starred && (
                        <StarIcon width={12} height={12} className="shrink-0 text-text-secondary" />
                      )}
                      <span className="truncate">{task.title || "（未命名任务）"}</span>
                    </span>
                    <span className="text-xs text-text-secondary">{task.agent_type}</span>
                  </a>
                  <button
                    type="button"
                    aria-label="更多选项"
                    aria-haspopup="menu"
                    aria-expanded={openMenuId === task.id}
                    onClick={() => setOpenMenuId(openMenuId === task.id ? null : task.id)}
                    className="absolute right-2 top-2 hidden rounded px-1.5 text-text-secondary hover:bg-sidebar hover:text-text group-hover:block"
                  >
                    ⋯
                  </button>
                  {openMenuId === task.id && (
                    <TaskListMenu
                      task={task}
                      onRename={() => {
                        setOpenMenuId(null);
                        startEdit(task);
                      }}
                      onOpenInNewTab={() => {
                        window.open(`/t/${task.id}`, "_blank", "noopener,noreferrer");
                        setOpenMenuId(null);
                      }}
                      onTogglePin={() => {
                        setOpenMenuId(null);
                        void handleTogglePin(task);
                      }}
                      onToggleStar={() => {
                        setOpenMenuId(null);
                        void handleToggleStar(task);
                      }}
                      onDelete={() => {
                        setOpenMenuId(null);
                        void handleDelete(task.id);
                      }}
                    />
                  )}
                </>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
