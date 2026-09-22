const TYPES = [
  { key: "toolcall", name: "ToolCalling", desc: "原生函数调用，省 token、速度快，适合工具链路明确的任务。" },
  { key: "react", name: "ReAct", desc: "推理与行动交错，兼容不支持函数调用的模型，通用性最好。" },
  { key: "reflection", name: "Reflection", desc: "先答后评再改，适合对质量敏感的开放式任务。" },
  { key: "plan_execute", name: "PlanExecute", desc: "先产出结构化计划再逐步执行，适合多步骤长任务。" },
];

export default function AgentsPage() {
  return (
    <section className="p-6">
      <h1 className="mb-4 text-xl font-semibold">Agent 类型</h1>
      <p className="mb-4 text-sm text-text-secondary">在顶栏下拉中切换当前类型，新建任务将使用该类型。</p>
      <ul className="grid gap-3">
        {TYPES.map((t) => (
          <li key={t.key} className="rounded-lg border border-border bg-white p-4">
            <p className="text-sm font-medium">{t.key}</p>
            <p className="mt-1 text-sm text-text-secondary"><strong>{t.name}</strong> — {t.desc}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
