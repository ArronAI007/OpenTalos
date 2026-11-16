"use client";

import { useState } from "react";
import type { ComponentType, SVGProps } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { SearchModal } from "@/components/search/SearchModal";
import {
  ChartBarIcon,
  KeyIcon,
  LayoutGridIcon,
  LibraryIcon,
  MessageSquareIcon,
  PuzzleIcon,
  RouteIcon,
  ServerIcon,
  SettingsIcon,
  ShieldIcon,
  TerminalIcon,
  XIcon,
} from "@/components/ui/icons";
import {
  NAVIGATION_GROUPS,
  SETTINGS_NAV_ITEM,
  type NavigationIcon,
} from "@/lib/navigation";

import { SidebarRail, useCreateTask } from "./SidebarClient";
import { SidebarGatewayStatus } from "./SidebarGatewayStatus";
import { SidebarHeader } from "./SidebarHeader";

interface SidebarProps {
  collapsed: boolean;
  mobileOpen: boolean;
  onToggleCollapse: () => void;
  onCloseMobile: () => void;
}

const navLinkCls =
  "flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors";

const ICONS: Record<NavigationIcon, ComponentType<SVGProps<SVGSVGElement>>> = {
  agent: TerminalIcon,
  conversation: MessageSquareIcon,
  library: LibraryIcon,
  provider: KeyIcon,
  route: RouteIcon,
  routeGroups: LayoutGridIcon,
  gateway: ServerIcon,
  usage: ChartBarIcon,
  privacy: ShieldIcon,
  plugins: PuzzleIcon,
};

export function Sidebar({
  collapsed,
  mobileOpen,
  onToggleCollapse,
  onCloseMobile,
}: SidebarProps) {
  const pathname = usePathname();
  const [searchOpen, setSearchOpen] = useState(false);
  const { busy, error, create } = useCreateTask();

  const openSearch = () => setSearchOpen(true);
  const closeSearch = () => setSearchOpen(false);
  const handleRailCreate = async () => {
    const ok = await create();
    if (!ok) onToggleCollapse();
  };

  return (
    <>
      {collapsed && (
        <SidebarRail
          className="hidden md:flex"
          busy={busy}
          onCreate={handleRailCreate}
          onExpand={onToggleCollapse}
          onOpenSearch={openSearch}
        />
      )}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
          onClick={onCloseMobile}
          aria-hidden="true"
        />
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

        <div className="min-h-0 flex-1 overflow-y-auto px-0.5">
          {NAVIGATION_GROUPS.map((group, groupIndex) => (
            <div
              key={group.id}
              className={groupIndex === 0 ? "pb-2" : "border-t border-border/70 pb-2 pt-3"}
            >
              {group.label && (
                <p className="mb-1 px-2 text-[11px] font-medium text-text-secondary">
                  {group.label}
                </p>
              )}
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const Icon = ICONS[item.icon];
                  const active =
                    pathname === item.href || pathname.startsWith(`${item.href}/`);
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={onCloseMobile}
                      className={`${navLinkCls} ${
                        active
                          ? "bg-surface font-medium text-text shadow-sm"
                          : "text-text-secondary hover:bg-surface hover:text-text"
                      }`}
                    >
                      <Icon width={16} height={16} />
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        <Link
          href={SETTINGS_NAV_ITEM.href}
          onClick={onCloseMobile}
          className={`${navLinkCls} mb-2 border-t border-border pt-3 ${
            pathname === SETTINGS_NAV_ITEM.href
              ? "bg-surface font-medium text-text"
              : "text-text-secondary hover:bg-surface hover:text-text"
          }`}
        >
          <SettingsIcon width={16} height={16} />
          {SETTINGS_NAV_ITEM.label}
        </Link>
        <SidebarGatewayStatus onNavigate={onCloseMobile} />
        {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
      </nav>
      <SearchModal open={searchOpen} onClose={closeSearch} />
    </>
  );
}
