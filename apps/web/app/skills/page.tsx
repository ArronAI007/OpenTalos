"use client";

import { useEffect, useState } from "react";
import { listSkills, addMySkill, removeMySkill, type SkillsResponse } from "@/lib/api";
import { filterSkills, filterSkillsByCategory } from "@/lib/skills-filter";
import { SearchIcon } from "@/components/ui/icons";
import { PageSkeleton } from "@/components/ui/PageSkeleton";
import { CreateSkillMenu } from "@/components/skills/CreateSkillMenu";
import { SkillCard } from "@/components/skills/SkillCard";
import { MyAddedSkillsModal } from "@/components/skills/MyAddedSkillsModal";

const CATEGORY_TABS = ["全部", "编程", "数据", "自动化", "商业", "设计", "媒体", "内容"];

export default function SkillsPage() {
  const [payload, setPayload] = useState<SkillsResponse | null>(null);
  const [query, setQuery] = useState("");
  const [myAddedOpen, setMyAddedOpen] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState("全部");

  const refresh = () => {
    listSkills()
      .then(setPayload)
      .catch(() => setPayload({ reachable: false, skills: [], error: "聊天 API 不可达，无法读取技能列表。" }));
  };

  useEffect(() => {
    refresh();
  }, []);

  if (payload === null) return <PageSkeleton />;

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
  const filtered = filterSkillsByCategory(searched, selectedCategory);

  return (
    <section className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">技能</h1>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setMyAddedOpen(true)}
            className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm font-medium hover:bg-gray-50"
          >
            我的技能
          </button>
          <CreateSkillMenu onImported={refresh} />
        </div>
      </div>

      <div className="mb-4 flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2">
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
          {payload.skills.length === 0 ? "还没有技能。" : "没有匹配的技能。"}
        </p>
      ) : (
        <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {filtered.map((skill) => (
            <SkillCard key={skill.name} skill={skill} onToggleAdded={handleToggleAdded} />
          ))}
        </ul>
      )}

      <MyAddedSkillsModal
        open={myAddedOpen}
        onClose={() => setMyAddedOpen(false)}
        skills={payload.skills}
        onToggleAdded={handleToggleAdded}
        onImported={refresh}
      />
    </section>
  );
}
