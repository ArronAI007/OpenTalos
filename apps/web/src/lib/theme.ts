const THEME_KEY = "opentalos-theme";

export type ThemePreference = "system" | "light" | "dark";

export function loadTheme(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // Best-effort only (e.g. private browsing with storage disabled) — falls back to "system".
  }
  return "system";
}

export function saveTheme(theme: ThemePreference): void {
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    // Best-effort only — the choice still applies for the current tab, it just won't persist.
  }
}

/** "system" removes the override entirely so tokens.css's prefers-color-scheme media query (the
 * OS-driven default) takes over again, rather than pinning to whatever the OS happened to be at
 * the moment "system" was chosen. */
export function applyTheme(theme: ThemePreference): void {
  if (theme === "system") {
    delete document.documentElement.dataset.theme;
  } else {
    document.documentElement.dataset.theme = theme;
  }
}
