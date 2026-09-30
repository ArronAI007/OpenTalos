"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/sidebar/Sidebar";
import { TopBar } from "@/components/TopBar";

const SIDEBAR_COLLAPSED_KEY = "opentalos.sidebarCollapsed";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();
  // TopBar 是"下一次新建任务用什么 agent 类型"的全局偏好选择器（HomeComposer 和侧栏
  // "新建任务"都读它），只在会用到它的页面显示：首页（创建新任务）和任务页（查看当前任务）；
  // /agents /skills /eval 等管理页与"新建任务"无关，不显示。
  const showTopBar = pathname === "/" || pathname.startsWith("/t/");

  useEffect(() => {
    const saved = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    // 挂载后再读取 localStorage（SSR 阶段不可用），避免与首屏渲染水合不一致。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (saved === "1") setCollapsed(true);
  }, []);

  const toggleCollapse = () => {
    const next = !collapsed;
    setCollapsed(next);
    // 折叠时写 "1"、展开时删除，刷新后按上次偏好恢复。
    if (next) localStorage.setItem(SIDEBAR_COLLAPSED_KEY, "1");
    else localStorage.removeItem(SIDEBAR_COLLAPSED_KEY);
  };

  return (
    <>
      <Sidebar collapsed={collapsed} onToggleCollapse={toggleCollapse} />
      <div className="flex min-w-0 flex-1 flex-col">
        {showTopBar && <TopBar />}
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </>
  );
}
