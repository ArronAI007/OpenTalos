const SIDEBAR_WIDTH_KEY = "opentalos-sidebar-width";

export const MIN_SIDEBAR_WIDTH = 180;
export const MAX_SIDEBAR_WIDTH = 420;
export const DEFAULT_SIDEBAR_WIDTH = 240;

export function clampSidebarWidth(width: number): number {
  return Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, width));
}

export function loadSidebarWidth(): number {
  try {
    const stored = localStorage.getItem(SIDEBAR_WIDTH_KEY);
    const parsed = stored ? Number(stored) : NaN;
    if (Number.isFinite(parsed)) return clampSidebarWidth(parsed);
  } catch {
    // Best-effort only (e.g. private browsing with storage disabled) — falls back to the default.
  }
  return DEFAULT_SIDEBAR_WIDTH;
}

export function saveSidebarWidth(width: number): void {
  try {
    localStorage.setItem(SIDEBAR_WIDTH_KEY, String(width));
  } catch {
    // Best-effort only — the resized width still applies for the current tab, it just won't persist.
  }
}
