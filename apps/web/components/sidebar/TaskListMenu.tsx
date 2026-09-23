"use client";

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { Task } from "@/lib/api";
import { ArchiveIcon, CheckIcon, ExternalLinkIcon, PencilSquareIcon, PinIcon, ShareIcon, StarIcon, TrashIcon } from "@/components/ui/icons";

interface TaskListMenuProps {
  task: Task;
  onShare: () => Promise<boolean>;
  onClose: () => void;
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
export function TaskListMenu({ task, onShare, onClose, onRename, onOpenInNewTab, onTogglePin, onToggleStar, onArchive, onDelete }: TaskListMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [flipUp, setFlipUp] = useState(false);
  // 分享反馈状态自管于菜单内部：分享是唯一"点击后不立即关菜单"的项，其余项由父层一键关闭，
  // 状态上移父层反而要为单次反馈维护 per-task 状态与复位逻辑。菜单开合即条件渲染重挂载，
  // shareState 随卸载天然复位，无需外部复位；关闭动作经 onClose 回传父层。
  const [shareState, setShareState] = useState<"idle" | "copied" | "failed">("idle");
  const shareTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 菜单位于 overflow-y-auto 滚动容器内，靠底任务的菜单会被裁剪：挂载后测量，
  // 下沿溢出视口则向上翻转（bottom-full）。开合即重新挂载，测一次即可；
  // useLayoutEffect 在绘制前纠位，避免先闪一帧错位。
  useLayoutEffect(() => {
    const rect = menuRef.current?.getBoundingClientRect();
    if (rect && rect.bottom > window.innerHeight) setFlipUp(true);
  }, []);

  // 卸载即清分享延时定时器：避免菜单先行关闭/切换后旧定时器再触发 onClose 波及新打开的菜单。
  useEffect(() => {
    return () => {
      if (shareTimerRef.current !== null) clearTimeout(shareTimerRef.current);
    };
  }, []);

  // 分享：复制结果驱动反馈文案（已复制/复制失败），菜单保持打开，延时后统一由 onClose 关闭。
  const handleShareClick = async () => {
    const ok = await onShare();
    setShareState(ok ? "copied" : "failed");
    if (shareTimerRef.current !== null) clearTimeout(shareTimerRef.current); // 连点重置计时
    shareTimerRef.current = setTimeout(onClose, 1500);
  };

  return (
    <div
      ref={menuRef}
      role="menu"
      aria-label={`任务「${task.title || "未命名任务"}」操作`}
      className={`absolute right-2 z-10 w-44 rounded-lg border border-border bg-white p-1 shadow-lg ${flipUp ? "bottom-full mb-1" : "top-full mt-1"}`}
    >
      <MenuItem
        icon={shareState === "copied" ? <CheckIcon /> : <ShareIcon />}
        onClick={() => void handleShareClick()}
      >
        {shareState === "copied" ? "已复制" : shareState === "failed" ? "复制失败" : "分享"}
      </MenuItem>
      <MenuItem icon={<PencilSquareIcon />} onClick={onRename}>重命名</MenuItem>
      <MenuItem icon={<ExternalLinkIcon />} onClick={onOpenInNewTab}>在新标签中打开</MenuItem>
      <MenuItem icon={<PinIcon />} onClick={onTogglePin}>{task.pinned ? "取消固定" : "固定"}</MenuItem>
      <MenuItem icon={<StarIcon />} onClick={onToggleStar}>{task.starred ? "取消收藏" : "收藏"}</MenuItem>
      <MenuItem icon={<ArchiveIcon />} onClick={onArchive}>归档</MenuItem>
      <MenuItem icon={<TrashIcon />} danger onClick={onDelete}>删除</MenuItem>
    </div>
  );
}
