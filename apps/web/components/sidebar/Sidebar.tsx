import Link from "next/link";

export function Sidebar() {
  return (
    <nav aria-label="主导航" className="flex w-60 shrink-0 flex-col border-r border-border bg-sidebar p-3">
      <Link
        href="/"
        className="mb-2 rounded-lg border border-border bg-white px-3 py-2 text-sm font-medium hover:border-text-secondary"
      >
        ＋ 新建任务
      </Link>
      <Link href="/agents" className="rounded-lg px-3 py-2 text-sm hover:bg-white">◈ Agent</Link>
      <Link href="/skills" className="rounded-lg px-3 py-2 text-sm hover:bg-white">🧩 技能</Link>
      <hr className="my-3 border-border" />
      <section aria-label="任务历史" className="flex-1 overflow-y-auto">
        <p className="px-3 py-1 text-xs text-text-secondary">任务历史</p>
      </section>
    </nav>
  );
}
