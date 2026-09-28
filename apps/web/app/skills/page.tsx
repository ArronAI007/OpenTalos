"use client";

import { useEffect, useState } from "react";
import { listSkills, addMySkill, removeMySkill, type SkillsResponse } from "@/lib/api";
import { filterSkills, filterSkillsByCategory } from "@/lib/skills-filter";
import { skillCardTint } from "@/lib/skills-color";
import { CheckIcon, PuzzleIcon, SearchIcon } from "@/components/ui/icons";
import { CreateSkillMenu } from "@/components/skills/CreateSkillMenu";
import { Tooltip } from "@/components/ui/Tooltip";
import { LogoMark } from "@/components/sidebar/Logo";

const CATEGORY_TABS = ["全部", "编程", "数据", "自动化", "商业", "设计", "媒体", "内容"];

export default function SkillsPage() {
  const [payload, setPayload] = useState<SkillsResponse | null>(null);
  const [query, setQuery] = useState("");
  const [myOnly, setMyOnly] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState("全部");

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
  const categoryFiltered = filterSkillsByCategory(searched, selectedCategory);
  const filtered = myOnly ? categoryFiltered.filter((s) => s.added) : categoryFiltered;

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
          <CreateSkillMenu onImported={refresh} />
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
        {CATEGORY_TABS.map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setSelectedCategory(tab)}
            className={
              tab === selectedCategory
                ? "rounded-full bg-text px-3 py-1 text-sm font-medium text-white"
                : "rounded-full px-3 py-1 text-sm text-text-secondary hover:bg-gray-100"
            }
          >
            {tab}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <p className="text-sm text-text-secondary">
          {payload.skills.length === 0
            ? "还没有技能。"
            : myOnly
            ? "还没有添加任何技能。"
            : "没有匹配的技能。"}
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
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <span className="flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-text-secondary">
                      <LogoMark size={12} />
                      OpenTalos
                    </span>
                    {skill.tags.map((tag) => (
                      <span key={tag} className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-text-secondary">
                        {tag}
                      </span>
                    ))}
                  </div>
                  <p className="mt-2 text-xs text-text-secondary">已使用 {skill.usage_count} 次</p>
                </div>

                {/* tooltip 相对按钮本身居中（Tooltip 组件内部用 relative inline-flex 包住
                    children，tooltip 以 left-1/2 对齐这个包裹层，天然跟着按钮走）。 */}
                <div className="absolute bottom-3 right-3 opacity-0 transition-opacity group-hover:opacity-100">
                  <Tooltip label={skill.added ? "从我的技能移除" : "添加到我的技能"}>
                    <button
                      type="button"
                      aria-label={skill.added ? `从我的技能移除 ${skill.name}` : `添加 ${skill.name} 到我的技能`}
                      onClick={() => void handleToggleAdded(skill.name, skill.added)}
                      className="flex h-7 w-7 items-center justify-center rounded-lg border border-border bg-white text-lg leading-none text-text hover:bg-gray-50"
                    >
                      {skill.added ? <CheckIcon width={14} height={14} /> : "+"}
                    </button>
                  </Tooltip>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
