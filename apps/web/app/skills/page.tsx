"use client";

import { useEffect, useState } from "react";
import { listSkills, type SkillsResponse } from "@/lib/api";
import { filterSkills } from "@/lib/skills-filter";
import { skillCardTint } from "@/lib/skills-color";
import { GithubIcon, PuzzleIcon, SearchIcon } from "@/components/ui/icons";
import { GithubImportModal } from "@/components/skills/GithubImportModal";

const CATEGORY_TABS = ["全部", "编程", "数据", "自动化", "商业", "设计", "媒体", "内容"];

export default function SkillsPage() {
  const [payload, setPayload] = useState<SkillsResponse | null>(null);
  const [query, setQuery] = useState("");
  const [importOpen, setImportOpen] = useState(false);

  const refresh = () => {
    listSkills()
      .then(setPayload)
      .catch(() => setPayload({ reachable: false, skills: [], error: "聊天 API 不可达，无法读取技能列表。" }));
  };

  useEffect(() => {
    refresh();
  }, []);

  if (payload === null) return null;

  if (!payload.reachable) {
    return (
      <p className="p-6 text-sm text-text-secondary">
        {payload.error ?? "技能服务未启动，对话将不带技能运行。"}
      </p>
    );
  }

  const filtered = filterSkills(payload.skills, query);

  return (
    <section className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">技能</h1>
        <button
          type="button"
          onClick={() => setImportOpen(true)}
          className="flex items-center gap-1.5 rounded-lg border border-border bg-white px-3 py-1.5 text-sm font-medium hover:bg-gray-50"
        >
          <GithubIcon width={16} height={16} />
          从 GitHub 导入
        </button>
      </div>

      <div className="mb-4 flex items-center gap-2 rounded-lg border border-border bg-white px-3 py-2">
        <SearchIcon width={16} height={16} className="shrink-0 text-text-secondary" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索技能"
          aria-label="搜索技能"
          className="w-full bg-transparent text-sm outline-none placeholder:text-text-secondary"
        />
      </div>

      <div className="mb-6 flex flex-wrap gap-2">
        {CATEGORY_TABS.map((tab) =>
          tab === "全部" ? (
            <span key={tab} className="rounded-full bg-text px-3 py-1 text-sm font-medium text-white">
              {tab}
            </span>
          ) : (
            <span
              key={tab}
              aria-disabled="true"
              className="cursor-not-allowed rounded-full px-3 py-1 text-sm text-text-secondary/50"
            >
              {tab}
            </span>
          )
        )}
      </div>

      {filtered.length === 0 ? (
        <p className="text-sm text-text-secondary">
          {query.trim() === "" ? "还没有技能。" : "没有匹配的技能。"}
        </p>
      ) : (
        <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {filtered.map((skill) => {
            const tint = skillCardTint(skill.name);
            return (
              <li key={skill.name} className="overflow-hidden rounded-xl border border-border bg-white">
                <div className={`flex h-24 items-center justify-center ${tint.bg}`}>
                  <PuzzleIcon width={32} height={32} className={tint.icon} />
                </div>
                <div className="p-3">
                  <p className="text-sm font-medium">{skill.name}</p>
                  <p className="mt-1 line-clamp-2 text-xs text-text-secondary">{skill.description}</p>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <GithubImportModal open={importOpen} onClose={() => setImportOpen(false)} onImported={refresh} />
    </section>
  );
}
