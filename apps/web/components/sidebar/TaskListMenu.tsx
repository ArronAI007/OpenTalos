"use client";

import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { Project, Task } from "@/lib/api";
import { ArchiveIcon, CheckIcon, ChevronDownIcon, ChevronRightIcon, ExternalLinkIcon, FolderIcon, FolderMinusIcon, PencilSquareIcon, PinIcon, ShareIcon, StarIcon, TrashIcon } from "@/components/ui/icons";

interface TaskListMenuProps {
  task: Task;
  projects: Project[];
  onShare: () => Promise<boolean>;
  onClose: () => void;
  onRename: () => void;
  onOpenInNewTab: () => void;
  onTogglePin: () => void;
  onToggleStar: () => void;
  onMoveToProject: (projectId: string | null) => void;
  onCreateProjectAndMove: (name: string) => void;
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

// 任务行 ··· 下拉菜单：经 portal 挂到 body、以固定定位浮在行右侧之上。
// 必须脱离侧栏滚动容器：其 overflow-y-auto 会同时裁剪 x/y 方向，靠顶/底行的菜单会被切掉。
// 开合由 TaskList 控制（同时最多一个）；点击菜单外或 Esc 由 TaskList 的全局监听关闭。
export function TaskListMenu({ task, projects, onShare, onClose, onRename, onOpenInNewTab, onTogglePin, onToggleStar, onMoveToProject, onCreateProjectAndMove, onArchive, onDelete }: TaskListMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  // 先隐藏测量尺寸，再定位，避免首帧闪一下错位。
  const [position, setPosition] = useState<CSSProperties>({ position: "fixed", top: 0, left: 0, visibility: "hidden" });
  // 分享反馈状态自管于菜单内部：分享是唯一"点击后不立即关菜单"的项，其余项由父层一键关闭，
  // 状态上移父层反而要为单次反馈维护 per-task 状态与复位逻辑。菜单开合即条件渲染重挂载，
  // shareState 随卸载天然复位，无需外部复位；关闭动作经 onClose 回传父层。
  const [shareState, setShareState] = useState<"idle" | "copied" | "failed">("idle");
  const shareTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  // 「移动到项目」子区：就地纵向展开（单一滚动面，不引 flyout）；
  // creatingProject = 新建项目行内输入态。
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const [creatingProject, setCreatingProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");

  // 固定定位：优先贴在行下方，下方空间不足则上翻；右对齐锚点并夹在视口内。
  // 锚点每次定位时按行现查 DOM（而非缓存元素）：行因标题/排序更新重渲染后旧节点会脱离文档，
  // 缓存的元素 getBoundingClientRect 归零会把菜单甩到左上角。
  // 依赖 projectMenuOpen——子区展开会改变菜单高度，需重算一次。
  // 监听 scroll（capture 捕获任意滚动容器）/resize 实时纠位，避免侧栏滚动后菜单悬空错位。
  useLayoutEffect(() => {
    const selector = `[data-task-row="${task.id}"] button[aria-haspopup="menu"]`;
    const place = () => {
      const el = menuRef.current;
      const anchor = document.querySelector<HTMLElement>(selector);
      if (!el || !anchor) return;
      const a = anchor.getBoundingClientRect();
      const rect = el.getBoundingClientRect();
      const gap = 4;
      const spaceBelow = window.innerHeight - a.bottom;
      const openUp = spaceBelow < rect.height + gap && a.top > rect.height + gap;
      const top = openUp ? a.top - rect.height - gap : a.bottom + gap;
      const left = Math.max(8, Math.min(a.right - rect.width, window.innerWidth - rect.width - 8));
      setPosition({ position: "fixed", top, left, visibility: "visible" });
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [task.id, projectMenuOpen]);

  // 卸载时双保险，防旧菜单的 onClose 误关其他任务的菜单：
  // ① 清已存在的延时定时器（菜单先行关闭/切换的场景）；② mountedRef 置 false，挡住 await 返回后
  // 再新建的定时器——Clipboard API 是异步的，写剪贴板期间外点/Esc 卸载（由 TaskList 全局监听触发），
  // 此处 cleanup 已跑、但 handleShareClick 的 await 尚未返回，之后新建的 timer 将无人清理（孤儿）。
  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (shareTimerRef.current !== null) clearTimeout(shareTimerRef.current);
    };
  }, []);

  // 分享：复制结果驱动反馈文案（已复制/复制失败），菜单保持打开，延时后统一由 onClose 关闭。
  const handleShareClick = async () => {
    const ok = await onShare();
    if (!mountedRef.current) return; // await 期间已被卸载：不落状态、不设新定时器
    setShareState(ok ? "copied" : "failed");
    if (shareTimerRef.current !== null) clearTimeout(shareTimerRef.current); // 连点重置计时
    shareTimerRef.current = setTimeout(onClose, 1500);
  };

  const subItemCls = "flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm hover:bg-sidebar";

  return createPortal(
    <div
      ref={menuRef}
      role="menu"
      data-task-menu={task.id}
      aria-label={`任务「${task.title || "未命名任务"}」操作`}
      style={position}
      className="z-50 w-44 rounded-lg border border-border bg-surface p-1 shadow-lg"
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
      <div>
        <button
          type="button"
          role="menuitem"
          aria-expanded={projectMenuOpen}
          className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-sidebar"
          onClick={() => setProjectMenuOpen((v) => !v)}
        >
          <FolderIcon />
          移动到项目
          {projectMenuOpen
            ? <ChevronDownIcon width={12} height={12} className="ml-auto" />
            : <ChevronRightIcon width={12} height={12} className="ml-auto" />}
        </button>
        {projectMenuOpen && (
          <div className="mx-1 mb-1 rounded-md border border-border p-1">
            {task.project_id !== null && (
              <button type="button" role="menuitem" className={subItemCls} onClick={() => onMoveToProject(null)}>
                <FolderMinusIcon />
                移出项目
              </button>
            )}
            <ul className="max-h-40 overflow-y-auto">
              {projects.map((project) => (
                <li key={project.id}>
                  <button type="button" role="menuitem" className={subItemCls} onClick={() => onMoveToProject(project.id)}>
                    <span className="flex w-4 shrink-0 justify-center">
                      {task.project_id === project.id && <CheckIcon width={12} height={12} />}
                    </span>
                    <span className="truncate">{project.name}</span>
                  </button>
                </li>
              ))}
            </ul>
            {creatingProject ? (
              <input
                value={newProjectName}
                onChange={(e) => setNewProjectName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.nativeEvent.isComposing) return; // IME 候选窗激活时 Enter/Esc 仅作用于输入法，不提交/取消
                  if (e.key === "Enter") {
                    e.preventDefault();
                    const name = newProjectName.trim();
                    if (name) onCreateProjectAndMove(name); // 父层两步请求（建项目+移入）后关菜单
                  } else if (e.key === "Escape") {
                    // 只退出输入态；必须阻止冒泡，否则 TaskList 的 document Esc 监听会把整个菜单关掉
                    e.stopPropagation();
                    setCreatingProject(false);
                    setNewProjectName("");
                  }
                }}
                autoFocus
                aria-label="新建项目名称"
                placeholder="项目名称"
                className="w-full rounded border border-border bg-surface px-2 py-1 text-sm outline-none focus:border-accent"
              />
            ) : (
              <button type="button" role="menuitem" className={subItemCls} onClick={() => setCreatingProject(true)}>
                ＋ 新建项目
              </button>
            )}
          </div>
        )}
      </div>
      <MenuItem icon={<ArchiveIcon />} onClick={onArchive}>归档</MenuItem>
      <MenuItem icon={<TrashIcon />} danger onClick={onDelete}>删除</MenuItem>
    </div>,
    document.body,
  );
}
