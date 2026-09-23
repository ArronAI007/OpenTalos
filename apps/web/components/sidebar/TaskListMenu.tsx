"use client";

import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { Task } from "@/lib/api";
import { ArchiveIcon, ExternalLinkIcon, PencilSquareIcon, PinIcon, StarIcon, TrashIcon } from "@/components/ui/icons";

interface TaskListMenuProps {
  task: Task;
  onRename: () => void;
  onOpenInNewTab: () => void;
  onTogglePin: () => void;
  onToggleStar: () => void;
  onArchive: () => void;
  onDelete: () => void;
}

interface MenuItemProps {
  icon: ReactNode;
  danger?: boolean;
  onClick: () => void;
  children: ReactNode;
}

function MenuItem({ icon, danger = false, onClick, children }: MenuItemProps) {
  const cls = `flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-sidebar${danger ? " text-red-500" : ""}`;
  return (
    <button type="button" role="menuitem" className={cls} onClick={onClick}>
      {icon}
      {children}
    </button>
  );
}

// 任务行 ··· 下拉菜单：绝对定位于所属 <li data-task-row>（relative）内，浮于右侧内容之上。
// 开合由 TaskList 控制（同时最多一个）；点击菜单外或 Esc 由 TaskList 的全局监听关闭。
export function TaskListMenu({ task, onRename, onOpenInNewTab, onTogglePin, onToggleStar, onArchive, onDelete }: TaskListMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [flipUp, setFlipUp] = useState(false);

  // 菜单位于 overflow-y-auto 滚动容器内，靠底任务的菜单会被裁剪：挂载后测量，
  // 下沿溢出视口则向上翻转（bottom-full）。开合即重新挂载，测一次即可；
  // useLayoutEffect 在绘制前纠位，避免先闪一帧错位。
  useLayoutEffect(() => {
    const rect = menuRef.current?.getBoundingClientRect();
    if (rect && rect.bottom > window.innerHeight) setFlipUp(true);
  }, []);

  return (
    <div
      ref={menuRef}
      role="menu"
      aria-label={`任务「${task.title || "未命名任务"}」操作`}
      className={`absolute right-2 z-10 w-44 rounded-lg border border-border bg-white p-1 shadow-lg ${flipUp ? "bottom-full mb-1" : "top-full mt-1"}`}
    >
      <MenuItem icon={<PencilSquareIcon />} onClick={onRename}>重命名</MenuItem>
      <MenuItem icon={<ExternalLinkIcon />} onClick={onOpenInNewTab}>在新标签中打开</MenuItem>
      <MenuItem icon={<PinIcon />} onClick={onTogglePin}>{task.pinned ? "取消固定" : "固定"}</MenuItem>
      <MenuItem icon={<StarIcon />} onClick={onToggleStar}>{task.starred ? "取消收藏" : "收藏"}</MenuItem>
      <MenuItem icon={<ArchiveIcon />} onClick={onArchive}>归档</MenuItem>
      <MenuItem icon={<TrashIcon />} danger onClick={onDelete}>删除</MenuItem>
    </div>
  );
}
