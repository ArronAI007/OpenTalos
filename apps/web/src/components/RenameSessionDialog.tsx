import { useEffect, useState, type FormEvent } from "react";

interface RenameSessionDialogProps {
  initialValue: string;
  onSave: (value: string) => void;
  onCancel: () => void;
}

/** Modal confirmation for renaming a session — reuses the same overlay/panel/header classes as
 * SettingsPanel for a consistent look, rather than the previous inline-input-in-place-of-the-h1
 * approach (which made it too easy to accidentally start editing and too easy to lose the draft
 * on an unrelated blur). */
export function RenameSessionDialog({ initialValue, onSave, onCancel }: RenameSessionDialogProps) {
  const [value, setValue] = useState(initialValue);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onCancel();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onCancel]);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    onSave(value);
  }

  return (
    <div className="settings-overlay" role="presentation" onClick={onCancel}>
      <div
        className="settings-panel rename-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="编辑对话名称"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="settings-header">
          <h2 className="settings-title">编辑对话名称</h2>
          <button type="button" className="settings-close-button" onClick={onCancel} aria-label="关闭">
            ✕
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <input
            className="rename-dialog-input"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            aria-label="对话名称"
            autoFocus
            onFocus={(event) => event.target.select()}
          />
          <div className="rename-dialog-actions">
            <button type="button" className="rename-dialog-cancel" onClick={onCancel}>
              取消
            </button>
            <button type="submit" className="rename-dialog-confirm">
              确定
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
