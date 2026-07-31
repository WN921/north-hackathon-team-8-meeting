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
          <p className="muted">用列表展示房间和组合空间状态；固定占用、规则占用和预约冲突均由后端返回。</p>
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
        {items.length === 0 ? <div className="panel">暂无平面图数据。</div> : (
          <div className="floor-plan-grid">
            {items.map((item) => (
              <Link className={`floor-plan-card status-${statusClass(item.status)}`} key={item.id} href={`/calendar?target_type=${item.member_room_ids ? "composite" : "room"}&target_id=${encodeURIComponent(item.id)}&date=${date}`}>
                <span className="floor-plan-emoji" aria-hidden="true">{statusEmoji(item.status)}</span>
                <span>
                  <strong className="floor-plan-name">{item.name}</strong>
                  <small className="floor-plan-message">{item.message || statusLabel(item.status)}</small>
                </span>
              </Link>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

function statusClass(status: string) {
  if (status === "available") return "available";
  if (status === "booked" || status === "maintenance") return "unavailable";
  if (status === "blocked_by_rule" || status === "fixed_unavailable") return "partial";
  if (status === "composite_booked") return "composite";
  return "available";
}

function statusEmoji(status: string) {
  if (status === "available") return "🟢";
  if (status === "booked") return "🔴";
  if (status === "blocked_by_rule") return "🟡";
  if (status === "fixed_unavailable") return "🟡";
  if (status === "maintenance") return "🔴";
  if (status === "composite_booked") return "🟣";
  return "🔵";
}

function statusLabel(status: string) {
  if (status === "available") return "可用";
  if (status === "booked") return "已预约";
  if (status === "blocked_by_rule") return "规则占用";
  if (status === "fixed_unavailable") return "固定不可用";
  if (status === "maintenance") return "维修中";
  if (status === "composite_booked") return "组合占用";
  return "状态未知";
}
