"use client";

import { useParams, useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { api, createIdempotencyKey, formatErrorMessage, readStoredAuth, type Booking } from "@/lib/api";
import { readStateRevision } from "@/lib/state";

export default function Page() {
  const params = useParams();
  const router = useRouter();
  const bookingId = typeof params.id === "string" ? params.id : "";
  const [booking, setBooking] = useState<Booking | null>(null);
  const [title, setTitle] = useState("");
  const [startAt, setStartAt] = useState("");
  const [endAt, setEndAt] = useState("");
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const auth = readStoredAuth();
    if (!auth || !bookingId) {
      window.location.assign("/login");
      return;
    }
    api.getBooking(auth.token, bookingId)
      .then((data) => {
        setBooking(data);
        setTitle(data.title);
        setStartAt(localDateTimeValue(data.start_at));
        setEndAt(localDateTimeValue(data.end_at));
      })
      .catch((err: unknown) => setError(formatErrorMessage(err)))
      .finally(() => setLoading(false));
  }, [bookingId]);

  async function updateBooking(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const auth = readStoredAuth();
    if (!auth || !bookingId) return;
    setError(null);
    setMessage(null);
    try {
      const response = await api.updateBooking(auth.token, bookingId, {
        actor_id: auth.user.id,
        idempotency_key: createIdempotencyKey("booking_update"),
        expected_state_revision: readStateRevision(),
        title,
        start_at: toApiDateTime(startAt),
        end_at: toApiDateTime(endAt),
        reason,
      });
      setBooking(response.new_booking);
      setMessage(`预约已更新：${response.status}`);
    } catch (err) {
      setError(formatErrorMessage(err));
    }
  }

  async function cancelBooking() {
    const auth = readStoredAuth();
    if (!auth || !bookingId) return;
    setError(null);
    setMessage(null);
    try {
      await api.cancelBooking(auth.token, bookingId, {
        actor_id: auth.user.id,
        idempotency_key: createIdempotencyKey("booking_cancel"),
        expected_state_revision: readStateRevision(),
        reason: reason || "会议取消",
      });
      setMessage("预约已取消，对应时段已释放。");
      router.push("/calendar");
    } catch (err) {
      setError(formatErrorMessage(err));
    }
  }

  return (
    <main className="page-shell">
      <header className="section-header">
        <div>
          <p className="eyebrow">预约详情</p>
          <h1>{booking?.title ?? "预约详情"}</h1>
          <p className="muted">支持取消预约；修改预约仍需通过后端冲突校验。</p>
        </div>
      </header>
      {error ? <div className="error-box">{error}</div> : null}
      {message ? <div className="success-box">{message}</div> : null}
      {loading ? <div className="panel">正在读取预约...</div> : booking ? (
        <div className="grid result-columns">
          <section className="card stack">
            <h2>预约信息</h2>
            <p><strong>ID：</strong>{booking.booking_id ?? booking.id}</p>
            <p><strong>目标：</strong>{booking.target_type}:{booking.target_id}</p>
            <p><strong>时间：</strong>{booking.start_at.replace("T", " ")} - {booking.end_at.replace("T", " ")}</p>
            <p><strong>发起人：</strong>{booking.organizer_id}</p>
            <p><strong>状态：</strong>{booking.status}</p>
          </section>
          <section className="card stack">
            <h2>修改预约</h2>
            <form className="stack" onSubmit={updateBooking}>
              <label className="field"><span>标题</span><input value={title} onChange={(event) => setTitle(event.target.value)} /></label>
              <label className="field"><span>开始时间</span><input type="datetime-local" value={startAt} onChange={(event) => setStartAt(event.target.value)} /></label>
              <label className="field"><span>结束时间</span><input type="datetime-local" value={endAt} onChange={(event) => setEndAt(event.target.value)} /></label>
              <label className="field"><span>修改原因</span><input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="会议时间调整" /></label>
              <button className="primary-button">保存修改</button>
            </form>
          </section>
          <section className="card stack">
            <h2>取消预约</h2>
            <p className="muted">取消后该时段释放，可在日历或预约创建流程中重新预约。</p>
            <button className="danger-button" onClick={cancelBooking}>取消预约</button>
          </section>
        </div>
      ) : null}
    </main>
  );
}

function localDateTimeValue(value: string) {
  if (!value.includes("T")) return value;
  const [date, time] = value.replace("+08:00", "").split("T");
  return `${date}T${time.slice(0, 5)}`;
}

function toApiDateTime(value: string) {
  return value ? `${value}:00+08:00` : "";
}
