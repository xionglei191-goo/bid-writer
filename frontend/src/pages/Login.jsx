import React, { useState } from "react";
import { BookOpenCheck, KeyRound, LogIn } from "lucide-react";
import { post } from "../api";
import { BusyButton, Notice } from "../components";

export default function Login({ oidcEnabled, onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try { await post("/api/auth/login", { username, password }); await onLogin(); }
    catch (nextError) { setError(nextError.message); }
    finally { setBusy(false); }
  }
  return <main className="login-page"><section className="login-panel"><div className="login-brand"><BookOpenCheck size={25} /><div><strong>标书生产系统</strong><span>技术与知识工作台</span></div></div><form onSubmit={submit}><label>账号<input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} /></label><label>密码<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>{error && <Notice type="danger">{error}</Notice>}<BusyButton busy={busy} type="submit"><LogIn size={16} />登录</BusyButton>{oidcEnabled && <a className="oidc-login" href="/api/auth/oidc/start"><KeyRound size={16} />企业账号登录</a>}</form></section></main>;
}
