export function parseEnvLines(text: string): Record<string, string> | undefined {
  const entries = text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const idx = line.indexOf("=");
      return idx > 0 ? [line.slice(0, idx), line.slice(idx + 1)] : null;
    })
    .filter((pair): pair is [string, string] => pair !== null);
  return entries.length > 0 ? Object.fromEntries(entries) : undefined;
}
