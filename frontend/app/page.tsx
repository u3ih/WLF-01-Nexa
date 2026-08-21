"use client";

import { useCallback, useEffect, useState } from "react";

import { ChatPane } from "@/components/ChatPane";
import { DraftModal } from "@/components/DraftModal";
import { Evidence } from "@/components/Evidence";
import { api } from "@/lib/api";
import { ui } from "@/lib/i18n";
import type { ChatReply, Lang, Summary } from "@/lib/types";

export default function Page() {
  const [lang, setLang] = useState<Lang>("vi");
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [health, setHealth] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [draft, setDraft] = useState<any>(null);
  const [busyDraft, setBusyDraft] = useState(false);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [summaryData, healthData] = await Promise.all([
        api.summary(lang),
        api.health(),
      ]);
      setSummary(summaryData);
      setHealth(healthData);
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : String(exception));
    }
  }, [lang]);

  useEffect(() => { load(); }, [load]);

  // A chat turn that produced a draft opens the confirmation dialog, so the
  // "email me the report" flow always passes through an explicit confirmation.
  function handleReply(reply: ChatReply) {
    if (reply.tool === "draft_report_email" && reply.data?.confirm_token) {
      setDraft({ ...reply.data, body: reply.data.body_preview });
    }
    setRefreshToken((value) => value + 1);
  }

  async function requestDraft() {
    setBusyDraft(true);
    try {
      setDraft(await api.draftReport(lang, "month"));
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : String(exception));
    } finally {
      setBusyDraft(false);
    }
  }

  const account = summary?.account;

  return (
    <div className="shell">
      {/* Mandated notice: always visible, no dismiss control. */}
      <div className="disclaimer">
        <strong>{ui(lang, "disclaimerLabel")}</strong>
        <span>{summary?.disclaimer ?? ""}</span>
      </div>

      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">N</span>
          <span>
            <div className="brand-name">Nexa</div>
            <div className="brand-sub">{ui(lang, "tagline")}</div>
          </span>
        </div>

        <div className="topbar-meta">
          {account ? (
            <>
              <span className="chip">
                <span className="k">{account.owner_name}</span>
                <span className="v mono">{account.account_masked}</span>
                <span className="v mono">{account.card_masked}</span>
              </span>
              <span className="chip">
                <span className="k">{ui(lang, "statement")}</span>
                <span className="v mono">{account.statement_date}</span>
              </span>
            </>
          ) : null}
          <span className="chip" title={health?.llm?.detail}>
            <span className="k">{ui(lang, "model")}</span>
            <span className="v mono">
              {health?.llm?.available ? health.llm.model : ui(lang, "offline")}
            </span>
          </span>
          <button className="btn btn-sm" onClick={requestDraft} disabled={busyDraft}>
            {ui(lang, "emailReport")}
          </button>
          <button
            className="btn btn-sm"
            onClick={() => setLang(lang === "vi" ? "en" : "vi")}
          >
            {lang === "vi" ? "EN" : "VI"}
          </button>
          <button
            className="btn btn-sm btn-ghost"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? ui(lang, "theme_light") : ui(lang, "theme_dark")}
          </button>
        </div>
      </header>

      {error ? <p className="err" style={{ padding: "8px 16px" }}>{error}</p> : null}

      <main className="main">
        <ChatPane lang={lang} onReply={handleReply} />
        <Evidence
          lang={lang}
          summary={summary}
          refreshToken={refreshToken}
          onScan={() => setRefreshToken((value) => value + 1)}
        />
      </main>

      <footer className="footer">
        <div>{summary?.fx?.note}</div>
        <div style={{ marginTop: 4 }}>
          {summary
            ? `${summary.counts.account_txns} + ${summary.counts.card_txns} `
              + `rows · ${summary.counts.emails} emails · `
              + `${summary.counts.findings} findings · sample data only`
            : ""}
        </div>
      </footer>

      {draft ? (
        <DraftModal lang={lang} draft={draft} onClose={() => setDraft(null)} />
      ) : null}
    </div>
  );
}
