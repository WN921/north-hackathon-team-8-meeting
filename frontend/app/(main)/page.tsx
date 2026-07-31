"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, clearStoredAuth, readStoredAuth, type StoredAuth } from "@/lib/api";
import { readStateRevision } from "@/lib/state";

export default function Page() {
  const [auth, setAuth] = useState<StoredAuth | null>(null);
  const [revision, setRevision] = useState<number | null>(null);
  const [rooms, setRooms] = useState(0);
  const [composites, setComposites] = useState(0);
  const [bookings, setBookings] = useState(0);
  const [rules, setRules] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const stored = readStoredAuth();
    if (!stored) {
      return;
    }
    setAuth(stored);
    Promise.all([
      api.me(stored.token),
      api.listRooms(stored.token, true),
      api.listBookings(stored.token),
      api.listRules(stored.token),
    ])
      .then(([me, roomData, bookingData, ruleData]) => {
        setAuth({ token: stored.token, user: me.user });
        setRevision(readStateRevision());
        setRooms(roomData.rooms.length);
        setComposites(roomData.composites.length);
        setBookings(bookingData.items.length);
        setRules(ruleData.items.length);
      })
      .catch((err: unknown) => setError((err as Error).message));
  }, []);

  if (!auth) {
    return null;
  }

  return (
    <main className="page-shell">
      <header className="section-header">
        <div>
          <p className="eyebrow">会务系统</p>
          <h1>你好，{auth.user.name}</h1>
          <p className="muted">本地会务系统关键路径：登录、会议室、日历、自然语言、预约和平面图。</p>
        </div>
        <button className="secondary-button" onClick={() => { clearStoredAuth(); window.location.assign("/login"); }}>退出登录</button>
      </header>

      {error ? <div className="error-box">{error}</div> : null}
      {revision === null ? <div className="panel">正在读取后端状态...</div> : (
        <section className="grid cards">
          <article className="card metric">
            <span>状态版本</span>
            <strong>{revision}</strong>
          </article>
          <article className="card metric">
            <span>会议室</span>
            <strong>{rooms}</strong>
          </article>
          <article className="card metric">
            <span>组合空间</span>
            <strong>{composites}</strong>
          </article>
          <article className="card metric">
            <span>预约</span>
            <strong>{bookings}</strong>
          </article>
          <article className="card metric">
            <span>规则</span>
            <strong>{rules}</strong>
          </article>
        </section>
      )}

      <section className="grid actions">
        <Link className="action-card" href="/rooms">
          <strong>会议室列表</strong>
          <span>查看默认空间、容量、设备和 504 节点</span>
        </Link>
        <Link className="action-card" href="/calendar">
          <strong>日历视图</strong>
          <span>查看预约、固定占用、规则占用和组合占用</span>
        </Link>
        <Link className="action-card" href="/nl/query">
          <strong>自然语言查询</strong>
          <span>查询候选，选择候选后再创建预约</span>
        </Link>
        <Link className="action-card" href="/rules">
          <strong>规则配置</strong>
          <span>用自然语言更新 504 临时维修规则</span>
        </Link>
        <Link className="action-card" href="/floor-plan">
          <strong>平面图</strong>
          <span>查看 5F 静态 SVG 与房间状态</span>
        </Link>
      </section>
    </main>
  );
}
