import { listSkills } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function SkillsPage() {
  let payload;
  try {
    payload = await listSkills();
  } catch {
    return <p className="p-6 text-sm text-text-secondary">聊天 API 不可达，无法读取技能列表。</p>;
  }
  if (!payload.reachable) {
    return <p className="p-6 text-sm text-text-secondary">技能服务未启动，对话将不带技能运行。</p>;
  }
  return (
    <section className="p-6">
      <h1 className="mb-4 text-xl font-semibold">技能</h1>
      <ul className="grid gap-3">
        {payload.skills.map((skill) => (
          <li key={skill.name} className="rounded-lg border border-border bg-white p-4">
            <p className="text-sm font-medium">{skill.name}</p>
            <p className="mt-1 text-sm text-text-secondary">{skill.description}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
