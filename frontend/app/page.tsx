"use client";

import { PanelLeft, Table2, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { ChatPane, type ChatHandle } from "@/components/ChatPane";
import { DraftModal } from "@/components/DraftModal";
import { Evidence } from "@/components/evidence/Evidence";
import { Sidebar, type ThemePref } from "@/components/Sidebar";
import { api } from "@/lib/api";
import { ui } from "@/lib/i18n";
import type { ChatReply, Lang, Summary } from "@/lib/types";

// Kept in step with the rail's breakpoint in globals.css: below this the rail
// is an overlay, so opening one covers the conversation.
const NARROW = "(max-width: 900px)";
const THEME_KEY = "nexa-theme";

function applyTheme(choice: ThemePref) {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
}

export default function Page() {
  const [lang, setLang] = useState<Lang>("vi");
  const [theme, setTheme] = useState<ThemePref>("system");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [health, setHealth] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [draft, setDraft] = useState<any>(null);
  const [busyDraft, setBusyDraft] = useState(false);
  const [chatBusy, setChatBusy] = useState(false);
  // null = "not chosen yet", which CSS reads as open on desktop and closed on a
  // phone. Picking a boolean here would need the viewport width during SSR.
  const [railOpen, setRailOpen] = useState<boolean | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const chat = useRef<ChatHandle>(null);

  // The inline script in layout.tsx already put the stored choice on <html>
  // before paint. This re-applies it because React Strict Mode remounts once in
  // development and resets the attributes on <html>, dropping what the script
  // set; before paint rather than after, so the reset never becomes a flash.
  useLayoutEffect(() => {
    let stored: string | null = null;
    try { stored = localStorage.getItem(THEME_KEY); } catch { /* private mode */ }
    const choice: ThemePref =
      stored === "light" || stored === "dark" ? stored : "system";
    applyTheme(choice);
    setTheme(choice);
  }, []);

  function chooseTheme(next: ThemePref) {
    setTheme(next);
    applyTheme(next);
    try { localStorage.setItem(THEME_KEY, next); } catch { /* private mode */ }
  }

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

  // While the choice is still null the rail is open on a desktop and closed on
  // a phone, so which way this toggles can only be settled at click time.
  function toggleRail() {
    setRailOpen(railOpen === null
      ? window.matchMedia(NARROW).matches
      : !railOpen);
  }

  function askFromRail(question: string) {
    chat.current?.ask(question);
    if (railOpen !== false && window.matchMedia(NARROW).matches) setRailOpen(false);
  }

  // Below 1280px the drawer covers the conversation, so a question asked from
  // inside it would send the answer somewhere the user cannot see.
  function askFromDrawer(question: string) {
    chat.current?.ask(question);
    if (window.matchMedia("(max-width: 1279px)").matches) setDrawerOpen(false);
  }

  return (
    <div className="app">
      <Sidebar
        lang={lang}
        onLang={setLang}
        theme={theme}
        onTheme={chooseTheme}
        summary={summary}
        health={health}
        open={railOpen}
        onHide={() => setRailOpen(false)}
        onAsk={askFromRail}
        onNewChat={() => chat.current?.reset()}
        onEmailReport={requestDraft}
        busy={chatBusy}
        busyDraft={busyDraft}
      />
      <button
        className="scrim scrim-rail"
        onClick={() => setRailOpen(false)}
        aria-label={ui(lang, "hideRail")}
      />

      <div className="workspace">
        <div className="conversation">
          <header className="convo-head">
            <button
              className="icon-btn rail-toggle"
              onClick={toggleRail}
              // CSS hides this button whenever the rail is on screen, so from
              // the reader's side it only ever means "show".
              title={ui(lang, "showRail")}
              aria-label={ui(lang, "showRail")}
            >
              <PanelLeft size={18} />
            </button>
            <div className="convo-title">
              <span>{ui(lang, "tagline")}</span>
            </div>
            <button
              className="icon-btn"
              onClick={() => setDrawerOpen(!drawerOpen)}
              aria-pressed={drawerOpen}
              title={ui(lang, drawerOpen ? "closeEvidence" : "openEvidence")}
              aria-label={ui(lang, drawerOpen ? "closeEvidence" : "openEvidence")}
            >
              <Table2 size={18} />
            </button>
          </header>

          {error ? <p className="err" style={{ padding: "8px 16px" }}>{error}</p> : null}

          <ChatPane
            ref={chat}
            lang={lang}
            ownerName={summary?.account?.owner_name}
            disclaimer={summary?.disclaimer ?? ""}
            fxNote={summary?.fx?.note}
            onReply={handleReply}
            onBusyChange={setChatBusy}
          />
        </div>

        {drawerOpen ? (
          <>
            <button
              className="scrim scrim-drawer"
              onClick={() => setDrawerOpen(false)}
              aria-label={ui(lang, "closeEvidence")}
            />
            <section className="drawer">
              <div className="drawer-head">
                <span className="drawer-title">{ui(lang, "evidence")}</span>
                <button
                  className="icon-btn"
                  onClick={() => setDrawerOpen(false)}
                  title={ui(lang, "closeEvidence")}
                  aria-label={ui(lang, "closeEvidence")}
                >
                  <X size={18} />
                </button>
              </div>
              <div className="drawer-body">
                <Evidence
                  lang={lang}
                  summary={summary}
                  refreshToken={refreshToken}
                  onScan={() => setRefreshToken((value) => value + 1)}
                  onAsk={askFromDrawer}
                />
              </div>
            </section>
          </>
        ) : null}
      </div>

      {draft ? (
        <DraftModal lang={lang} draft={draft} onClose={() => setDraft(null)} />
      ) : null}
    </div>
  );
}
