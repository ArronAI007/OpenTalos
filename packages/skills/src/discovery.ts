import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

export interface Skill {
  name: string;
  description: string;
  /** The full raw Markdown content, including frontmatter — returned verbatim by load_skill. */
  content: string;
  /** Absolute path to this skill's own directory, used to resolve/validate script paths. */
  dir: string;
}

const FRONTMATTER_PATTERN = /^---\r?\n([\s\S]*?)\r?\n---/;

/** Deliberately not a full YAML parser — the frontmatter contract here is exactly two flat
 * string fields (name, description), so a line-based `key: value` scan is sufficient and avoids
 * adding a new dependency for a format this constrained. */
function parseFrontmatter(raw: string): Record<string, string> | undefined {
  const match = FRONTMATTER_PATTERN.exec(raw);
  if (!match) return undefined;
  const fields: Record<string, string> = {};
  for (const line of match[1].split(/\r?\n/)) {
    const separatorIndex = line.indexOf(":");
    if (separatorIndex === -1) continue;
    const key = line.slice(0, separatorIndex).trim();
    const value = line.slice(separatorIndex + 1).trim();
    if (key) fields[key] = value;
  }
  return fields;
}

/** Scans immediate subdirectories of `skillsRootDir` for a SKILL.md each. A directory with a
 * malformed or missing-required-field SKILL.md is skipped with a logged warning, not a thrown
 * error — one bad skill must not prevent every other skill, or the whole agent, from starting. */
export function loadSkills(skillsRootDir: string): Skill[] {
  if (!existsSync(skillsRootDir)) return [];

  const skills: Skill[] = [];
  for (const entry of readdirSync(skillsRootDir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const dir = resolve(skillsRootDir, entry.name);
    const skillMdPath = join(dir, "SKILL.md");
    if (!existsSync(skillMdPath)) continue;

    const content = readFileSync(skillMdPath, "utf-8");
    const frontmatter = parseFrontmatter(content);
    if (!frontmatter?.name || !frontmatter?.description) {
      console.warn(`@opentalos/skills: skipping "${dir}" — SKILL.md is missing a name or description`);
      continue;
    }

    skills.push({ name: frontmatter.name, description: frontmatter.description, content, dir });
  }
  return skills;
}
