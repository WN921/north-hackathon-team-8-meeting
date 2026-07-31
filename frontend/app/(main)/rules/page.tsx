"use client";

import { FormEvent, useState } from "react";
import { api, createIdempotencyKey, formatErrorMessage, readStoredAuth, type NLConfigureData, type Rule } from "@/lib/api";
import { readStateRevision } from "@/lib/state";

const examples = [
  "这周三 504 临时维修，全天不能预约。刚才说错了，只停用下午。",
  "这周三 504 临时维修，全天不能预约。",
];

export default function Page() {
  const [utterance, setUtterance] = useState(examples[0]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [result, setResult] = useState<NLConfigureData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function loadRules() {
    const auth = readStoredAuth();
    if (!auth) {
      window.location.assign("/login");
      return;
    }
    const data = await api.listRules(auth.token);
    setRules(data.items);
  }

  async function submitConfigure(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const auth = readStoredAuth();
    if (!auth) {
      window.location.assign("/login");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await api.configureNaturalLanguage(auth.token, {
        utterance,
        actor_id: auth.user.id,
        idempotency_key: createIdempotencyKey("nl_configure"),
        expected_state_revision: readStateRevision(),
      });
      setResult(response);
      await loadRules();
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
          <p className="eyebrow">规则配置</p>
          <h1>不可预约规则</h1>
          <p className="muted">自然语言配置直接写入系统状态；前端只展示后端解析和规则结果。</p>
        </div>
      </header>
      {error ? <div className="error-box">{error}</div> : null}

      <section className="card stack">
        <form onSubmit={submitConfigure} className="stack">
          <label className="field">
            <span>自然语言规则配置</span>
            <textarea value={utterance} onChange={(event) => setUtterance(event.target.value)} rows={4} />
          </label>
          <div className="row wrap">
            {examples.map((example) => (
              <button className="ghost-button" key={example} type="button" onClick={() => setUtterance(example)}>{example}</button>
            ))}
          </div>
          <button className="primary-button" disabled={loading}>{loading ? "配置中..." : "提交配置"}</button>
        </form>
      </section>

      {result ? (
        <section className="grid result-columns">
          <article className="card stack">
            <h2>解析结果</h2>
            <p><strong>意图：</strong>{result.intent}</p>
            <p><strong>匹配规则：</strong>{result.matched_rule_id ?? "新建"}</p>
            <p><strong>规则 ID：</strong>{result.rule_id}</p>
            <p><strong>状态：</strong>{result.status}</p>
            <p><strong>LLM：</strong>{result.llm.provider}/{result.llm.model}</p>
          </article>
          <article className="card stack">
            <h2>新规则窗口</h2>
            {result.new_rule?.time_windows.map((window, index) => (
              <div className="slot status-blocked_by_rule" key={index}>
                <strong>{window.start_at} - {window.end_at}</strong>
                <p>{result.new_rule?.reason}</p>
              </div>
            ))}
          </article>
        </section>
      ) : null}

      <section className="stack">
        <h2>规则列表</h2>
        {rules.length === 0 ? <button className="secondary-button" onClick={loadRules}>加载规则</button> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>ID</th><th>类型</th><th>目标</th><th>时间窗口</th><th>原因</th><th>状态</th></tr>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <tr key={rule.id}>
                    <td>{rule.id}</td>
                    <td>{rule.rule_type}</td>
                    <td>{rule.target_type}:{rule.target_id}</td>
                    <td>{rule.time_windows.map((window) => `${window.start_at} - ${window.end_at}`).join("；")}</td>
                    <td>{rule.reason}</td>
                    <td>{rule.fixed ? "固定" : "动态"}</td>
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
