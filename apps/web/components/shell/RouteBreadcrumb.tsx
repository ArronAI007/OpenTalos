"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { ServerIcon, SettingsIcon } from "@/components/ui/icons";
import { navigationItemForPath } from "@/lib/navigation";

export function RouteBreadcrumb() {
  const pathname = usePathname();
  const current = navigationItemForPath(pathname);
  if (!current) return null;

  return (
    <div className="flex h-11 shrink-0 items-center justify-between border-b border-border px-6">
      <div className="flex min-w-0 items-center gap-2 text-sm">
        <span className="text-text-secondary">{current.section}</span>
        <span className="text-text-secondary">/</span>
        <span className="truncate font-medium">{current.label}</span>
      </div>
      <div className="flex items-center gap-1">
        <Link
          href="/gateway"
          aria-label="网关状态"
          title="网关状态"
          className="rounded-lg p-1.5 text-text-secondary hover:bg-sidebar hover:text-text"
        >
          <ServerIcon width={15} height={15} />
        </Link>
        <Link
          href="/settings"
          aria-label="设置"
          title="设置"
          className="rounded-lg p-1.5 text-text-secondary hover:bg-sidebar hover:text-text"
        >
          <SettingsIcon width={15} height={15} />
        </Link>
      </div>
    </div>
  );
}
