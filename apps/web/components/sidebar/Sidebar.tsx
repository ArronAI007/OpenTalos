"use client";

import { useState } from "react";
import Link from "next/link";
import { NewTaskButton, SidebarRail, TaskList, useCreateTask } from "./SidebarClient";
import { SidebarHeader } from "./SidebarHeader";
import { SearchModal } from "@/components/search/SearchModal";
import {
  BeakerIcon,
  ChartBarIcon,
  PlugIcon,
  PuzzleIcon,
  SparklesIcon,
  TelescopeIcon,
  XIcon,
} from "@/components/ui/icons";

interface SidebarProps {
  collapsed: boolean;
  mobileOpen: boolean;
  onToggleCollapse: () => void;
  onCloseMobile: () => void;
}

const navLinkCls = "flex items-center gap-2 rounded-lg px-3 py-2 text-sm hover:bg-surface";

export function Sidebar({ collapsed, mobileOpen, onToggleCollapse, onCloseMobile }: SidebarProps) {
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
      {/* 折叠态窄栏：仅桌面显示（移动端用抽屉里的完整导航）。 */}
      {collapsed && (
        <SidebarRail
          className="hidden md:flex"
          busy={busy}
          onCreate={handleRailCreate}
          onExpand={handleExpand}
          onOpenSearch={openSearch}
        />
      )}
      {/* 移动端遮罩：点击关闭抽屉。 */}
      {mobileOpen && (
        <div className="fixed inset-0 z-30 bg-black/40 md:hidden" onClick={onCloseMobile} aria-hidden="true" />
      )}
      <nav
        aria-label="主导航"
        className={`fixed inset-y-0 left-0 z-40 flex w-60 shrink-0 flex-col border-r border-border bg-sidebar p-3 transition-transform duration-200 md:static md:z-auto md:translate-x-0 ${
          collapsed ? "md:hidden" : ""
        } ${mobileOpen ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className="mb-2 flex justify-end md:hidden">
          <button
            type="button"
            aria-label="关闭导航"
            onClick={onCloseMobile}
            className="rounded-lg p-1.5 text-text-secondary hover:bg-surface"
          >
            <XIcon />
          </button>
        </div>
        <SidebarHeader onOpenSearch={openSearch} onToggleCollapse={onToggleCollapse} />
        <NewTaskButton busy={busy} error={error} onCreate={() => void create()} />
        <Link href="/agents" onClick={onCloseMobile} className={navLinkCls}>
          <SparklesIcon />
          Agent
        </Link>
        <Link href="/skills" onClick={onCloseMobile} className={navLinkCls}>
          <PuzzleIcon />
          技能
        </Link>
        <Link href="/eval" onClick={onCloseMobile} className={navLinkCls}>
          <ChartBarIcon />
          Agent 评估
        </Link>
        <Link href="/agentrl" onClick={onCloseMobile} className={navLinkCls}>
          <BeakerIcon />
          AgentRL
        </Link>
        <Link href="/deepresearch" onClick={onCloseMobile} className={navLinkCls}>
          <TelescopeIcon />
          DeepResearch
        </Link>
        <Link href="/mcp" onClick={onCloseMobile} className={navLinkCls}>
          <PlugIcon />
          MCP
        </Link>
        <hr className="my-3 border-border" />
        <TaskList />
      </nav>
      <SearchModal open={searchOpen} onClose={closeSearch} />
    </>
  );
}
