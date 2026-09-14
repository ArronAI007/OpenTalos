import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** Absolute path to this package's own bundled `skills/` directory, resolved relative to this
 * module's own location so it works correctly whether this file is running from `src/` (vitest)
 * or from `dist/` (the compiled output) — the `skills/` directory itself is a sibling of both
 * `src/` and `dist/`, never compiled or moved by tsc. */
export const BUNDLED_SKILLS_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "../skills");
