import { useEffect, useState, type FormEvent } from "react";
import { registerUser } from "../api.js";

interface RegisterDialogProps {
  onSuccess: (username: string) => void;
  onCancel: () => void;
}

/** Modal for creating a new account — reuses the same overlay/panel/header classes as
 * RenameSessionDialog/SettingsPanel for a consistent look, replacing the old inline "注册" tab
 * in ApiKeyGate. */
export function RegisterDialog({ onSuccess, onCancel }: RegisterDialogProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [formError, setFormError] = useState<string>();

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onCancel();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onCancel]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(undefined);
    if (password !== confirmPassword) {
      setFormError("两次输入的密码不一致");
      return;
    }
    try {
      // Registering issues a fresh API key, but it's intentionally not used to auto-enter the
      // app — the user is expected to log in explicitly afterward (see ApiKeyGate's onSuccess).
      await registerUser(username.trim(), password);
      onSuccess(username.trim());
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "注册失败，请重试");
    }
  }

  return (
    <div className="settings-overlay" role="presentation" onClick={onCancel}>
      <div
        className="settings-panel"
        role="dialog"
        aria-modal="true"
        aria-label="注册账号"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="settings-header">
          <h2 className="settings-title">注册账号</h2>
          <button type="button" className="settings-close-button" onClick={onCancel} aria-label="关闭">
            ✕
          </button>
        </div>
        {formError && <p className="chat-error">{formError}</p>}
        <form onSubmit={handleSubmit}>
          <input
            className="register-dialog-input"
            placeholder="用户名"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoFocus
          />
          <input
            className="register-dialog-input"
            type="password"
            placeholder="密码（至少 8 位）"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <input
            className="register-dialog-input"
            type="password"
            placeholder="确认密码"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
          />
          <div className="register-dialog-actions">
            <button type="button" className="register-dialog-cancel" onClick={onCancel}>
              取消
            </button>
            <button type="submit" className="register-dialog-confirm">
              注册
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
