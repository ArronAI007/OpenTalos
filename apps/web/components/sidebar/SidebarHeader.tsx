"use client";

import { Logo } from "./Logo";
import { PanelLeftCloseIcon, SearchIcon } from "@/components/ui/icons";

interface SidebarHeaderProps {
  query: string;
  onQueryChange: (query: string) => void;
  searchOpen: boolean;
  onSearchOpenChange: (open: boolean) => void;
  onToggleCollapse: () => void;
}

export function SidebarHeader({
  query,
  onQueryChange,
  searchOpen,
  onSearchOpenChange,
  onToggleCollapse,
}: SidebarHeaderProps) {
  const closeSearch = () => {
    onQueryChange("");
    onSearchOpenChange(false);
  };

  const toggleSearch = () => {
    // 收起时一并清空 query，与 ✕ / Esc 的 closeSearch 行为保持一致，避免列表仍在过滤但无可见指示。
    if (searchOpen) onQueryChange("");
    onSearchOpenChange(!searchOpen);
  };

  return (
    <>
      <div className="flex items-center justify-between px-1 pb-2">
        <Logo />
        <div className="flex items-center gap-1">
          <button
            type="button"
            aria-label="搜索任务"
            aria-expanded={searchOpen}
            onClick={toggleSearch}
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
      {searchOpen && (
        <div className="mb-2 flex items-center gap-1">
          <input
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") closeSearch();
            }}
            placeholder="搜索任务标题"
            aria-label="搜索任务标题"
            autoFocus
            className="w-full rounded-lg border border-border bg-white px-3 py-1.5 text-sm"
          />
          <button
            type="button"
            aria-label="清空搜索"
            onClick={closeSearch}
            className="rounded px-1 text-text-secondary hover:text-text"
          >
            ✕
          </button>
        </div>
      )}
    </>
  );
}
