"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, formatErrorMessage, readStoredAuth, type Room, type CompositeRoom } from "@/lib/api";

export default function Page() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [composites, setComposites] = useState<CompositeRoom[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const auth = readStoredAuth();
    if (!auth) {
      window.location.assign("/login");
      return;
    }
    api.listRooms(auth.token, true)
      .then((data) => {
        setRooms(data.rooms);
        setComposites(data.composites);
      })
      .catch((err: unknown) => setError(formatErrorMessage(err)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="page-shell">
      <header className="section-header">
        <div>
          <p className="eyebrow">会议室</p>
          <h1>会议室列表</h1>
          <p className="muted">数据来源：GET /api/rooms。前端只展示后端返回的结构化状态。</p>
        </div>
      </header>
      {error ? <div className="error-box">{error}</div> : null}
      {loading ? <div className="panel">正在读取会议室...</div> : (
        <>
          <section className="stack">
            <h2>普通会议室</h2>
            <div className="grid room-grid">
              {rooms.map((room) => (
                <article className="card room-card" key={room.id}>
                  <div className="row between">
                    <strong>{room.name}</strong>
                    <span className={`status-pill status-${room.status}`}>{room.status}</span>
                  </div>
                  <p className="muted">{room.id} · {room.location} · 容量 {room.capacity} · {room.type}</p>
                  <p>{room.equipment.join("、") || "无设备"}</p>
                  <Link className="text-link" href={`/calendar?target_type=room&target_id=${room.id}`}>查看日历</Link>
                </article>
              ))}
            </div>
          </section>
          <section className="stack">
            <h2>组合空间</h2>
            <div className="grid room-grid">
              {composites.map((composite) => (
                <article className="card room-card" key={composite.id}>
                  <div className="row between">
                    <strong>{composite.name}</strong>
                    <span className={`status-pill status-${composite.status}`}>{composite.status}</span>
                  </div>
                  <p className="muted">{composite.id} · 容量 {composite.capacity}</p>
                  <p>成员：{composite.member_room_ids.join(" + ")}</p>
                  <Link className="text-link" href={`/calendar?target_type=composite&target_id=${composite.id}`}>查看日历</Link>
                </article>
              ))}
            </div>
          </section>
        </>
      )}
    </main>
  );
}
