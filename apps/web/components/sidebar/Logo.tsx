import Link from "next/link";

// 圆角六边形轮廓 + 内部火花形节点，单色抽象标，风格对齐 Manus 花形标。
export function LogoMark() {
  return (
    <svg viewBox="0 0 24 24" width={22} height={22} className="text-accent" aria-hidden="true">
      <path
        d="M12 4 L18.93 8 L18.93 16 L12 20 L5.07 16 L5.07 8 Z"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
        strokeLinejoin="round"
      />
      <path
        d="M12 8 L13.6 10.4 L16 12 L13.6 13.6 L12 16 L10.4 13.6 L8 12 L10.4 10.4 Z"
        fill="currentColor"
      />
    </svg>
  );
}

export function Logo() {
  return (
    <Link
      href="/"
      aria-label="OpenTalos 首页"
      className="flex items-center gap-2 rounded-lg px-1 py-1 hover:bg-white"
    >
      <LogoMark />
      <span className="text-[15px] font-semibold tracking-tight">OpenTalos</span>
    </Link>
  );
}
