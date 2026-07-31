"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { readStoredAuth } from "@/lib/api";

type ChatMessage = {
  role: "user" | "assistant" | "system";
  content: string;
  at: string;
};

type ChatResponse = {
  sessionId?: string;
  content?: string;
  error?: {
    code: string;
    message: string;
    details?: string;
  };
};

const examples = [
  "查询下周二 10:00-11:00 有哪些小会议室可用？",
  "明天中午预约活动室，如果可以的话帮我创建预约。",
  "504 全天临时维修，然后改成只停用下午。",
  "查看今天的日历和平面图状态。",
];

export default function Page() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "system",
      content: "这里通过 NAC Agent Gateway 调用 meeting_assistant。写操作仍由 Agent 通过 FastAPI 完成，前端只负责对话和流式展示。",
      at: new Date().toISOString(),
    },
  ]);
  const [input, setInput] = useState("");
  const [environment, setEnvironment] = useState("test");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const streamRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const stored = readStoredAuth();
    if (!stored) {
      window.location.assign("/login");
      return;
    }
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = input.trim();
    if (!message || loading) return;

    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    setInput("");

    const userMessage: ChatMessage = { role: "user", content: message, at: new Date().toISOString() };
    const assistantMessage: ChatMessage = { role: "assistant", content: "", at: new Date().toISOString() };
    setMessages((current) => [...current, userMessage, assistantMessage]);

    try {
      const response = await fetch("/api/nac/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, environment, sessionId }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        const payload = (await response.json().catch(() => null)) as ChatResponse | null;
        throw new Error(payload?.error?.message ?? `NAC Chat 请求失败：HTTP ${response.status}`);
      }

      const nextSessionId = response.headers.get("x-nac-session-id") ?? sessionId;
      if (nextSessionId) setSessionId(nextSessionId);

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      streamRef.current = reader;
      let buffer = "";
      let assistantText = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split(/\r?\n/);
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          const parsed = parseSseLine(line);
          if (!parsed) continue;

          if (parsed.sessionId && !sessionId && !nextSessionId) {
            setSessionId(parsed.sessionId);
          }

          if (parsed.content) {
            assistantText += parsed.content;
            setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, content: assistantText } : item));
          }

          if (parsed.error) {
            throw new Error(parsed.error.message);
          }
        }
      }

      if (buffer.trim()) {
        const parsed = parseSseLine(buffer);
        if (parsed?.content) {
          assistantText += parsed.content;
          setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, content: assistantText } : item));
        }
      }

      if (!assistantText.trim()) {
        setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, content: "Agent 已响应，但本次流式内容暂无可读文本。" } : item));
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "NAC Chat 请求失败";
      setError(message);
      setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, content: item.content || `请求失败：${message}` } : item));
    } finally {
      setLoading(false);
      streamRef.current = null;
      abortRef.current = null;
    }
  }

  function stopStream() {
    abortRef.current?.abort();
    streamRef.current?.cancel().catch(() => undefined);
  }

  function resetSession() {
    setSessionId(undefined);
    setMessages([messages[0]]);
    setError(null);
  }

  return (
    <main className="page-shell agent-page">
      <header className="section-header">
        <div>
          <p className="eyebrow">NAC Agent</p>
          <h1>会务 Agent 对话</h1>
          <p className="muted">前端页面通过 BFF 调用 NAC Gateway，支持流式输出；Agent 仍通过 FastAPI 工具执行会务查询、规则配置、预约、取消、日历和平面图操作。</p>
        </div>
      </header>

      {error ? <div className="error-box">{error}</div> : null}

      <section className="card agent-config">
        <div className="grid filters">
          <label className="field">
            <span>NAC environment</span>
            <input value={environment} onChange={(event) => setEnvironment(event.target.value)} placeholder="hack-8" />
          </label>
          <label className="field">
            <span>Session</span>
            <input value={sessionId ?? ""} readOnly placeholder="首次请求后由 Gateway 返回" />
          </label>
          <div className="row wrap agent-actions">
            <button className="secondary-button" type="button" onClick={resetSession}>新建会话</button>
            {loading ? (
              <button className="danger-button" type="button" onClick={stopStream}>停止生成</button>
            ) : null}
          </div>
        </div>
        <p className="muted">提示：真实 AK/SK 只配置在服务端环境变量 NAC_TOKEN / NAC_GATEWAY_TOKEN，不会写入页面或浏览器。</p>
      </section>

      <section className="card chat-window" aria-live="polite">
        <div className="chat-list">
          {messages.map((message, index) => (
            <article className={`chat-message ${message.role}`} key={`${message.role}-${message.at}-${index}`}>
              <div className="chat-meta">{roleLabel(message.role)} · {new Date(message.at).toLocaleString()}</div>
              <div className="chat-content">{message.content || (message.role === "assistant" && loading ? <span className="typing-dot" /> : null)}</div>
            </article>
          ))}
          <div ref={bottomRef} />
        </div>
      </section>

      <form className="card chat-composer" onSubmit={send}>
        <label className="field">
          <span>给 meeting_assistant 发送消息</span>
          <textarea value={input} onChange={(event) => setInput(event.target.value)} rows={4} placeholder="例如：下周二 10:00-11:00 有哪些小会议室可用？" />
        </label>
        <div className="row wrap">
          {examples.map((example) => (
            <button className="ghost-button" key={example} type="button" onClick={() => setInput(example)} disabled={loading}>{example}</button>
          ))}
        </div>
        <button className="primary-button" disabled={loading || !input.trim()} type="submit">{loading ? "生成中..." : "发送"}</button>
      </form>
    </main>
  );
}

function parseSseLine(line: string): Partial<ChatResponse> | null {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith(":")) return null;
  if (trimmed.startsWith("data:")) {
    const raw = trimmed.slice(5).trim();
    if (!raw) return null;
    try {
      return JSON.parse(raw) as ChatResponse;
    } catch {
      return { content: `${raw}\n` };
    }
  }
  return null;
}

function roleLabel(role: ChatMessage["role"]) {
  if (role === "user") return "我";
  if (role === "system") return "系统";
  return "meeting_assistant";
}
