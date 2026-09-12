import { useEffect } from "react";
import type { ThemePreference } from "../lib/theme.js";

interface SettingsPanelProps {
  theme: ThemePreference;
  onThemeChange: (theme: ThemePreference) => void;
  onChangeApiKey: () => void;
  onClose: () => void;
}

const THEME_OPTIONS: { value: ThemePreference; label: string }[] = [
  { value: "system", label: "跟随系统" },
  { value: "light", label: "浅色" },
  { value: "dark", label: "深色" },
];

export function SettingsPanel({ theme, onThemeChange, onChangeApiKey, onClose }: SettingsPanelProps) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div className="settings-overlay" role="presentation" onClick={onClose}>
      <div
        className="settings-panel"
        role="dialog"
        aria-modal="true"
        aria-label="设置"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="settings-header">
          <h2 className="settings-title">设置</h2>
          <button type="button" className="settings-close-button" onClick={onClose} aria-label="关闭设置">
            ✕
          </button>
        </div>

        <section className="settings-section">
          <h3 className="settings-section-title">外观</h3>
          <div className="settings-theme-options" role="radiogroup" aria-label="主题">
            {THEME_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={theme === option.value}
                className={`settings-theme-option${theme === option.value ? " settings-theme-option-active" : ""}`}
                onClick={() => onThemeChange(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </section>

        <section className="settings-section">
          <h3 className="settings-section-title">账户</h3>
          <p className="settings-section-hint">更换 API Key 后需要重新输入才能继续使用。</p>
          <button type="button" className="settings-change-key-button" onClick={onChangeApiKey}>
            更换 API Key
          </button>
        </section>
      </div>
    </div>
  );
}
