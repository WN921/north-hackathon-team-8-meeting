import { NextRequest, NextResponse } from "next/server";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { TextEncoder } from "node:util";

type ChatRequest = {
  message: string;
  environment?: string;
  sessionId?: string;
};

type SsePayload = {
  type: "stdout" | "stderr" | "error" | "done";
  content?: string;
  code?: number;
};

const DEFAULT_NAC_BASE_URL = "https://nac-beta.xiaobei.top/";
const DEFAULT_NAC_ENVIRONMENT = "test";
const DEFAULT_NAC_PROJECT_ID = "e4ebe630-1c26-48d0-8d29-4563375ee959";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const payload = (await request.json().catch(() => null)) as Partial<ChatRequest> | null;
  const message = payload?.message?.trim();

  if (!message) {
    return NextResponse.json(
      { error: { code: "INVALID_MESSAGE", message: "message 不能为空" } },
      { status: 400 },
    );
  }

  const token = process.env.NAC_TOKEN ?? process.env.NAC_GATEWAY_TOKEN;
  if (!token) {
    return NextResponse.json(
      { error: { code: "NAC_TOKEN_REQUIRED", message: "服务端未配置 NAC_TOKEN / NAC_GATEWAY_TOKEN" } },
      { status: 500 },
    );
  }

  const environment = payload?.environment ?? process.env.NAC_ENVIRONMENT ?? DEFAULT_NAC_ENVIRONMENT;
  const baseUrl = process.env.NAC_BASE_URL ?? DEFAULT_NAC_BASE_URL;
  const projectId = process.env.NAC_PROJECT_ID ?? DEFAULT_NAC_PROJECT_ID;

  const child = spawn("nac", buildChatArgs(environment, baseUrl, projectId, payload?.sessionId), {
    env: {
      ...process.env,
      NAC_TOKEN: token,
      NAC_BASE_URL: baseUrl,
      NAC_PROJECT_ID: projectId,
    },
    stdio: ["pipe", "pipe", "pipe"],
  });

  const headers = new Headers({
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
  });
  if (payload?.sessionId) {
    headers.set("x-nac-session-id", payload.sessionId);
  }

  const stream = createChatStream(child, message, request.signal);

  return new Response(stream, {
    status: 200,
    headers,
  });
}

function buildChatArgs(environment: string, baseUrl: string, projectId: string, sessionId?: string) {
  const args = [
    "chat",
    environment,
    "--stdin",
    "--compact",
    "--base-url",
    baseUrl,
    "--project-id",
    projectId,
  ];

  if (sessionId) {
    args.push("--session", sessionId);
  }

  return args;
}

function createChatStream(child: ChildProcessWithoutNullStreams, message: string, signal: AbortSignal) {
  const encoder = new TextEncoder();
  let settled = false;

  return new ReadableStream<Uint8Array>({
    start(controller) {
      const enqueue = (payload: SsePayload) => {
        if (settled) return;
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(payload)}\n\n`));
      };

      const close = () => {
        if (settled) return;
        settled = true;
        enqueue({ type: "done" });
        controller.close();
      };

      const fail = (code: number, content: string) => {
        if (settled) return;
        settled = true;
        enqueue({ type: "error", code, content });
        controller.close();
      };

      child.stdout.on("data", (chunk: Buffer) => {
        enqueue({ type: "stdout", content: chunk.toString("utf8") });
      });

      child.stderr.on("data", (chunk: Buffer) => {
        enqueue({ type: "stderr", content: chunk.toString("utf8") });
      });

      child.on("error", (error) => {
        fail(1, error.message.includes("ENOENT") ? "未找到 nac CLI。请在服务端安装 NAC CLI。" : error.message);
      });

      child.on("exit", (code) => {
        if (code === 0) {
          close();
          return;
        }
        fail(code ?? 1, `nac chat 退出，退出码 ${code ?? "unknown"}`);
      });

      child.stdin.write(message, (error) => {
        if (error) {
          fail(1, error.message);
        }
      });
      child.stdin.end();

      const abort = () => {
        if (settled) return;
        settled = true;
        child.kill("SIGTERM");
        enqueue({ type: "error", code: 499, content: "请求已取消" });
        controller.close();
      };

      signal.addEventListener("abort", abort, { once: true });
    },
    cancel() {
      if (!settled) {
        settled = true;
        child.kill("SIGTERM");
      }
    },
  });
}
