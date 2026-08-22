"use client";

import { Bell, PanelLeft, Table2, X } from "lucide-react";
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
import { LabelBadge } from "@/components/Badges";

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
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifTab, setNotifTab] = useState<string>("all");

  const NOTIF_TABS = [
    { id: "all", key: "notifTabAll" },
    { id: "needs_your_confirmation", key: "notifTabConfirm" },
    { id: "insufficient_data", key: "notifTabNodata" },
    { id: "recurring_confirmed", key: "notifTabRecurring" },
  ] as const;

  // ── Notifications từ findings data (mock nội dung) ──────────────────
  // Dùng findings từ summary nếu có, fallback về mock data
  // 3 trạng thái: needs_your_confirmation / insufficient_data / recurring_confirmed
  const findings = summary?.findings ?? [];
  const notifList = findings.length > 0
    ? findings.map((f) => ({
        id: f.id,
        title: f.title,
        detail: f.detail,
        badgeKey: f.label,           // "needs_your_confirmation" | "insufficient_data" | "recurring_confirmed"
        badgeText: f.label_text,
        isAlert: f.label !== "recurring_confirmed",
        time: f.occurred_on ?? "",
      }))
    : [
        {
          id: "mock-1",
          title: lang === "vi" ? "Phát hiện giao dịch bất thường" : "Abnormal transaction detected",
          detail: lang === "vi"
            ? "AliExpress $237.21 — Tần suất cao (3 giao dịch trong 30 phút)"
            : "AliExpress $237.21 — Unusual frequency (3 transactions in 30 min)",
          badgeKey: "needs_your_confirmation" as const,
          badgeText: lang === "vi" ? "Cần bạn tự xác nhận" : "Needs your confirmation",
          isAlert: true,
          time: new Date(Date.now() - 2 * 3600_000).toISOString(),
        },
        {
          id: "mock-2",
          title: lang === "vi" ? "Nghi tính trùng" : "Possible duplicate charge",
          detail: lang === "vi"
            ? "Spotify $9.99 — Hai giao dịch giống nhau trong cùng ngày"
            : "Spotify $9.99 — Two identical transactions on the same day",
          badgeKey: "needs_your_confirmation" as const,
          badgeText: lang === "vi" ? "Cần bạn tự xác nhận" : "Needs your confirmation",
          isAlert: true,
          time: new Date(Date.now() - 24 * 3600_000).toISOString(),
        },
        {
          id: "mock-3",
          title: lang === "vi" ? "Email nghi giả mạo" : "Suspicious email detected",
          detail: lang === "vi"
            ? "netfl1x-billing.com — Email giả mạo thương hiệu Netflix"
            : "netfl1x-billing.com — Impersonation email claiming to be Netflix",
          badgeKey: "insufficient_data" as const,
          badgeText: lang === "vi" ? "Chưa đủ dữ liệu" : "Insufficient data",
          isAlert: true,
          time: new Date(Date.now() - 24 * 3600_000).toISOString(),
        },
        {
          id: "mock-4",
          title: lang === "vi" ? "Tiền rời tài khoản chưa lên thẻ" : "Transfer not on card",
          detail: lang === "vi"
            ? "$2,014.08 — Giao dịch rút tiền không khớp sao kê thẻ"
            : "$2,014.08 — Withdrawal doesn't match card statement",
          badgeKey: "insufficient_data" as const,
          badgeText: lang === "vi" ? "Chưa đủ dữ liệu" : "Insufficient data",
          isAlert: true,
          time: new Date(Date.now() - 2 * 24 * 3600_000).toISOString(),
        },
        {
          id: "mock-5",
          title: lang === "vi" ? "Tập trung chi tiêu bất thường" : "Abnormal spending concentration",
          detail: lang === "vi"
            ? "Subscription — Chiếm 72% tổng chi tiêu"
            : "Subscription — 72% of total spending",
          badgeKey: "recurring_confirmed" as const,
          badgeText: lang === "vi" ? "Định kỳ đã xác định" : "Recurring confirmed",
          isAlert: false,
          time: new Date(Date.now() - 3 * 24 * 3600_000).toISOString(),
        },
      ];

  const hasRealFindings = (summary?.findings?.length ?? 0) > 0;
  const alertCount = notifList.filter((n) => n.isAlert).length;
  const filteredNotifs = notifTab === "all"
    ? notifList
    : notifList.filter((n) => n.badgeKey === notifTab);

  const OVERDUE_DAYS = 60;

  function formatNotifTime(iso: string): { text: string; expired: boolean } {
    if (!iso) return { text: "", expired: false };
    const diffMs = Date.now() - new Date(iso).getTime();
    const days = Math.floor(diffMs / (24 * 3600_000));
    if (days > OVERDUE_DAYS) {
      return {
        text: lang === "vi" ? "Đã quá hạn" : "Expired",
        expired: true,
      };
    }
    const mins = Math.floor(diffMs / 60_000);
    if (mins < 1) return { text: lang === "vi" ? "Vừa xong" : "Just now", expired: false };
    if (mins < 60) return { text: lang === "vi" ? `${mins} phút trước` : `${mins} min ago`, expired: false };
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return { text: lang === "vi" ? `${hrs} giờ trước` : `${hrs} hours ago`, expired: false };
    if (days === 1) return { text: lang === "vi" ? "Hôm qua" : "Yesterday", expired: false };
    return { text: lang === "vi" ? `${days} ngày trước` : `${days} days ago`, expired: false };
  }

  // Click outside to close dropdown
  const notifRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) {
        setNotifOpen(false);
      }
    }
    if (notifOpen) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [notifOpen]);

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
            <div className="convo-actions" ref={notifRef}>
              <button
                className="icon-btn notif-bell-btn"
                onClick={() => setNotifOpen(!notifOpen)}
                aria-pressed={notifOpen}
                title={ui(lang, "notifLabel")}
                aria-label={ui(lang, "notifLabel")}
              >
                <Bell size={18} />
                {hasRealFindings && alertCount > 0 && (
                  <span className="notif-bell-dot">{alertCount}</span>
                )}
              </button>

              {notifOpen && (
                <div className="notif-dropdown" onMouseDown={(e) => e.stopPropagation()}>
                  <div className="notif-dropdown-head">
                    <span>{ui(lang, "notifLabel")}</span>
                    <span className="chip">{notifList.length}</span>
                  </div>

                  <div className="notif-dd-tabs" role="tablist">
                    {NOTIF_TABS.map((tab) => {
                      const count = tab.id === "all"
                        ? notifList.length
                        : notifList.filter((n) => n.badgeKey === tab.id).length;
                      return (
                        <button
                          key={tab.id}
                          role="tab"
                          aria-selected={notifTab === tab.id}
                          className="notif-dd-tab"
                          onClick={(e) => { e.stopPropagation(); setNotifTab(tab.id); }}
                        >
                          {ui(lang, tab.key as never)}
                          {count > 0 && (
                            <span className="notif-dd-tab-count">{count}</span>
                          )}
                        </button>
                      );
                    })}
                  </div>

                  <div className="notif-dd-list">
                    {filteredNotifs.length === 0 ? (
                      <div className="notif-dd-empty">
                        {ui(lang, "notifEmpty")}
                      </div>
                    ) : (
                      filteredNotifs.map((n) => {
                        const ft = formatNotifTime(n.time);
                        return (
                          <div
                            key={n.id}
                            className={`notif-dd-item ${ft.expired ? "notif-dd-expired" : ""}`}
                          >
                            <div className="notif-dd-body">
                              <div className="notif-dd-head">
                                <span className="notif-dd-title">{n.title}</span>
                                <LabelBadge
                                  label={n.badgeKey}
                                  text={n.badgeText}
                                />
                              </div>
                              <p className="notif-dd-desc">{n.detail}</p>
                              <span className={`notif-dd-time ${ft.expired ? "notif-dd-time-expired" : ""}`}>
                                {ft.text}
                              </span>
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              )}

              <button
                className="icon-btn"
                onClick={() => setDrawerOpen(!drawerOpen)}
                aria-pressed={drawerOpen}
                title={ui(lang, drawerOpen ? "closeEvidence" : "openEvidence")}
                aria-label={ui(lang, drawerOpen ? "closeEvidence" : "openEvidence")}
              >
                <Table2 size={18} />
              </button>
            </div>
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
