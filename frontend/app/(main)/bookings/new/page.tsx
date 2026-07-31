"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { api, createIdempotencyKey, formatErrorMessage, readStoredAuth } from "@/lib/api";
import { readStateRevision } from "@/lib/state";

const today = new Date().toISOString().slice(0, 10);

export default function Page() {
  const router = useRouter();
  const [targetType, setTargetType] = useState<"room" | "composite">("room");
  const [targetId, setTargetId] = useState("503");
  const [startAt, setStartAt] = useState(`${today}T10:00`);
  const [endAt, setEndAt] = useState(`${today}T11:00`);
  const [title, setTitle] = useState("项目讨论");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function createBooking(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const auth = readStoredAuth();
    if (!auth) {
      window.location.assign("/login");
      return;
    }
    setLoading(true);
    setError(null);
    setMessage(null);
    try {
      const payload = {
        actor_id: auth.user.id,
        idempotency_key: createIdempotencyKey("booking_create"),
        expected_state_revision: readStateRevision(),
        target_type: targetType,
        target_id: targetId,
        start_at: startAt ? `${startAt}:00+08:00` : "",
        end_at: endAt ? `${endAt}:00+08:00` : "",
        title,
        organizer_id: auth.user.id,
        attendees: [auth.user.name],
        description: "手动创建预约",
      };
      await api.checkAvailability(auth.token, {
        target_type: targetType,
        target_id: targetId,
        start_at: payload.start_at,
        end_at: payload.end_at,
      });
      const created = await api.createBooking(auth.token, payload);
      setMessage(`预约创建成功：${created.booking_id}`);
      router.push(`/bookings/${created.booking_id}`);
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="page-shell">
      <header className="section-header">
        <div>
          <p className="eyebrow">预约</p>
          <h1>创建预约</h1>
          <p className="muted">创建前调用冲突预检；所有冲突、午餐、规则和组合空间约束由后端判断。</p>
        </div>
      </header>
      {error ? <div className="error-box">{error}</div> : null}
      {message ? <div className="success-box">{message}</div> : null}
      <section className="card stack">
        <form className="grid filters" onSubmit={createBooking}>
          <label className="field"><span>目标类型</span><select value={targetType} onChange={(event) => setTargetType(event.target.value as "room" | "composite")}><option value="room">房间</option><option value="composite">组合空间</option></select></label>
          <label className="field"><span>目标 ID</span><input value={targetId} onChange={(event) => setTargetId(event.target.value)} placeholder="503 或 meeting-room-1-2" /></label>
          <label className="field"><span>开始时间</span><input type="datetime-local" value={startAt} onChange={(event) => setStartAt(event.target.value)} /></label>
          <label className="field"><span>结束时间</span><input type="datetime-local" value={endAt} onChange={(event) => setEndAt(event.target.value)} /></label>
          <label className="field"><span>标题</span><input value={title} onChange={(event) => setTitle(event.target.value)} /></label>
          <button className="primary-button" disabled={loading}>{loading ? "创建中..." : "创建预约"}</button>
        </form>
      </section>
    </main>
  );
}
