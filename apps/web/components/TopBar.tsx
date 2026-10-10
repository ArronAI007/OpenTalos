"use client";

import { useEffect, useState } from "react";
import { fetchConfig, type AppConfig } from "@/lib/api";

export function TopBar() {
  const [config, setConfig] = useState<AppConfig | null>(null);

  useEffect(() => {
    void fetchConfig().then(setConfig).catch(() => undefined);
  }, []);

  return (
    <header className="hidden items-center justify-end border-b border-border px-4 py-2.5 md:flex">
      <span className="text-xs text-text-secondary">{config?.model_name ?? "模型未配置"}</span>
    </header>
  );
}
