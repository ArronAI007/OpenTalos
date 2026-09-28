import { CheckIcon, PuzzleIcon } from "@/components/ui/icons";
import { Tooltip } from "@/components/ui/Tooltip";
import { LogoMark } from "@/components/sidebar/Logo";
import { skillCardTint } from "@/lib/skills-color";
import type { SkillSummary } from "@/lib/api";

interface SkillCardProps {
  skill: SkillSummary;
  onToggleAdded: (name: string, currentlyAdded: boolean) => void | Promise<void>;
}

export function SkillCard({ skill, onToggleAdded }: SkillCardProps) {
  const tint = skillCardTint(skill.name);
  return (
    <li className="group relative rounded-xl border border-border bg-white">
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
            onClick={() => void onToggleAdded(skill.name, skill.added)}
            className="flex h-7 w-7 items-center justify-center rounded-lg border border-border bg-white text-lg leading-none text-text hover:bg-gray-50"
          >
            {skill.added ? <CheckIcon width={14} height={14} /> : "+"}
          </button>
        </Tooltip>
      </div>
    </li>
  );
}
