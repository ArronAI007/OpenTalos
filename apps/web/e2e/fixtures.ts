import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const FIXTURE_PATH = path.join(import.meta.dirname, ".fixture-api-key.json");

export function writeFixtureApiKey(rawKey: string): void {
  writeFileSync(FIXTURE_PATH, JSON.stringify({ rawKey }));
}

export function readFixtureApiKey(): string {
  const content = readFileSync(FIXTURE_PATH, "utf-8");
  return (JSON.parse(content) as { rawKey: string }).rawKey;
}
