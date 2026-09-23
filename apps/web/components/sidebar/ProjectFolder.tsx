"use client";

import { useState, type ReactNode } from "react";
import type { Project, Task } from "@/lib/api";
import { ChevronDownIcon, ChevronRightIcon, FolderIcon } from "@/components/ui/icons";

interface ProjectFolderProps {
  project: Project;
  tasks: Task[]; // 组内已按三级规则排好序（partitionTasks 负责）
  // 行结构与主未归组列表完全同源：TaskList 传入同一个行渲染函数（含 ⋯ 菜单与重命名）。
  renderTask: (task: Task) => ReactNode;
}

// 项目文件夹折叠区：默认收起；展开态仅存组件本地，分区数据变化（成员进出）不重置展开状态。
// 纯受控：项目数据、成员任务、行渲染全部由父组件传入。
export function ProjectFolder({ project, tasks, renderTask }: ProjectFolderProps) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div>
      <button
        type="button"
        aria-label={`项目文件夹 ${project.name}`}
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-1.5 rounded-lg px-3 py-1.5 text-left text-xs text-text-secondary hover:bg-white"
      >
        {expanded ? <ChevronDownIcon width={12} height={12} /> : <ChevronRightIcon width={12} height={12} />}
        <FolderIcon width={12} height={12} />
        <span className="truncate">{project.name}</span>
        {expanded && <span>({tasks.length})</span>}
      </button>
      {expanded && (
        <ul>
          {tasks.length === 0 && (
            <li className="px-3 py-1 text-xs text-text-secondary">暂无任务</li>
          )}
          {tasks.map(renderTask)}
        </ul>
      )}
    </div>
  );
}
