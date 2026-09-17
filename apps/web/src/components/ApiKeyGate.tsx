import { useState, type FormEvent } from "react";
import { setApiKey, loginUser, registerUser } from "../api.js";

interface ApiKeyGateProps {
  onSubmit: () => void;
  error?: string;
}

type Mode = "login" | "register" | "key";

export function ApiKeyGate({ onSubmit, error }: ApiKeyGateProps) {
  const [mode, setMode] = useState<Mode>("login");
  const [draft, setDraft] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [formError, setFormError] = useState<string>();

  function switchMode(next: Mode) {
    setMode(next);
    setFormError(undefined);
  }

  function handleKeySubmit(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim()) return;
    setApiKey(draft.trim());
    onSubmit();
  }

  async function handleLoginSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(undefined);
    try {
      const apiKey = await loginUser(username.trim(), password);
      setApiKey(apiKey);
      onSubmit();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "登录失败，请重试");
    }
  }

  async function handleRegisterSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(undefined);
    if (password !== confirmPassword) {
      setFormError("两次输入的密码不一致");
      return;
    }
    try {
      const apiKey = await registerUser(username.trim(), password);
      setApiKey(apiKey);
      onSubmit();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "注册失败，请重试");
    }
  }

  return (
    <div className="gate-card">
      {/* role="tab"/"tablist" (rather than plain buttons) is deliberate, not just decoration:
       * the login/register forms below have their own submit buttons with the same visible text
       * ("登录" / "注册"). Two simultaneously-rendered controls both exposed as role="button"
       * with the identical accessible name would be ambiguous for assistive tech and for
       * Playwright's getByRole("button", ...) alike — giving the tabs their own role sidesteps
       * that entirely instead of relying on visible-text tricks. */}
      <div className="gate-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "login"}
          className={mode === "login" ? "gate-tab gate-tab-active" : "gate-tab"}
          onClick={() => switchMode("login")}
        >
          登录
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "register"}
          className={mode === "register" ? "gate-tab gate-tab-active" : "gate-tab"}
          onClick={() => switchMode("register")}
        >
          注册
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "key"}
          className={mode === "key" ? "gate-tab gate-tab-active" : "gate-tab"}
          onClick={() => switchMode("key")}
        >
          API Key
        </button>
      </div>

      {error && <p className="chat-error">{error}</p>}
      {formError && <p className="chat-error">{formError}</p>}

      {mode === "key" && (
        <form onSubmit={handleKeySubmit}>
          <p>请输入管理员为你分配的 API Key</p>
          <input
            className="gate-input"
            type="password"
            placeholder="API Key"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <button className="gate-button" type="submit">
            进入
          </button>
        </form>
      )}

      {mode === "login" && (
        <form onSubmit={handleLoginSubmit}>
          <input
            className="gate-input"
            placeholder="用户名"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
          <input
            className="gate-input"
            type="password"
            placeholder="密码"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <button className="gate-button" type="submit">
            登录
          </button>
        </form>
      )}

      {mode === "register" && (
        <form onSubmit={handleRegisterSubmit}>
          <input
            className="gate-input"
            placeholder="用户名"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
          <input
            className="gate-input"
            type="password"
            placeholder="密码（至少 8 位）"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <input
            className="gate-input"
            type="password"
            placeholder="确认密码"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
          />
          <button className="gate-button" type="submit">
            注册
          </button>
        </form>
      )}
    </div>
  );
}
