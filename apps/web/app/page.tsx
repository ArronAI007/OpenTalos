import { HomeComposer } from "@/components/chat/HomeComposer";

export default function Home() {
  return (
    <section className="flex h-full flex-col">
      <div className="flex flex-1 flex-col items-center justify-center gap-4">
        <h1 className="text-2xl font-semibold">给 OpenTalos 一个任务</h1>
        <p className="text-sm text-text-secondary">直接在下方输入，发送即开始</p>
      </div>
      <HomeComposer />
    </section>
  );
}
