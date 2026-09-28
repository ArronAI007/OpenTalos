"use client";

import { useEffect, useState } from "react";
import type { SkillSummary } from "@/lib/api";
import { filterSkills } from "@/lib/skills-filter";
import { PuzzleIcon, SearchIcon } from "@/components/ui/icons";
import { SkillCard } from "@/components/skills/SkillCard";
import { CreateSkillMenu } from "@/components/skills/CreateSkillMenu";

interface MyAddedSkillsModalProps {
  open: boolean;
  onClose: () => void;
  skills: SkillSummary[];
  onToggleAdded: (name: string, currentlyAdded: boolean) => void | Promise<void>;
  onImported: () => void;
}

export function MyAddedSkillsModal({ open, onClose, skills, onToggleAdded, onImported }: MyAddedSkillsModalProps) {
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!open) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setQuery("");
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing) return;
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const added = skills.filter((s) => s.added);
  const filtered = filterSkills(added, query);

  return (
    <div role="dialog" aria-modal="true" aria-label="已添加的技能" className="fixed inset-0 z-50 overflow-y-auto bg-sidebar">
      <button
        type="button"
        aria-label="关闭"
        onClick={onClose}
        className="absolute right-6 top-6 text-text-secondary hover:text-text"
      >
        ✕
      </button>

      <div className="mx-auto max-w-5xl px-8 py-10">
        <h2 className="text-2xl font-semibold">已添加的技能</h2>
        <div className="mt-4 border-b border-border" />

        <div className="mt-6 flex items-center gap-3">
          <div className="flex flex-1 items-center gap-2 rounded-lg border border-border bg-white px-3 py-2">
            <SearchIcon width={16} height={16} className="shrink-0 text-text-secondary" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索技能"
              aria-label="搜索已添加的技能"
              className="w-full bg-transparent text-sm outline-none placeholder:text-text-secondary"
            />
          </div>
          <CreateSkillMenu onImported={onImported} label="创建" />
        </div>

        {filtered.length === 0 ? (
          <div className="mt-24 flex flex-col items-center gap-3">
            <PuzzleIcon width={40} height={40} className="text-text-secondary" />
            <p className="text-sm text-text-secondary">{added.length === 0 ? "尚无技能" : "没有匹配的技能。"}</p>
            {added.length === 0 && <CreateSkillMenu onImported={onImported} label="创建" />}
          </div>
        ) : (
          <ul className="mt-8 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {filtered.map((skill) => (
              <SkillCard key={skill.name} skill={skill} onToggleAdded={onToggleAdded} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
