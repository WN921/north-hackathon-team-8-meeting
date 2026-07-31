"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, formatErrorMessage, readStoredAuth, type Booking, type CalendarSlot } from "@/lib/api";

const today = new Date().toISOString().slice(0, 10);

export default function Page() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [targetType, setTargetType] = useState(searchParams.get("target_type") ?? "");
  const [targetId, setTargetId] = useState(searchParams.get("target_id") ?? "");
  const [date, setDate] = useState(searchParams.get("date") ?? today);
  const [slots, setSlots] = useState<CalendarSlot[]>([]);
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const query = useMemo(() => {
    const params: Record<string, string> = { date };
    if (targetType) params.target_type = targetType;
    if (targetId) params.target_id = targetId;
    return params;
  }, [date, targetId, targetType]);

  useEffect(() => {
    setTargetType(searchParams.get("target_type") ?? "");
    setTargetId(searchParams.get("target_id") ?? "");
    setDate(searchParams.get("date") ?? today);
  }, [pathname, searchParams]);

  useEffect(() => {
    const auth = readStoredAuth();
    if (!auth) {
      window.location.assign("/login");
      return;
    }
    setLoading(true);
    setError(null);
    Promise.all([api.getCalendar(auth.token, query), api.listBookings(auth.token, query)])
      .then(([calendarData, bookingData]) => {
        setSlots(calendarData.slots);
        setBookings(bookingData.items);
      })
      .catch((err: unknown) => setError(formatErrorMessage(err)))
      .finally(() => setLoading(false));
  }, [query]);

  return (
    <main className="page-shell">
      <header className="section-header">
        <div>
          <p className="eyebrow">日历</p>
          <h1>日历/时段视图</h1>
          <p className="muted">数据来源：GET /api/calendar。固定占用、规则占用和冲突均由后端返回。</p>
        </div>
      </header>
      {error ? <div className="error-box">{error}</div> : null}
      <section className="card stack">
        <div className="grid filters">
          <label className="field">
            <span>目标类型</span>
            <select value={targetType} onChange={(event) => setTargetType(event.target.value)}>
              <option value="">全部</option>
              <option value="room">房间</option>
              <option value="composite">组合空间</option>
            </select>
          </label>
          <label className="field">
            <span>目标 ID</span>
            <input value={targetId} onChange={(event) => setTargetId(event.target.value)} placeholder="例如 503 或 meeting-room-1-2" />
          </label>
          <label className="field">
            <span>日期</span>
            <input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
          </label>
        </div>
        <div className="row wrap">
          <Link className="secondary-button" href="/calendar">查看全部</Link>
          <Link className="secondary-button" href="/floor-plan">查看平面图</Link>
        </div>
      </section>

      <section className="stack">
        <h2>占用时段</h2>
        {loading ? <div className="panel">正在读取日历...</div> : slots.length === 0 ? <div className="panel">该视图暂无占用记录。</div> : (
          <div className="timeline">
            {slots.map((slot, index) => (
              <article className={`slot status-${slot.status}`} key={`${slot.start_at}-${slot.end_at}-${slot.booking_id ?? slot.rule_id ?? index}`}>
                <strong>{formatTime(slot.start_at)} - {formatTime(slot.end_at)}</strong>
                <span>{slot.status}</span>
                <p>{slot.title ?? slot.message ?? "不可预约"}</p>
                <small>{slot.booking_id ? `预约 ${slot.booking_id}` : slot.rule_id ? `规则 ${slot.rule_id}` : slot.reason_code}</small>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="stack">
        <h2>预约记录</h2>
        {bookings.length === 0 ? <div className="panel">暂无预约。</div> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>标题</th><th>目标</th><th>时间</th><th>状态</th><th>操作</th></tr>
              </thead>
              <tbody>
                {bookings.map((booking) => (
                  <tr key={booking.id}>
                    <td>{booking.title}</td>
                    <td>{booking.target_type}:{booking.target_id}</td>
                    <td>{formatDateTime(booking.start_at)} - {formatTime(booking.end_at)}</td>
                    <td>{booking.status}</td>
                    <td><Link className="text-link" href={`/bookings/${booking.id}`}>详情</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}

function formatTime(value: string) {
  return value.includes("T") ? value.slice(11, 16) : value;
}

function formatDateTime(value: string) {
  return value.includes("T") ? value.replace("T", " ").slice(0, 16) : value;
}
