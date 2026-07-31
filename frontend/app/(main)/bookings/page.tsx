"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, formatErrorMessage, readStoredAuth, type Booking } from "@/lib/api";

export default function Page() {
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const auth = readStoredAuth();
    if (!auth) {
      window.location.assign("/login");
      return;
    }
    api.listBookings(auth.token)
      .then((data) => setBookings(data.items))
      .catch((err: unknown) => setError(formatErrorMessage(err)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="page-shell">
      <header className="section-header">
        <div>
          <p className="eyebrow">预约</p>
          <h1>预约列表</h1>
          <p className="muted">查看、取消和修改预约。取消后释放的时段可重新预约。</p>
        </div>
        <Link className="primary-button" href="/bookings/new">新建预约</Link>
      </header>
      {error ? <div className="error-box">{error}</div> : null}
      {loading ? <div className="panel">正在读取预约...</div> : bookings.length === 0 ? <div className="panel">暂无预约。</div> : (
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
    </main>
  );
}

function formatTime(value: string) {
  return value.includes("T") ? value.slice(11, 16) : value;
}

function formatDateTime(value: string) {
  return value.includes("T") ? value.replace("T", " ").slice(0, 16) : value;
}
