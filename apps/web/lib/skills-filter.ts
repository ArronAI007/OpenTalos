export function filterSkills<T extends { name: string; description: string }>(
  skills: T[], query: string
): T[] {
  const q = query.trim().toLowerCase();
  if (q === "") return skills;
  return skills.filter(
    (skill) => skill.name.toLowerCase().includes(q) || skill.description.toLowerCase().includes(q)
  );
}
