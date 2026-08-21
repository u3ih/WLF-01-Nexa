import type { ChatReply, Lang, Summary } from "./types";

// Same-origin by default: next.config.mjs proxies /api to the backend.
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText} — ${path}`);
  }
  return response.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
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
};
