export function filterSkills<T extends { name: string; description: string }>(
  skills: T[], query: string
): T[] {
  const q = query.trim().toLowerCase();
  if (q === "") return skills;
  return skills.filter(
    (skill) => skill.name.toLowerCase().includes(q) || skill.description.toLowerCase().includes(q)
  );
}

export function filterSkillsByCategory<T extends { tags: string[] }>(skills: T[], category: string): T[] {
  if (category === "全部") return skills;
  return skills.filter((skill) => skill.tags.includes(category));
}
