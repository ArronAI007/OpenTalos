"use client";

import type { Task } from "@/lib/api";
import { ArchiveRestoreIcon, ChevronDownIcon, ChevronRightIcon, TrashIcon } from "@/components/ui/icons";

interface ArchivedSectionProps {
  expanded: boolean;
  tasks: Task[] | null; // null = 尚未拉取（计数此时不显示）
  onToggle: () => void;
  onRestore: (task: Task) => void;
  onDelete: (task: Task) => void;
}

// 侧栏底部「已归档」折叠区：默认折叠；展开后由父组件拉取归档任务。
// 行内只放恢复/删除两个图标按钮，不复用任务菜单。
export function ArchivedSection({ expanded, tasks, onToggle, onRestore, onDelete }: ArchivedSectionProps) {
  const iconBtn = "rounded p-1 text-text-secondary hover:bg-white hover:text-text";
  return (
    <div className="mt-2 border-t border-border pt-1">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={onToggle}
        className="flex w-full items-center gap-1.5 rounded-lg px-3 py-1.5 text-left text-xs text-text-secondary hover:bg-white"
      >
        {expanded ? <ChevronDownIcon width={12} height={12} /> : <ChevronRightIcon width={12} height={12} />}
        已归档
        {expanded && tasks !== null && <span>({tasks.length})</span>}
      </button>
      {expanded && (
        <ul>
          {tasks !== null && tasks.length === 0 && (
            <li className="px-3 py-1 text-xs text-text-secondary">暂无已归档任务</li>
          )}
          {(tasks ?? []).map((task) => (
            <li key={task.id} className="flex items-center gap-1 rounded-lg px-3 py-1.5 hover:bg-white">
              <span className="min-w-0 flex-1 truncate text-sm">{task.title || "（未命名任务）"}</span>
              <button type="button" aria-label="恢复任务" title="恢复任务" onClick={() => onRestore(task)} className={iconBtn}>
                <ArchiveRestoreIcon width={14} height={14} />
              </button>
              <button type="button" aria-label="删除任务" title="删除任务" onClick={() => onDelete(task)} className={iconBtn}>
                <TrashIcon width={14} height={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
