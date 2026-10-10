"use client";

import { useEffect, useState } from "react";
import { MoonIcon, SunIcon } from "@/components/ui/icons";

const THEME_KEY = "opentalos.theme";

// 深色/浅色切换：写 localStorage + 切 <html> 的 .dark 类（首屏由 layout 内联脚本预置，避免闪烁）。
export function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 挂载后读 DOM 上的实际主题（SSR 不可用）
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem(THEME_KEY, next ? "dark" : "light");
    } catch {
      // 隐私模式等 localStorage 不可用时静默忽略，仅本次会话生效。
    }
  };

  const label = dark ? "切换到浅色主题" : "切换到深色主题";
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={toggle}
      className="rounded-lg p-1.5 text-text-secondary hover:bg-surface hover:text-text"
    >
      {dark ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}
