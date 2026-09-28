"use client";

import { useEffect, useState } from "react";
import { listSkills, addMySkill, removeMySkill, type SkillsResponse } from "@/lib/api";
import { filterSkills } from "@/lib/skills-filter";
import { skillCardTint } from "@/lib/skills-color";
import { CheckIcon, GithubIcon, PuzzleIcon, SearchIcon } from "@/components/ui/icons";
import { GithubImportModal } from "@/components/skills/GithubImportModal";

const CATEGORY_TABS = ["全部", "编程", "数据", "自动化", "商业", "设计", "媒体", "内容"];

export default function SkillsPage() {
  const [payload, setPayload] = useState<SkillsResponse | null>(null);
  const [query, setQuery] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [myOnly, setMyOnly] = useState(false);

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

  const handleToggleAdded = async (name: string, currentlyAdded: boolean) => {
    // 乐观更新：先翻转本地状态，请求失败再翻回去。
    setPayload((prev) =>
      prev
        ? { ...prev, skills: prev.skills.map((s) => (s.name === name ? { ...s, added: !currentlyAdded } : s)) }
        : prev
    );
    try {
      if (currentlyAdded) {
        await removeMySkill(name);
      } else {
        await addMySkill(name);
      }
    } catch {
      setPayload((prev) =>
        prev
          ? { ...prev, skills: prev.skills.map((s) => (s.name === name ? { ...s, added: currentlyAdded } : s)) }
          : prev
      );
    }
  };

  const searched = filterSkills(payload.skills, query);
  const filtered = myOnly ? searched.filter((s) => s.added) : searched;

  return (
    <section className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">技能</h1>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setMyOnly((v) => !v)}
            className="rounded-lg border border-border bg-white px-3 py-1.5 text-sm font-medium hover:bg-gray-50"
          >
            {myOnly ? "全部技能" : "我的技能"}
          </button>
          <button
            type="button"
            onClick={() => setImportOpen(true)}
            className="flex items-center gap-1.5 rounded-lg border border-border bg-white px-3 py-1.5 text-sm font-medium hover:bg-gray-50"
          >
            <GithubIcon width={16} height={16} />
            从 GitHub 导入
          </button>
        </div>
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
          {myOnly ? "还没有添加任何技能。" : query.trim() === "" ? "还没有技能。" : "没有匹配的技能。"}
        </p>
      ) : (
        <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {filtered.map((skill) => {
            const tint = skillCardTint(skill.name);
            return (
              <li key={skill.name} className="group relative rounded-xl border border-border bg-white">
                <div className={`flex h-24 items-center justify-center overflow-hidden rounded-t-xl ${tint.bg}`}>
                  <PuzzleIcon width={32} height={32} className={tint.icon} />
                </div>
                <div className="p-3">
                  <p className="text-sm font-medium">{skill.name}</p>
                  <p className="mt-1 line-clamp-2 text-xs text-text-secondary">{skill.description}</p>
                </div>

                {/* tooltip 相对整张卡片居中，而不是相对按钮居中——按钮贴在右下角，
                    如果 tooltip 跟着按钮居中会贴着卡片右边缘，容易被右侧相邻卡片盖住。 */}
                <span
                  role="tooltip"
                  className="pointer-events-none absolute bottom-12 left-1/2 z-20 -translate-x-1/2 whitespace-nowrap rounded-md bg-text px-1.5 py-0.5 text-xs text-surface opacity-0 shadow-md transition-opacity duration-150 group-hover:opacity-100"
                >
                  {skill.added ? "从我的技能移除" : "添加到我的技能"}
                </span>
                <button
                  type="button"
                  aria-label={skill.added ? `从我的技能移除 ${skill.name}` : `添加 ${skill.name} 到我的技能`}
                  onClick={() => void handleToggleAdded(skill.name, skill.added)}
                  className="absolute bottom-3 right-3 flex h-7 w-7 items-center justify-center rounded-lg border border-border bg-white text-lg leading-none text-text opacity-0 transition-opacity hover:bg-gray-50 group-hover:opacity-100"
                >
                  {skill.added ? <CheckIcon width={14} height={14} /> : "+"}
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <GithubImportModal open={importOpen} onClose={() => setImportOpen(false)} onImported={refresh} />
    </section>
  );
}
