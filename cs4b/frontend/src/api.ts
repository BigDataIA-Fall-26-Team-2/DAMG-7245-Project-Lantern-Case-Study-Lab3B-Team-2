import type { AskResponse, Economics, Health, Mode, RecordedQuestion, SchemaTable } from "./types";

// Same origin in dev (Vite proxies /api to FastAPI). Override with VITE_API_BASE.
const BASE: string = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "network", "Can't reach the API. Is the backend running on port 8000?");
  }
  if (!res.ok) {
    let code = `http_${res.status}`;
    let message = res.statusText || "Request failed";
    try {
      const body = await res.json();
      const d = body?.detail;
      if (d && typeof d === "object" && !Array.isArray(d)) {
        code = d.code ?? code;
        message = d.message ?? message;
      } else if (Array.isArray(d)) {
        code = "invalid_request";
        message = d.map((e: { msg?: string }) => e.msg).filter(Boolean).join("; ") || message;
      } else if (typeof d === "string") {
        message = d;
      }
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, code, message);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => call<Health>("/health"),
  questions: () => call<RecordedQuestion[]>("/questions"),
  schema: () => call<{ tables: SchemaTable[] }>("/schema").then((r) => r.tables),
  economics: () => call<Economics>("/economics"),
  newConversation: (mode: Mode) =>
    call<{ thread_id: string; mode: Mode }>("/conversations", { method: "POST", body: JSON.stringify({ mode }) }).then(
      (r) => r.thread_id,
    ),
  ask: (question: string, thread_id: string | null | undefined, mode: Mode) =>
    call<AskResponse>("/ask", {
      method: "POST",
      body: JSON.stringify(thread_id ? { question, thread_id, mode } : { question, mode }),
    }),
};
