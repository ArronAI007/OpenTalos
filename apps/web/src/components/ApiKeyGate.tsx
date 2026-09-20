import { useState, type FormEvent } from "react";
import { setApiKey, loginUser } from "../api.js";
import { RegisterDialog } from "./RegisterDialog.js";

interface ApiKeyGateProps {
  onSubmit: () => void;
  error?: string;
}

export function ApiKeyGate({ onSubmit, error }: ApiKeyGateProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [formError, setFormError] = useState<string>();
  const [successMessage, setSuccessMessage] = useState<string>();
  const [isRegisterOpen, setIsRegisterOpen] = useState(false);

  async function handleLoginSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(undefined);
    setSuccessMessage(undefined);
    try {
      const apiKey = await loginUser(username.trim(), password);
      setApiKey(apiKey);
      onSubmit();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "登录失败，请重试");
    }
  }

  return (
    <div className="gate-card">
      <h1 className="gate-title">登录</h1>

      {error && <p className="chat-error">{error}</p>}
      {formError && <p className="chat-error">{formError}</p>}
      {successMessage && <p className="gate-success">{successMessage}</p>}

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

      <div className="gate-footer">
        还没有账号？
        <button
          type="button"
          className="gate-register-link"
          onClick={() => {
            setSuccessMessage(undefined);
            setIsRegisterOpen(true);
          }}
        >
          注册
        </button>
      </div>

      {isRegisterOpen && (
        <RegisterDialog
          onSuccess={(registeredUsername) => {
            // Deliberately does not auto-login: registration and login are kept as two
            // explicit steps, so the user always logs in themselves after creating an account.
            setUsername(registeredUsername);
            setIsRegisterOpen(false);
            setSuccessMessage("注册成功，请登录");
          }}
          onCancel={() => setIsRegisterOpen(false)}
        />
      )}
    </div>
  );
}
