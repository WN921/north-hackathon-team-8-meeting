"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { api, formatErrorMessage, type FloorPlanNode, readStoredAuth, type StoredAuth } from "@/lib/api";

const today = new Date().toISOString().slice(0, 10);

export default function Page() {
  const [auth, setAuth] = useState<StoredAuth | null>(null);
  const [date, setDate] = useState(today);
  const [time, setTime] = useState("10:00");
  const [items, setItems] = useState<FloorPlanNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const stored = readStoredAuth();
    if (!stored) {
      window.location.assign("/login");
      return;
    }
    setAuth(stored);
  }, []);

  async function load(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!auth) return;
    setLoading(true);
    setError(null);
    try {
      const response = await api.getFloorPlan(auth.token, { date, time });
      setItems([...response.rooms, ...response.composites]);
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (auth) void load();
  }, [auth]);

  if (!auth) return null;

  return (
    <main className="page-shell">
      <header className="section-header">
        <div>
          <p className="eyebrow">平面图</p>
          <h1>会议室平面图</h1>
          <p className="muted">使用静态 SVG 布局，叠加 FastAPI 返回的规则、预约和组合空间状态。</p>
        </div>
      </header>
      <form className="card filters" onSubmit={load}>
        <label className="field"><span>日期</span><input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label>
        <label className="field"><span>时间</span><input type="time" value={time} onChange={(event) => setTime(event.target.value)} /></label>
        <button className="primary-button" disabled={loading}>{loading ? "刷新中..." : "刷新状态"}</button>
      </form>
      {error ? <div className="error-box">{error}</div> : null}
      <section className="card">
        <div className="legend-row">
          <span><i className="status-dot available" /> 可用</span>
          <span><i className="status-dot unavailable" /> 不可用</span>
          <span><i className="status-dot partial" /> 部分占用</span>
          <span><i className="status-dot composite" /> 组合空间</span>
        </div>
        <div className="svg-scroll">
          <svg className="floor-plan-svg" viewBox="0 0 1000 620" role="img" aria-label="会议室平面图">
            <rect x="20" y="20" width="960" height="580" rx="24" fill="#f8fafc" stroke="#cbd5e1" />
            {items.map((item) => {
              const position = item.position;
              if (!position) return null;
              const fill = statusFill(item.status);
              return (
                <Link key={item.id} href={`/calendar?target_type=${item.member_room_ids ? "composite" : "room"}&target_id=${encodeURIComponent(item.id)}&date=${date}`}>
                  <g>
                    <rect x={position.x} y={position.y} width={position.width} height={position.height} rx="12" fill={fill} stroke="#475569" strokeWidth="2" />
                    <text x={position.x + 16} y={position.y + 32} className="floor-plan-label">{item.name}</text>
                    <text x={position.x + 16} y={position.y + 56} className="floor-plan-caption">{item.message}</text>
                  </g>
                </Link>
              );
            })}
          </svg>
        </div>
      </section>
    </main>
  );
}

function statusFill(status: string) {
  if (status === "available") return "#dcfce7";
  if (status === "unavailable") return "#fee2e2";
  if (status === "partial") return "#fef3c7";
  return "#dbeafe";
}
