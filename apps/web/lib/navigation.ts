export type NavigationIcon =
  | "agent"
  | "conversation"
  | "library"
  | "provider"
  | "route"
  | "routeGroups"
  | "gateway"
  | "usage"
  | "privacy"
  | "plugins";

export interface NavigationItem {
  href: string;
  label: string;
  icon: NavigationIcon;
}

export interface NavigationGroup {
  id: string;
  label?: string;
  items: NavigationItem[];
}

export const NAVIGATION_GROUPS: NavigationGroup[] = [
  {
    id: "use",
    label: "使用",
    items: [
      { href: "/agents", label: "Agent", icon: "agent" },
      { href: "/conversations", label: "会话", icon: "conversation" },
      { href: "/resources", label: "资源库", icon: "library" },
    ],
  },
  {
    id: "models",
    label: "模型",
    items: [
      { href: "/providers", label: "供应商", icon: "provider" },
      { href: "/routing", label: "路由", icon: "route" },
      { href: "/routing-groups", label: "路由组", icon: "routeGroups" },
      { href: "/gateway", label: "网关", icon: "gateway" },
    ],
  },
  {
    id: "observability",
    label: "观测",
    items: [
      { href: "/usage", label: "用量", icon: "usage" },
      { href: "/privacy", label: "脱敏", icon: "privacy" },
    ],
  },
  {
    id: "extensions",
    label: "扩展",
    items: [{ href: "/plugins", label: "插件", icon: "plugins" }],
  },
];

export const SETTINGS_NAV_ITEM = {
  href: "/settings",
  label: "设置",
} as const;

export const LEGACY_NAV_ITEMS = [
  { href: "/skills", label: "Skills" },
  { href: "/mcp", label: "MCP" },
  { href: "/memory", label: "记忆" },
  { href: "/runs", label: "运行记录" },
  { href: "/eval", label: "Agent 评估" },
  { href: "/agentrl", label: "AgentRL" },
  { href: "/deepresearch", label: "DeepResearch" },
] as const;

export function navigationItemForPath(pathname: string): {
  section: string;
  label: string;
} | null {
  if (pathname === SETTINGS_NAV_ITEM.href) {
    return { section: "设置", label: SETTINGS_NAV_ITEM.label };
  }
  for (const group of NAVIGATION_GROUPS) {
    const item = group.items.find(
      (candidate) =>
        pathname === candidate.href ||
        pathname.startsWith(`${candidate.href}/`)
    );
    if (item) {
      return {
        section: group.label ?? "使用",
        label: item.label,
      };
    }
  }
  const legacy = LEGACY_NAV_ITEMS.find(
    (item) =>
      pathname === item.href || pathname.startsWith(`${item.href}/`)
  );
  if (legacy) {
    return { section: "高级功能", label: legacy.label };
  }
  if (pathname === "/security") {
    return { section: "高级功能", label: "安全与共享" };
  }
  return null;
}
