"use client";

import { PanelLeft, Table2, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { ChatPane, type ChatHandle } from "@/components/ChatPane";
import { DraftModal } from "@/components/DraftModal";
import { Evidence } from "@/components/evidence/Evidence";
import { HistoryModal } from "@/components/HistoryModal";
import { Sidebar, type ThemePref } from "@/components/Sidebar";
import { api } from "@/lib/api";
import { ui } from "@/lib/i18n";
import { viewForTool, type RefFocus } from "@/lib/refs";
import type { ChatReply, ChatSession, Lang, Summary, Turn } from "@/lib/types";

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
  // Mounted on first open and kept from then on, so closing animates too. It
  // starts unmounted so the evidence endpoints are not called on page load.
  const [drawerMounted, setDrawerMounted] = useState(false);
  const [focus, setFocus] = useState<RefFocus | null>(null);
  const chat = useRef<ChatHandle>(null);
  const [historyModalOpen, setHistoryModalOpen] = useState(false);

  // -- Chat history state -------------------------------------------------
  const [history, setHistory] = useState<ChatSession[]>([]);
  const [sessionId, setSessionId] = useState<number | null>(null);
  // The conversation the chat pane is holding, as an object that is *replaced*
  // on every switch. A save runs from a callback that was created before the
  // switch, and it captures this object rather than reading the id at the time
  // it runs — so it writes to the session its answer was asked in and cannot be
  // redirected into whichever session the user has opened since. Reading a
  // plain id here is what let one conversation overwrite another.
  const open = useRef<{ id: number | null }>({ id: null });
  // Loading a session is a round trip. This says which click is the live one,
  // so a slower earlier load cannot land on top of a later choice.
  const loadGen = useRef(0);
  // Saves run one at a time: two answers landing together would otherwise both
  // see "no session yet" and each create a row for the same conversation.
  const saveChain = useRef<Promise<void>>(Promise.resolve());

  const refreshHistory = useCallback(() => {
    api.listHistory().then(setHistory).catch(() => { });
  }, []);

  useEffect(() => { refreshHistory(); }, [refreshHistory]);

  /** Points the pane at another conversation. `turns` of null means a blank
   *  one. The pointer and the thread move together, which is what keeps a save
   *  and the turns it is saving talking about the same session. */
  function switchTo(id: number | null, turns: Turn[] | null) {
    loadGen.current += 1;
    open.current = { id };
    setSessionId(id);
    if (turns === null) chat.current?.reset();
    else chat.current?.loadTurns(turns);
  }

  function startNewChat() {
    switchTo(null, null);
  }

  async function handleSelectHistory(session: ChatSession) {
    const gen = ++loadGen.current;
    try {
      const full = await api.getHistory(session.id);
      // Superseded by a later click, or by "new chat", while this was loading.
      if (gen !== loadGen.current) return;
      switchTo(session.id, full.messages ?? []);
      setError(null);
    } catch (exception) {
      // Silence here read as "clicking the session does nothing".
      setError(exception instanceof Error ? exception.message : String(exception));
    }
  }

  async function handleDeleteHistory(id: number) {
    // Detach first. If this is the open conversation, a save firing afterwards
    // would try to write to a row that is going away: that write fails, and
    // every turn since would then be stored nowhere.
    if (open.current.id === id) switchTo(null, null);
    try {
      await api.deleteHistory(id);
    } catch { /* a row already gone is the outcome asked for */ }
    refreshHistory();
  }

  /** Persists the conversation an answer landed in. The turns are passed in
   *  rather than read back from the pane, so this cannot pick up a thread the
   *  user switched to while the answer was in flight. */
  function saveCurrentChat(turns: Turn[]) {
    if (turns.length === 0) return;
    const target = open.current;
    saveChain.current = saveChain.current.then(async () => {
      try {
        if (target.id !== null) {
          await api.updateHistory(target.id, { messages: turns, lang });
        } else {
          const title =
            turns.find((t) => t.role === "user")?.text?.slice(0, 80) || "";
          const created = await api.createHistory(title, lang, turns);
          // Recorded on the captured object, so a save queued behind this one
          // updates the new row instead of creating a second one for the same
          // conversation — and so a switch in between leaves it alone.
          target.id = created.id;
          if (target === open.current) setSessionId(created.id);
        }
      } catch { /* history is a convenience; a failed save must not break chat */ }
      refreshHistory();
    });
  }

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

  useEffect(() => {
    if (drawerOpen) setDrawerMounted(true);
  }, [drawerOpen]);

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
  function handleReply(reply: ChatReply, turns: Turn[]) {
    if (reply.tool === "draft_report_email" && reply.data?.confirm_token) {
      setDraft({ ...reply.data, body: reply.data.body_preview });
    }
    setRefreshToken((value) => value + 1);
    saveCurrentChat(turns);
  }

  /** A reference in an answer opens the evidence view that lists it. The panel
   *  is the only place the underlying row exists — nothing here leaves the app. */
  function showRef(ref: string, tool: string | null) {
    setDrawerOpen(true);
    setFocus((previous) => ({
      ref, view: viewForTool(tool), seq: (previous?.seq ?? 0) + 1,
    }));
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
        onNewChat={startNewChat}
        onEmailReport={requestDraft}
        busy={chatBusy}
        busyDraft={busyDraft}
        history={history}
        activeSessionId={sessionId}
        onSelectHistory={handleSelectHistory}
        onDeleteHistory={handleDeleteHistory}
        onShowHistoryModal={() => setHistoryModalOpen(true)}
      />
      <button
        className="scrim scrim-rail"
        data-open={railOpen === true}
        onClick={() => setRailOpen(false)}
        aria-label={ui(lang, "hideRail")}
        tabIndex={railOpen === true ? 0 : -1}
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
            onReply={handleReply}
            onBusyChange={setChatBusy}
            onRef={showRef}
          />
        </div>

        {drawerMounted ? (
          <>
            <button
              className="scrim scrim-drawer"
              data-open={drawerOpen}
              onClick={() => setDrawerOpen(false)}
              aria-label={ui(lang, "closeEvidence")}
              tabIndex={drawerOpen ? 0 : -1}
            />
            <section
              className="drawer"
              data-open={drawerOpen}
              aria-hidden={!drawerOpen}
            >
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
                  focus={focus}
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

      {historyModalOpen ? (
        <HistoryModal
          lang={lang}
          history={history}
          onSelect={handleSelectHistory}
          onDelete={handleDeleteHistory}
          onClose={() => setHistoryModalOpen(false)}
        />
      ) : null}
    </div>
  );
}
