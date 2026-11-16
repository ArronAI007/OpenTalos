export interface ChatProviderPreset {
  key: string;
  label: string;
  backend: "anthropic" | "openai-compatible";
  baseUrl?: string;
}

export function applyChatPreset(
  preset: ChatProviderPreset
): { backend: "anthropic" | "openai-compatible"; baseUrl: string } {
  return { backend: preset.backend, baseUrl: preset.baseUrl ?? "" };
}
