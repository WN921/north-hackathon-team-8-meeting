"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { api, formatErrorMessage, readStoredAuth, writeStoredAuth } from "@/lib/api";

export default function Page() {
  const router = useRouter();
  const [username, setUsername] = useState("demo");
  const [password, setPassword] = useState("demo-password");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (readStoredAuth()) {
      router.replace("/");
    }
  }, [router]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const data = await api.login(username, password);
      writeStoredAuth({ token: data.token, user: data.user });
      router.replace("/");
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="page-shell">
      <section className="card login-card">
        <p className="eyebrow">本地演示</p>
        <h1>会务系统登录</h1>
        <p className="muted">使用本地演示账号进入会务系统。默认账号：demo / demo-password。</p>
        <form className="stack" onSubmit={onSubmit}>
          <label className="field">
            <span>用户名</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required />
          </label>
          <label className="field">
            <span>密码</span>
            <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="current-password" required />
          </label>
          {error ? <div className="error-box">{error}</div> : null}
          <button className="primary-button" disabled={loading}>{loading ? "登录中..." : "登录"}</button>
        </form>
      </section>
    </main>
  );
}
