"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { SAMPLE_QUESTIONS, TRAP_QUESTIONS, ui } from "@/lib/i18n";
import type { ChatReply, Lang } from "@/lib/types";

interface Turn {
  role: "user" | "assistant";
  text: string;
  reply?: ChatReply;
}

const PROVENANCE: Record<string, string> = {
  llm: "prov_llm",
  llm_retry: "prov_llm_retry",
  deterministic: "prov_deterministic",
  deterministic_fallback: "prov_deterministic_fallback",
  llm_unavailable: "prov_llm_unavailable",
  llm_error: "prov_llm_error",
  smalltalk_canned: "prov_smalltalk_canned",
  guardrail: "prov_guardrail",
};

export function ChatPane({
  lang,
  onReply,
}: {
  lang: Lang;
  onReply: (reply: ChatReply) => void;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  // Vietnamese input goes through an IME. Enter pressed mid-composition is the
  // IME committing a syllable, not the user sending: submitting there clears
  // the box, and the composition that lands afterwards types the syllable back
  // into the empty box. Track composition and let the IME finish first.
  const composing = useRef(false);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, busy]);

  async function ask(question: string) {
    const text = question.trim();
    if (!text || busy) return;
    setError(null);
    setDraft("");
    setTurns((previous) => [...previous, { role: "user", text }]);
    setBusy(true);
    try {
      const reply = await api.chat(text, lang);
      setTurns((previous) => [
        ...previous,
        { role: "assistant", text: reply.answer, reply },
      ]);
      onReply(reply);
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : String(exception));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card chat">
      <div className="card-head">
        <span className="card-title">Nexa</span>
        <span className="badge badge-neutral">{ui(lang, "readOnly")}</span>
      </div>

      <div className="chat-log" ref={logRef}>
        {turns.length === 0 ? (
          <p className="empty">{ui(lang, "ask")}</p>
        ) : null}

        {turns.map((turn, index) => (
          <div
            className={turn.role === "user" ? "msg msg-user" : "msg"}
            key={index}
          >
            <div className="bubble">{turn.text}</div>
            {turn.reply ? (
              <div className="msg-meta">
                {turn.reply.refused ? (
                  <span className="badge badge-confirm">
                    {ui(lang, "prov_guardrail")}
                  </span>
                ) : null}
                <span className="chip">
                  <span className="k">{ui(lang, "provenance")}</span>
                  <span className="v">
                    {ui(lang, (PROVENANCE[turn.reply.source] ?? "prov_deterministic") as never)}
                  </span>
                </span>
                {turn.reply.tool ? (
                  <span className="chip">
                    <span className="k">tool</span>
                    <span className="v mono">{turn.reply.tool}</span>
                  </span>
                ) : null}
                {turn.reply.checks?.ungrounded_numbers?.length ? (
                  <span className="badge badge-nodata" title="Figures the model
                    produced that were not in the engine output were rejected.">
                    rejected: {turn.reply.checks.ungrounded_numbers.join(", ")}
                  </span>
                ) : null}
              </div>
            ) : null}
          </div>
        ))}

        {busy ? (
          <div className="msg">
            <div className="bubble">
              <span className="spinner" /> {ui(lang, "sending")}…
            </div>
          </div>
        ) : null}
        {error ? <p className="err">{error}</p> : null}
      </div>

      <div className="quick">
        <span className="chip">
          <span className="k">{ui(lang, "quickTitle")}</span>
        </span>
        {SAMPLE_QUESTIONS[lang].map((question) => (
          <button
            className="btn btn-sm"
            key={question}
            onClick={() => ask(question)}
            disabled={busy}
          >
            {question.length > 46 ? `${question.slice(0, 46)}…` : question}
          </button>
        ))}
      </div>
      <div className="quick">
        <span className="chip">
          <span className="k">{ui(lang, "trapTitle")}</span>
        </span>
        {TRAP_QUESTIONS[lang].map((question) => (
          <button
            className="btn btn-sm quick-trap"
            key={question}
            onClick={() => ask(question)}
            disabled={busy}
          >
            {question}
          </button>
        ))}
      </div>

      <div className="chat-input">
        <textarea
          value={draft}
          placeholder={ui(lang, "ask")}
          onChange={(event) => setDraft(event.target.value)}
          onCompositionStart={() => {
            composing.current = true;
          }}
          onBlur={() => {
            // compositionend cannot be relied on if focus leaves mid-syllable,
            // and a flag stuck at true would swallow Enter for good.
            composing.current = false;
          }}
          onCompositionEnd={(event) => {
            composing.current = false;
            // The value that lands with the composition is authoritative:
            // React's onChange for it can arrive after this event.
            setDraft((event.target as HTMLTextAreaElement).value);
          }}
          onKeyDown={(event) => {
            if (event.key !== "Enter" || event.shiftKey) return;
            // keyCode 229 is the pre-standard signal for the same thing.
            if (composing.current || event.nativeEvent.isComposing
                || event.keyCode === 229) {
              return;
            }
            event.preventDefault();
            ask(draft);
          }}
        />
        <button
          className="btn btn-primary"
          onClick={() => ask(draft)}
          disabled={busy || !draft.trim()}
        >
          {busy ? ui(lang, "sending") : ui(lang, "send")}
        </button>
      </div>
    </section>
  );
}
