"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { api } from "@/lib/api";

const TOKEN_KEY = "nexa-auth-token";
const USER_KEY = "nexa-auth-user";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await api.login(username, password);
      localStorage.setItem(TOKEN_KEY, result.token);
      localStorage.setItem(USER_KEY, result.username);
      router.replace("/");
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
        </div>
        <h1 className="login-title">Nexa</h1>
        <p className="login-subtitle">Statement Review Assistant</p>

        <form className="login-form" onSubmit={handleSubmit}>
          <label className="login-label">
            Username
            <input
              className="login-input"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="admin"
              autoFocus
              disabled={busy}
            />
          </label>
          <label className="login-label">
            Password
            <input
              className="login-input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••"
              disabled={busy}
            />
          </label>

          {error ? <p className="login-error">{error}</p> : null}

          <button className="login-btn" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}