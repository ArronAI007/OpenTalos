"use client";

import { useState } from "react";
import Link from "next/link";
import { NewTaskButton, SidebarRail, TaskList, useCreateTask } from "./SidebarClient";
import { SidebarHeader } from "./SidebarHeader";
import { SearchModal } from "@/components/search/SearchModal";

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export function Sidebar({ collapsed, onToggleCollapse }: SidebarProps) {
  const [searchOpen, setSearchOpen] = useState(false);
  const { busy, error, create } = useCreateTask();

  // 窄栏只在折叠态渲染，此时 onToggleCollapse 等价于「展开」。
  const handleExpand = onToggleCollapse;
  const openSearch = () => setSearchOpen(true);
  const closeSearch = () => setSearchOpen(false);
  const handleRailCreate = async () => {
    const ok = await create();
    // 失败自动展开，行内报错由展开后的 NewTaskButton 展示。
    if (!ok) onToggleCollapse();
  };

  return (
    <>
      {collapsed ? (
        <SidebarRail
          busy={busy}
          onCreate={handleRailCreate}
          onExpand={handleExpand}
          onOpenSearch={openSearch}
        />
      ) : (
        <nav aria-label="主导航" className="flex w-60 shrink-0 flex-col border-r border-border bg-sidebar p-3">
          <SidebarHeader onOpenSearch={openSearch} onToggleCollapse={onToggleCollapse} />
          <NewTaskButton busy={busy} error={error} onCreate={() => void create()} />
          <Link href="/agents" className="rounded-lg px-3 py-2 text-sm hover:bg-white">◈ Agent</Link>
          <Link href="/skills" className="rounded-lg px-3 py-2 text-sm hover:bg-white">🧩 技能</Link>
          <hr className="my-3 border-border" />
          <TaskList />
        </nav>
      )}
      <SearchModal open={searchOpen} onClose={closeSearch} />
    </>
  );
}
