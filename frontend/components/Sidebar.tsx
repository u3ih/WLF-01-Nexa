"use client";

import {
  Languages, Mail, MessageSquare, Monitor, Moon, PanelLeft, Plus, Sun,
} from "lucide-react";

import { BrandMark } from "@/components/BrandMark";
import { ALL_QUESTIONS, ui } from "@/lib/i18n";
import type { Lang, Summary } from "@/lib/types";

export type ThemePref = "system" | "light" | "dark";

const THEME_ORDER: ThemePref[] = ["system", "light", "dark"];
const THEME_ICON = { system: Monitor, light: Sun, dark: Moon };
const THEME_KEY = {
  system: "theme_system", light: "theme_light", dark: "theme_dark",
} as const;

export function Sidebar({
  lang, onLang, theme, onTheme, summary, health, open, onHide,
  onAsk, onNewChat, onEmailReport, busy, busyDraft,
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
}) {
  const account = summary?.account;
  const ThemeIcon = THEME_ICON[theme];

  return (
    <aside
      className="rail"
      data-open={open === null ? "default" : String(open)}
      aria-hidden={open === false}
    >
      <div className="rail-top">
        <div className="brand">
          <BrandMark size={30} />
          <span className="brand-text">
            <span className="brand-name">Nexa</span>
            <span className="brand-sub">for Wealify · WLF-01</span>
          </span>
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
        {/* One unlabelled list: the three refusal probes sit among the ordinary
            questions, because a product does not advertise what it will decline. */}
        <div className="rail-group">
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
        </div>

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
                    ? `${account.virtual_accounts.length} ${
                        lang === "vi" ? "tài khoản nhận" : "receiving"
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

        <p
          className="rail-note"
          title={health?.llm?.detail ?? undefined}
        >
          {ui(lang, "model")}:{" "}
          {health?.llm?.available ? health.llm.model : ui(lang, "offline")}
        </p>
        {/* The ₫ rate disclosure sits here rather than under the composer: it
            is ours to explain, not part of the notice the brief mandates, and
            that notice now runs in full with nothing folded away beside it. */}
        {summary?.fx?.note ? (
          <p className="rail-note rail-note-fx" title={summary.fx.note}>
            {summary.fx.note}
          </p>
        ) : null}
      </div>
    </aside>
  );
}
