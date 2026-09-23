"use client";

import type { Task } from "@/lib/api";
import { ExternalLinkIcon, PencilSquareIcon, PinIcon, StarIcon, TrashIcon } from "@/components/ui/icons";

interface TaskListMenuProps {
  task: Task;
  onRename: () => void;
  onOpenInNewTab: () => void;
  onTogglePin: () => void;
  onToggleStar: () => void;
  onDelete: () => void;
}

// 任务行 ··· 下拉菜单：绝对定位于所属 <li data-task-row>（relative）内，浮于右侧内容之上。
// 开合由 TaskList 控制（同时最多一个）；点击菜单外或 Esc 由 TaskList 的全局监听关闭。
export function TaskListMenu({ task, onRename, onOpenInNewTab, onTogglePin, onToggleStar, onDelete }: TaskListMenuProps) {
  const itemCls = "flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-sidebar";
  return (
    <div
      role="menu"
      aria-label={`任务「${task.title || "未命名任务"}」操作`}
      className="absolute right-2 top-full z-10 mt-1 w-44 rounded-lg border border-border bg-white p-1 shadow-lg"
    >
      <button type="button" role="menuitem" className={itemCls} onClick={onRename}>
        <PencilSquareIcon />
        重命名
      </button>
      <button type="button" role="menuitem" className={itemCls} onClick={onOpenInNewTab}>
        <ExternalLinkIcon />
        在新标签中打开
      </button>
      <button type="button" role="menuitem" className={itemCls} onClick={onTogglePin}>
        <PinIcon />
        {task.pinned ? "取消固定" : "固定"}
      </button>
      <button type="button" role="menuitem" className={itemCls} onClick={onToggleStar}>
        <StarIcon />
        {task.starred ? "取消收藏" : "收藏"}
      </button>
      <button type="button" role="menuitem" className={`${itemCls} text-red-500`} onClick={onDelete}>
        <TrashIcon />
        删除
      </button>
    </div>
  );
}
