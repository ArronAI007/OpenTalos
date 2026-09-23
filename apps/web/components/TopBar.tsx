"use client";

import { useEffect, useState } from "react";
import { fetchConfig, type AppConfig } from "@/lib/api";
import { AGENT_TYPE_KEY, DEFAULT_AGENT_TYPE } from "@/lib/agent-type";

const AGENT_TYPE_LABELS: Record<string, string> = {
  toolcall: "原生函数调用，最快",
  react: "边推理边行动（经典 ReAct）",
  reflection: "自我评估再修正",
  plan_execute: "先规划后执行",
};

export function TopBar() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [agentType, setAgentType] = useState(DEFAULT_AGENT_TYPE);

  useEffect(() => {
    const saved = localStorage.getItem(AGENT_TYPE_KEY);
    // 挂载后再读取 localStorage（SSR 阶段不可用），避免与首屏渲染水合不一致。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (saved) setAgentType(saved);
    void fetchConfig().then(setConfig).catch(() => undefined);
  }, []);

  const handleChange = (value: string) => {
    setAgentType(value);
    localStorage.setItem(AGENT_TYPE_KEY, value);
  };

  return (
    <header className="flex items-center justify-between border-b border-border px-4 py-2.5">
      <label className="flex items-center gap-2 text-sm">
        <select
          value={agentType}
          onChange={(e) => handleChange(e.target.value)}
          className="rounded-lg border border-border bg-white px-2 py-1 text-sm font-medium"
          aria-label="agent 类型"
        >
          {(config?.agent_types ?? Object.keys(AGENT_TYPE_LABELS)).map((t) => (
            <option key={t} value={t}>{t}{AGENT_TYPE_LABELS[t] ? ` · ${AGENT_TYPE_LABELS[t]}` : ""}</option>
          ))}
        </select>
      </label>
      <span className="text-xs text-text-secondary">{config?.model_name ?? "模型未配置"}</span>
    </header>
  );
}
