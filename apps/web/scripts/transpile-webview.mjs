import { createHash } from "node:crypto";
import { readdir, readFile, unlink, writeFile } from "node:fs/promises";
import path from "node:path";

import babel from "next/dist/compiled/babel/core.js";
import presetEnv from "next/dist/compiled/babel/preset-env.js";

const webRoot = path.resolve(import.meta.dirname, "..");
const nextRoot = path.join(webRoot, ".next");
const staticRoot = path.join(nextRoot, "static");

async function walk(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const candidate = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await walk(candidate)));
    } else if (entry.isFile()) {
      files.push(candidate);
    }
  }
  return files;
}

function toPosix(value) {
  return value.split(path.sep).join("/");
}

const replacements = new Map();
const scripts = (await walk(staticRoot)).filter((file) => file.endsWith(".js"));

for (const filename of scripts) {
  let source = await readFile(filename, "utf8");
  // remark-gfm includes a redundant lookbehind around email autolinks. macOS 12
  // WebKit rejects the entire bundle at parse time; its callback already checks
  // the preceding character, so the lookbehind can be removed safely.
  source = source.replace(
    "(?<=^|\\s|\\p{P}|\\p{S})([-.\\w+]+)@",
    "([-.\\w+]+)@",
  );
  const result = babel.transformSync(source, {
    filename,
    sourceType: "unambiguous",
    babelrc: false,
    configFile: false,
    comments: false,
    compact: true,
    minified: true,
    sourceMaps: false,
    presets: [
      [
        presetEnv,
        {
          bugfixes: true,
          modules: false,
          targets: { safari: "14.1" },
        },
      ],
    ],
  });
  if (!result?.code) {
    throw new Error(`Babel did not produce output for ${filename}`);
  }

  const relativeOld = toPosix(path.relative(staticRoot, filename));
  const digest = createHash("sha256").update(result.code).digest("hex").slice(0, 12);
  const parsed = path.posix.parse(relativeOld);
  const relativeNew = path.posix.join(
    parsed.dir,
    `${parsed.name}-wv.${digest}${parsed.ext}`,
  );
  const target = path.join(staticRoot, relativeNew);

  await writeFile(target, result.code);
  await unlink(filename);
  replacements.set(relativeOld, relativeNew);
}

const replacementTargets = [
  ...(await walk(staticRoot)),
  ...(await walk(path.join(nextRoot, "server"))),
];
const standaloneRoot = path.join(nextRoot, "standalone");
try {
  replacementTargets.push(...(await walk(standaloneRoot)));
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
for (const entry of await readdir(nextRoot, { withFileTypes: true })) {
  if (entry.isFile()) {
    replacementTargets.push(path.join(nextRoot, entry.name));
  }
}

for (const filename of replacementTargets) {
  const data = await readFile(filename);
  let text;
  try {
    text = data.toString("utf8");
  } catch {
    continue;
  }

  let updated = text;
  for (const [oldPath, newPath] of replacements) {
    updated = updated.split(oldPath).join(newPath);
  }
  if (updated !== text) {
    await writeFile(filename, updated);
  }
}

console.log(
  `Prepared ${replacements.size} WebKit-compatible chunks with versioned filenames.`,
);
