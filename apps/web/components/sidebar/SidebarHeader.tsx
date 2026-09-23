"use client";

import { Logo } from "./Logo";
import { PanelLeftCloseIcon, SearchIcon } from "@/components/ui/icons";

interface SidebarHeaderProps {
  onOpenSearch: () => void;
  onToggleCollapse: () => void;
}

export function SidebarHeader({ onOpenSearch, onToggleCollapse }: SidebarHeaderProps) {
  return (
    <div className="flex items-center justify-between px-1 pb-2">
      <Logo />
      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-label="搜索任务"
          onClick={onOpenSearch}
          className="rounded-lg p-1.5 text-text-secondary hover:bg-white hover:text-text"
        >
          <SearchIcon />
        </button>
        <button
          type="button"
          aria-label="折叠侧栏"
          onClick={onToggleCollapse}
          className="rounded-lg p-1.5 text-text-secondary hover:bg-white hover:text-text"
        >
          <PanelLeftCloseIcon />
        </button>
      </div>
    </div>
  );
}
