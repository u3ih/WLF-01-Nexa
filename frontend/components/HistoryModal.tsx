"use client";

import {
  History, MessageSquare, Search, Trash2, X,
} from "lucide-react";
import { useMemo, useState } from "react";

import { ui } from "@/lib/i18n";
import type { ChatSession, Lang } from "@/lib/types";

function formatDate(dateStr: string, lang: Lang): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  const time = date.toLocaleTimeString(lang === "vi" ? "vi-VN" : "en-US", {
    hour: "2-digit", minute: "2-digit",
  });

  if (diffDays === 0) return `${ui(lang, "today")} ${time}`;
  if (diffDays === 1) return ui(lang, "yesterday");
  if (diffDays < 7) {
    const days = ["CN", "T2", "T3", "T4", "T5", "T6", "T7"];
    const enDays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const dayNames = lang === "vi" ? days : enDays;
    return `${dayNames[date.getDay()]} ${time}`;
  }
  return date.toLocaleDateString(lang === "vi" ? "vi-VN" : "en-US", {
    day: "numeric", month: "short",
  });
}

export function HistoryModal({
  lang, history, onSelect, onDelete, onClose,
}: {
  lang: Lang;
  history: ChatSession[];
  onSelect: (session: ChatSession) => void;
  /** Owns the deletion itself — including detaching the open conversation, so
   *  this list is not a second place that can delete a session on its own. */
  onDelete: (id: number) => void | Promise<void>;
  onClose: () => void;
}) {
  const [search, setSearch] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  // The list endpoint carries the title and the opening question, not every
  // turn: shipping whole conversations to draw this would mean sending the
  // evidence attached to each answer along with them.
  const filtered = useMemo(() => {
    if (!search.trim()) return history;
    const q = search.toLowerCase().trim();
    return history.filter(
      (s) => s.title.toLowerCase().includes(q)
        || s.preview?.toLowerCase().includes(q)
        || s.messages?.some((m) => m.text?.toLowerCase().includes(q)),
    );
  }, [history, search]);

  const grouped = useMemo(() => {
    const groups: Record<string, ChatSession[]> = {};
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today.getTime() - 86400000);
    const weekAgo = new Date(today.getTime() - 6 * 86400000);

    for (const session of filtered) {
      const d = new Date(session.updated_at);
      const dayStart = new Date(d.getFullYear(), d.getMonth(), d.getDate());
      let key: string;
      if (dayStart.getTime() === today.getTime()) key = ui(lang, "today");
      else if (dayStart.getTime() === yesterday.getTime()) key = ui(lang, "yesterday");
      else if (dayStart >= weekAgo) key = ui(lang, "thisWeek");
      else key = ui(lang, "earlier");

      if (!groups[key]) groups[key] = [];
      groups[key].push(session);
    }
    return groups;
  }, [filtered, lang]);

  async function handleDelete(id: number) {
    setBusy(true);
    try {
      await onDelete(id);
    } catch {}
    setBusy(false);
    setConfirmDeleteId(null);
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-history" onClick={(e) => e.stopPropagation()}>
        <div className="modal-history-head">
          <div className="modal-history-title-row">
            <History size={20} />
            <span className="modal-history-title">{ui(lang, "historyModal")}</span>
            <span className="modal-history-count">{history.length}</span>
            <button className="icon-btn" onClick={onClose}
                    title={ui(lang, "cancel")} aria-label={ui(lang, "cancel")}>
              <X size={18} />
            </button>
          </div>
          <div className="modal-history-search">
            <Search size={15} />
            <input type="text" className="modal-history-input"
              placeholder={lang === "vi" ? "Tìm kiếm lịch sử..." : "Search history..."}
              value={search} onChange={(e) => setSearch(e.target.value)} autoFocus />
            {search && (
              <button className="modal-history-clear" onClick={() => setSearch("")}
                      aria-label="Clear search"><X size={14} /></button>
            )}
          </div>
        </div>
        <div className="modal-history-body">
          {filtered.length === 0 ? (
            <div className="modal-history-empty">
              {search
                ? (lang === "vi" ? "Không tìm thấy kết quả" : "No results found")
                : (lang === "vi" ? "Chưa có lịch sử trò chuyện" : "No conversations yet")}
            </div>
          ) : (
            Object.entries(grouped).map(([groupLabel, sessions]) => (
              <div key={groupLabel} className="modal-history-group">
                <div className="modal-history-group-label">{groupLabel}</div>
                {sessions.map((session) => {
                  const userMessages = session.message_count
                    ?? session.messages?.filter((m) => m.role === "user").length ?? 0;
                  const preview = session.preview
                    ?? session.messages?.find((m) => m.role === "user")?.text ?? "";
                  return (
                    <div key={session.id} className="modal-history-item"
                      onClick={() => { onSelect(session); onClose(); }}
                      role="button" tabIndex={0}
                      onKeyDown={(e) => { if (e.key === "Enter") { onSelect(session); onClose(); } }}>
                      <div className="modal-history-item-icon">
                        <MessageSquare size={18} />
                      </div>
                      <div className="modal-history-item-body">
                        <div className="modal-history-item-title">
                          {session.title || ui(lang, "newChat")}
                        </div>
                        <div className="modal-history-item-meta">
                          <span className="modal-history-item-date">{formatDate(session.updated_at, lang)}</span>
                          <span className="modal-history-item-dot">·</span>
                          <span>{userMessages} {lang === "vi" ? "tin nhắn" : "messages"}</span>
                        </div>
                        {preview && <div className="modal-history-item-preview">{preview}</div>}
                      </div>
                      <div className="modal-history-item-actions">
                        {confirmDeleteId === session.id ? (
                          <div className="modal-history-confirm">
                            <span>{lang === "vi" ? "Xoá?" : "Delete?"}</span>
                            <button className="modal-history-confirm-yes"
                              onClick={(e) => { e.stopPropagation(); handleDelete(session.id); }}
                              disabled={busy}>{ui(lang, "deleteHistory")}</button>
                            <button className="modal-history-confirm-no"
                              onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(null); }}>
                              {lang === "vi" ? "Huỷ" : "Cancel"}</button>
                          </div>
                        ) : (
                          <button className="modal-history-delete-btn"
                            onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(session.id); }}
                            title={ui(lang, "deleteHistory")} aria-label={ui(lang, "deleteHistory")}>
                            <Trash2 size={15} />
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
