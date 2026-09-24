import type { ReactNode } from "react";

// 原生 title 提示有 ~1.5s 浏览器延迟——功能键上的中文提示改用纯 CSS tooltip 即时显现。
// 命名组 group/tip：消息行外层 li 已挂匿名 group（整行 hover 显隐操作行），
// 若 tooltip 复用匿名 group-hover 会被外层的 hover 牵连常显。
// 键盘可达与鼠标一致：focus-within 同样显现。
export function Tooltip({
  label,
  hidden,
  children,
}: {
  label: string;
  hidden?: boolean; // 关联浮层打开时压制（如 ⋯ 菜单展开期间，避免 tooltip 盖在菜单上）
  children: ReactNode;
}) {
  return (
    <span className="group/tip relative inline-flex">
      {children}
      <span
        role="tooltip"
        className={`pointer-events-none absolute bottom-full left-1/2 z-20 mb-1 -translate-x-1/2 rounded-md bg-text px-1.5 py-0.5 text-xs whitespace-nowrap text-surface opacity-0 shadow-md transition-opacity duration-150 group-hover/tip:opacity-100 group-focus-within/tip:opacity-100${hidden ? " hidden" : ""}`}
      >
        {label}
      </span>
    </span>
  );
}
