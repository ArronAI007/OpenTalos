export interface SkillCardTint {
  bg: string;
  icon: string;
}

// 固定的柔和色板：技能没有真实封面图时，用名字哈希出一个稳定的色块，
// 保证同一个技能每次渲染颜色一致，不同技能大概率不同色。
const CARD_TINTS: SkillCardTint[] = [
  { bg: "bg-indigo-50", icon: "text-indigo-500" },
  { bg: "bg-rose-50", icon: "text-rose-500" },
  { bg: "bg-amber-50", icon: "text-amber-600" },
  { bg: "bg-emerald-50", icon: "text-emerald-500" },
  { bg: "bg-sky-50", icon: "text-sky-500" },
  { bg: "bg-violet-50", icon: "text-violet-500" },
];

function hashString(value: string): number {
  let hash = 5381;
  for (let i = 0; i < value.length; i++) {
    hash = (hash * 33) ^ value.charCodeAt(i);
  }
  return Math.abs(hash);
}

export function skillCardTint(name: string): SkillCardTint {
  return CARD_TINTS[hashString(name) % CARD_TINTS.length];
}
