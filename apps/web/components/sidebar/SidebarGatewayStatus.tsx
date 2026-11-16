"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { getSharingConfig, type SharingConfig } from "@/lib/m7-api";

const GATEWAY_URL =
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://127.0.0.1:3421";

export function SidebarGatewayStatus({ onNavigate }: { onNavigate: () => void }) {
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [config, setConfig] = useState<SharingConfig | null>(null);

  useEffect(() => {
    let active = true;
    Promise.allSettled([
      fetch(`${GATEWAY_URL}/health`, { cache: "no-store" }).then((response) => {
        if (!response.ok) throw new Error("gateway unavailable");
        return response.json();
      }),
      getSharingConfig(),
    ]).then(([health, sharing]) => {
      if (!active) return;
      setHealthy(health.status === "fulfilled");
      setConfig(sharing.status === "fulfilled" ? sharing.value : null);
    });
    return () => {
      active = false;
    };
  }, []);

  const displayUrl = GATEWAY_URL.replace(/^https?:\/\//, "");
  const [defaultHost, defaultPort] = displayUrl.split(":");
  const displayHost =
    config?.enabled ? config.bind_host : defaultHost;
  const displayPort =
    config?.enabled ? config.port : defaultPort;
  const statusLabel =
    healthy === null ? "检测中" : healthy ? "网关运行中" : "网关未连接";

  return (
    <Link
      href="/gateway"
      onClick={onNavigate}
      className="mt-auto rounded-lg border border-border bg-surface/60 px-3 py-2 hover:bg-surface"
    >
      <span className="flex items-center gap-2 text-xs text-text-secondary">
        <span
          className={`h-2 w-2 rounded-full ${
            healthy ? "bg-emerald-500" : healthy === false ? "bg-red-500" : "bg-amber-500"
          }`}
        />
        {statusLabel}
      </span>
      <span className="mt-1 block truncate font-mono text-[11px] text-text-secondary">
        {displayHost}:{displayPort}
      </span>
    </Link>
  );
}
