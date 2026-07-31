"use client";

import { FormEvent, useState } from "react";
import { api, createIdempotencyKey, formatErrorMessage, readStoredAuth, type AvailabilityTarget, type NLCandidatesData } from "@/lib/api";
import { readStateRevision } from "@/lib/state";

const examples = [
  "下周二 10:00—11:00 想约一间小会议室开项目讨论，帮我看看有哪些可以用。",
  "明天中午想预约活动室开会。",
];

export default function Page() {
  const [utterance, setUtterance] = useState(examples[0]);
  const [data, setData] = useState<NLCandidatesData | null>(null);
  const [selected, setSelected] = useState<AvailabilityTarget | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function queryCandidates(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const auth = readStoredAuth();
    if (!auth) {
      window.location.assign("/login");
      return;
    }
    setLoading(true);
    setError(null);
    setData(null);
    setSelected(null);
    setMessage(null);
    try {
      const result = await api.naturalLanguageCandidates(auth.token, {
        utterance,
        actor_id: auth.user.id,
        idempotency_key: createIdempotencyKey("nl_candidates"),
        expected_state_revision: readStateRevision(),
      });
      setData(result);
      setMessage("已返回候选；请选择候选后再创建预约。");
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  async function createFromCandidate() {
    const auth = readStoredAuth();
    if (!auth || !selected || !data) {
      return;
    }
    setError(null);
    setMessage(null);
    try {
      await api.checkAvailability(auth.token, {
        target_type: selected.target_type,
        target_id: selected.target_id,
        start_at: data.parsed_booking.start_at,
        end_at: data.parsed_booking.end_at,
      });
      const created = await api.createBooking(auth.token, {
        actor_id: auth.user.id,
        idempotency_key: createIdempotencyKey("booking_from_nl"),
        expected_state_revision: readStateRevision(),
        target_type: selected.target_type,
        target_id: selected.target_id,
        start_at: data.parsed_booking.start_at,
        end_at: data.parsed_booking.end_at,
        title: data.parsed_booking.title,
        organizer_id: auth.user.id,
        attendees: [auth.user.name],
        description: "由自然语言候选创建",
      });
      setMessage(`预约已创建：${created.booking_id}`);
    } catch (err) {
      setError(formatErrorMessage(err));
    }
  }

  return (
    <main className="page-shell">
      <header className="section-header">
        <div>
          <p className="eyebrow">自然语言</p>
          <h1>预约候选查询</h1>
          <p className="muted">先返回候选和排除原因；用户选择候选并确认后才会创建预约。</p>
        </div>
      </header>
      {error ? <div className="error-box">{error}</div> : null}
      {message ? <div className="success-box">{message}</div> : null}

      <section className="card stack">
        <form onSubmit={queryCandidates} className="stack">
          <label className="field">
            <span>自然语言预约查询</span>
            <textarea value={utterance} onChange={(event) => setUtterance(event.target.value)} rows={4} />
          </label>
          <div className="row wrap">
            {examples.map((example) => (
              <button className="ghost-button" key={example} type="button" onClick={() => setUtterance(example)}>{example}</button>
            ))}
          </div>
          <button className="primary-button" disabled={loading}>{loading ? "解析中..." : "查询候选"}</button>
        </form>
      </section>

      {data ? (
        <section className="grid result-columns">
          <article className="card stack">
            <h2>候选目标</h2>
            {data.candidates.length === 0 ? <div className="panel">暂无可用候选。</div> : data.candidates.map((candidate) => (
              <button className={`candidate-card ${selected?.target_id === candidate.target_id ? "selected" : ""}`} key={`${candidate.target_type}-${candidate.target_id}`} onClick={() => setSelected(candidate)}>
                <strong>{candidate.name}</strong>
                <span>{candidate.target_type}:{candidate.target_id}</span>
                <small>{candidate.capacity ? `容量 ${candidate.capacity}` : "组合空间"}</small>
              </button>
            ))}
            <button className="primary-button" disabled={!selected} onClick={createFromCandidate}>选择候选并创建预约</button>
          </article>
          <article className="card stack">
            <h2>排除原因</h2>
            {data.excluded_targets.length === 0 ? <div className="panel">没有排除目标。</div> : data.excluded_targets.map((target) => (
              <div className="exclusion" key={`${target.target_type}-${target.target_id}`}>
                <strong>{target.name}</strong>
                <span>{target.target_type}:{target.target_id}</span>
                <p>{target.message ?? target.reason_code}</p>
              </div>
            ))}
          </article>
        </section>
      ) : null}
    </main>
  );
}
