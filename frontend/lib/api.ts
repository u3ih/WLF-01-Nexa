import type { ChatReply, ChatSession, Lang, Summary } from "./types";

// Same-origin by default: next.config.mjs proxies /api to the backend.
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";
const TOKEN_KEY = "nexa-auth-token";

function authHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    cache: "no-store",
    headers: { ...authHeaders() },
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText} — ${path}`);
  }
  return response.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = (payload as any)?.detail ?? response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload as T;
}

export const api = {
  // -- Auth ----------------------------------------------------------------
  login: (username: string, password: string) =>
    post<{ token: string; username: string }>("/api/auth/login", { username, password }),
  verifyToken: (token: string) =>
    post<{ valid: boolean; username: string | null }>("/api/auth/verify", { token }),

  // -- Existing endpoints --------------------------------------------------
  health: () => get<any>("/api/health"),
  summary: (lang: Lang) => get<Summary>(`/api/summary?lang=${lang}`),
  strings: (lang: Lang) =>
    get<{ strings: Record<string, string> }>(`/api/i18n/${lang}`),
  cashflow: (lang: Lang) => get<any>(`/api/cashflow?lang=${lang}`),
  findings: (lang: Lang, kind?: string) =>
    get<any>(`/api/findings?lang=${lang}${kind ? `&kind=${kind}` : ""}`),
  emailRecon: (lang: Lang, status?: string) =>
    get<any>(`/api/email-recon?lang=${lang}${status ? `&status=${status}` : ""}`),
  triSource: (lang: Lang) => get<any>(`/api/tri-source?lang=${lang}`),
  subscriptions: (lang: Lang) => get<any>(`/api/subscriptions?lang=${lang}`),
  report: (lang: Lang, period: string, key?: string) =>
    get<any>(`/api/report?lang=${lang}&period=${period}${key ? `&key=${key}` : ""}`),
  reportAll: (lang: Lang) => get<any>(`/api/report/all?lang=${lang}`),
  statement: (lang: Lang, source: "account" | "card") =>
    get<any>(`/api/statement?lang=${lang}&source=${source}`),
  reminders: (lang: Lang) => get<any>(`/api/monitor/reminders?lang=${lang}`),
  scanHistory: () => get<any>("/api/monitor/history"),
  audit: (lang: Lang, limit = 100) =>
    get<any>(`/api/audit?lang=${lang}&limit=${limit}`),
  chat: (question: string, lang: Lang) =>
    post<ChatReply>("/api/chat", { question, lang }),
  scan: (lang: Lang) => post<any>("/api/monitor/scan", { lang, trigger: "ui" }),
  draftReport: (lang: Lang, period: string, key?: string) =>
    post<any>("/api/report/draft", { lang, period, key }),
  sendReport: (token: string, lang: Lang, recipient?: string) =>
    post<any>("/api/report/send", {
      confirm_token: token,
      lang,
      confirmed: true,
      recipient,
    }),
  testSmtp: (lang: Lang, recipient?: string) =>
    post<any>("/api/report/smtp-test", { lang, recipient }),
  purge: () => post<any>("/api/audit/purge", {}),

  // -- Chat history -------------------------------------------------------
  listHistory: (limit = 50) => get<ChatSession[]>(`/api/chat/history?limit=${limit}`),
  getHistory: (id: number) => get<ChatSession>(`/api/chat/history/${id}`),
  createHistory: (title: string, lang: Lang, messages: any[]) =>
    post<ChatSession>("/api/chat/history", { title, lang, messages }),
  updateHistory: (id: number, data: { title?: string; messages?: any[]; lang?: Lang }) =>
    post<ChatSession>(`/api/chat/history/${id}`, data),
  deleteHistory: (id: number) => post<any>(`/api/chat/history/${id}/delete`, {}),
};