"use client";

import {
  Clock, Languages, Mail, MessageSquare, Monitor, Moon, PanelLeft, Plus, Sun, Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";

import { BrandMark } from "@/components/BrandMark";
import { ALL_QUESTIONS, ui } from "@/lib/i18n";
import type { ChatSession, Lang, Summary } from "@/lib/types";

export type ThemePref = "system" | "light" | "dark";

const THEME_ORDER: ThemePref[] = ["system", "light", "dark"];
const THEME_ICON = { system: Monitor, light: Sun, dark: Moon };
const THEME_KEY = {
  system: "theme_system", light: "theme_light", dark: "theme_dark",
} as const;

function timeAgo(dateStr: string, lang: Lang): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return ui(lang, "today");
  if (diffDays === 1) return ui(lang, "yesterday");
  if (diffDays < 7) return ui(lang, "thisWeek");
  return ui(lang, "earlier");
}

export function Sidebar({
  lang, onLang, theme, onTheme, summary, health, open, onHide,
  onAsk, onNewChat, onEmailReport, busy, busyDraft,
  history, activeSessionId, onSelectHistory, onDeleteHistory, onShowHistoryModal,
}: {
  lang: Lang;
  onLang: (lang: Lang) => void;
  theme: ThemePref;
  onTheme: (theme: ThemePref) => void;
  summary: Summary | null;
  health: any;
  /** null until the user chooses: CSS reads that as open on a desktop and
   *  closed on a phone, which SSR cannot decide on its own. */
  open: boolean | null;
  onHide: () => void;
  onAsk: (question: string) => void;
  onNewChat: () => void;
  onEmailReport: () => void;
  busy: boolean;
  busyDraft: boolean;
  history: ChatSession[];
  activeSessionId: number | null;
  onSelectHistory: (session: ChatSession) => void;
  onDeleteHistory: (id: number) => void;
  onShowHistoryModal: () => void;
}) {
  const account = summary?.account;
  const ThemeIcon = THEME_ICON[theme];
  const [historyOpen, setHistoryOpen] = useState(true);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [systemDark, setSystemDark] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    setSystemDark(mq.matches);
    const handler = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const isDark = theme === "dark" || (theme === "system" && systemDark);
  const logoSrc = isDark ? "/images/dark-logo.png" : "/images/logo.png";

  return (
    <aside
      className="rail"
      data-open={open === null ? "default" : String(open)}
      aria-hidden={open === false}
    >
      <div className="rail-top">
        <div className="brand">
          <img src={logoSrc} className="brand-image" alt="Nexa Logo" />
        </div>
        <button className="icon-btn" onClick={onHide} title={ui(lang, "hideRail")}
          aria-label={ui(lang, "hideRail")}>
          <PanelLeft size={18} />
        </button>
      </div>

      <button className="rail-item rail-new" onClick={onNewChat}>
        <Plus size={17} />
        <span className="rail-item-text">{ui(lang, "newChat")}</span>
      </button>

      <div className="rail-scroll">
        {/* Chat History Section */}
        <div className="rail-group">
          <div className="rail-label rail-label-click"
            onClick={() => setHistoryOpen(!historyOpen)}
            role="button" tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setHistoryOpen(!historyOpen); }}>
            <span>{ui(lang, "history")}</span>
            <span className={`rail-chevron ${historyOpen ? "open" : ""}`}>&#9662;</span>
          </div>
          {historyOpen && (
            <>
              {history.length === 0 ? (
                <div className="rail-empty">{ui(lang, "historyEmpty")}</div>
              ) : (
                <>
                  {history.slice(0, 8).map((session) => (
                    <div
                      key={session.id}
                      className={`rail-item rail-history-item ${activeSessionId === session.id ? "active" : ""}`}
                      onClick={() => onSelectHistory(session)}
                      role="button" tabIndex={0}
                      onKeyDown={(e) => { if (e.key === "Enter") onSelectHistory(session); }}
                    >
                      <Clock size={15} className="rail-history-icon" />
                      <span className="rail-item-text rail-history-text">
                        <span className="rail-history-title">{session.title || ui(lang, "newChat")}</span>
                        <span className="rail-history-time">{timeAgo(session.updated_at, lang)}</span>
                      </span>
                      {confirmDeleteId === session.id ? (
                        <button
                          className="rail-history-delete confirm"
                          onClick={(e) => {
                            e.stopPropagation();
                            onDeleteHistory(session.id);
                            setConfirmDeleteId(null);
                          }}
                          title={ui(lang, "deleteConfirm")}
                          aria-label={ui(lang, "deleteConfirm")}
                        >
                          {ui(lang, "deleteHistory")}
                        </button>
                      ) : (
                        <button
                          className="rail-history-delete"
                          onClick={(e) => {
                            e.stopPropagation();
                            setConfirmDeleteId(session.id);
                          }}
                          title={ui(lang, "deleteHistory")}
                          aria-label={ui(lang, "deleteHistory")}
                        >
                          <Trash2 size={13} />
                        </button>
                      )}
                    </div>
                  ))}
                  {history.length > 8 && (
                    <button
                      className="rail-item rail-view-all"
                      onClick={onShowHistoryModal}
                    >
                      <span className="rail-item-text">
                        {lang === "vi" ? "Xem tất cả..." : "View all..."}
                      </span>
                    </button>
                  )}
                </>
              )}
            </>
          )}
        </div>

        {/* One unlabelled list: the three refusal probes sit among the ordinary
            questions, because a product does not advertise what it will decline. */}
        {/* <div className="rail-group">
          <div className="rail-label">{ui(lang, "suggestions")}</div>
          {ALL_QUESTIONS[lang].map((question) => (
            <button
              className="rail-item"
              key={question}
              onClick={() => onAsk(question)}
              disabled={busy}
              title={question}
            >
              <MessageSquare size={15} />
              <span className="rail-item-text">{question}</span>
            </button>
          ))}
        </div> */}

        {account ? (
          <div className="rail-group">
            <div className="rail-label">{ui(lang, "accountLabel")}</div>
            <div className="acct">
              {/* Some exports name the holder, others only register an
                  address. Whichever is present identifies the account. */}
              <div className="acct-name">
                {account.owner_name || account.owner_email}
              </div>
              <div className="acct-row">
                <span>{ui(lang, "statement")}</span>
                <span className="v mono">{account.statement_date}</span>
              </div>
              <div className="acct-row">
                <span>{lang === "vi" ? "Tài khoản" : "Account"}</span>
                <span className="v mono">
                  {account.virtual_accounts?.length
                    ? `${account.virtual_accounts.length} ${lang === "vi" ? "tài khoản nhận" : "receiving"
                    }`
                    : account.account_masked}
                </span>
              </div>
              <div className="acct-row">
                <span>{lang === "vi" ? "Thẻ" : "Card"}</span>
                {/* An account can hold several cards and this export carries no
                    PAN, so the count is the honest summary; the cards tab lists
                    them by name and code. */}
                <span className="v mono">
                  {account.cards?.length
                    ? `${account.cards.length} ${lang === "vi" ? "thẻ" : "cards"}`
                    : account.card_masked}
                </span>
              </div>
              {account.currencies && account.currencies.length > 1 ? (
                <div className="acct-row">
                  <span>{lang === "vi" ? "Tiền tệ" : "Currencies"}</span>
                  <span className="v mono">{account.currencies.join(" · ")}</span>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>

      <div className="rail-foot">
        <button className="rail-item" onClick={onEmailReport} disabled={busyDraft}>
          <Mail size={16} />
          <span className="rail-item-text">{ui(lang, "emailReport")}</span>
        </button>

        <div className="rail-toggles">
          <button
            className="btn btn-sm btn-ghost"
            onClick={() => onLang(lang === "vi" ? "en" : "vi")}
            title={ui(lang, "langHint")}
          >
            <Languages size={14} />
            {lang === "vi" ? "Tiếng Việt" : "English"}
          </button>
          <button
            className="btn btn-sm btn-ghost"
            onClick={() =>
              onTheme(THEME_ORDER[(THEME_ORDER.indexOf(theme) + 1) % THEME_ORDER.length])
            }
            title={`${ui(lang, "theme_hint")}: ${ui(lang, THEME_KEY[theme])}`}
          >
            <ThemeIcon size={14} />
          </button>
        </div>
      </div>
    </aside>
  );
}
