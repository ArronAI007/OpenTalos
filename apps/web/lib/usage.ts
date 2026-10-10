export interface UsageInfo {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  cost?: number;
}

// "1,234 tokens · $0.0034"；既无 token 也无 cost 时返回空串（调用方据此不渲染）。
export function formatUsage(usage: UsageInfo | undefined): string {
  if (!usage) return "";
  const parts: string[] = [];
  if (usage.total_tokens) parts.push(`${usage.total_tokens.toLocaleString()} tokens`);
  if (usage.cost !== undefined) parts.push(`$${usage.cost.toFixed(4)}`);
  return parts.join(" · ");
}
