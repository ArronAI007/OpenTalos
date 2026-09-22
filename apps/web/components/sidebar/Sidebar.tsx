import Link from "next/link";
import { NewTaskButton, TaskList } from "./SidebarClient";

export function Sidebar() {
  return (
    <nav aria-label="主导航" className="flex w-60 shrink-0 flex-col border-r border-border bg-sidebar p-3">
      <NewTaskButton />
      <Link href="/agents" className="rounded-lg px-3 py-2 text-sm hover:bg-white">◈ Agent</Link>
      <Link href="/skills" className="rounded-lg px-3 py-2 text-sm hover:bg-white">🧩 技能</Link>
      <hr className="my-3 border-border" />
      <TaskList />
    </nav>
  );
}
